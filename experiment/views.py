import os
import random

import pandas as pd
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.urls import reverse
from .models import *
from .telemetry_configs import get_dataset_config


def get_session_sequence():
    csv_path = os.path.join('data', 'tep_10vars_10sessions_ground_truth.csv')
    df = pd.read_csv(csv_path, usecols=['SESSION_ID'])
    return list(df['SESSION_ID'].unique())


def experiment_entry(request):
    """Entry point: Consent Form"""
    if request.method == 'POST':
        consented = request.POST.get('consent') == 'true'
        if consented:
            # Create a new participant record
            participant = Participant.objects.create()
            return redirect('experiment_intro', participant_id=participant.id)
        else:
            return render(request, 'experiment/consent.html', {'error': 'You must agree to participate in the study.'})

    return render(request, 'experiment/consent.html')


def experiment_intro(request, participant_id):
    """Introduction to the study goals and system role"""
    participant = get_object_or_404(Participant, pk=participant_id)

    if request.method == 'POST':
        return redirect('experiment_instructions', participant_id=participant.id)

    return render(request, 'experiment/intro.html', {'participant': participant})


import random
from django.shortcuts import render, redirect, get_object_or_404

def experiment_instructions(request, participant_id):
    participant = get_object_or_404(Participant, pk=participant_id)

    # 1. On GET request: Pick condition once and store it in Django's session
    if 'condition' not in request.session:
        request.session['condition'] = random.choice(['FIXED_LOW', 'FIXED_MEDIUM', 'ADAPTIVE_META'])

    condition = request.session['condition']

    # 2. On POST request: Read condition from session and create the trial
    if request.method == 'POST':
        sequence = get_session_sequence()
        first_fault = sequence[0] if sequence else 'Disturbance_01'

        first_trial = Trial.objects.create(
            participant=participant,
            fault_code=first_fault,
            condition=condition,
            completed=False
        )

        # Clear session key if you want a fresh condition for the next instructions page
        # del request.session['condition']

        return redirect('trial_dashboard', trial_id=first_trial.id)

    # 3. Render template with the condition from session
    return render(request, 'experiment/instructions.html', {
        'participant': participant,
        'condition': condition,
    })


def start_experiment(request):
    """
    Creates a new Participant and initializes their first trial (d00).
    Redirects directly to the active trial dashboard.
    """
    # 1. Create new participant
    participant = Participant.objects.create(assigned_condition='FIXED_MEDIUM')

    # 2. Initialize first dataset trial (Disturbance_01)
    first_trial = Trial.objects.create(
        participant=participant,
        fault_code='Disturbance_01',
        condition=participant.assigned_condition
    )

    # 3. Redirect to the newly created trial ID
    return redirect('trial_dashboard', trial_id=first_trial.id)


def trial_dashboard(request, trial_id):
    """
    Renders the SCADA Control Dashboard for a specific trial using dynamic CSV sequence.
    """
    trial = get_object_or_404(Trial, pk=trial_id)

    # 1. Get dataset configuration (defaults to 'TEP_10VARS')
    dataset_type = getattr(trial, 'dataset_type', 'TEP_10VARS')
    dataset_config = get_dataset_config(dataset_type)

    # 2. Context dictionary passed to template
    context = {
        'trial': trial,
        'condition': trial.condition,
        'dataset_config': dataset_config,
    }
    return render(request, 'experiment/trial_dashboard.html', context)


@require_POST
def submit_action(request, trial_id):
    trial = get_object_or_404(Trial, pk=trial_id)
    sequence = get_session_sequence()

    action_type = request.POST.get('action_type')
    try:
        time_step = int(request.POST.get('time_step', 1))
    except (ValueError, TypeError):
        time_step = 1

    selected_root_cause = request.POST.get('selected_root_cause', '')

    ActionLog.objects.create(
        trial=trial,
        time_step=time_step,
        action_type=action_type,
        selected_root_cause=selected_root_cause
    )

    # -------------------------------------------------------------
    # HANDLE CONFIRMED OVERRIDE: Demote LoA to 2 & keep monitoring
    # -------------------------------------------------------------
    if action_type in ['OVERRIDE', 'OVERRIDE_CONFIRMED']:
        if hasattr(trial, 'assigned_loa'):
            trial.assigned_loa = 2
        trial.is_overridden = True
        trial.save()

        if request.headers.get('HX-Request'):
            return HttpResponse(
                '<div class="bg-amber-950/80 border border-amber-500/80 text-amber-300 font-bold p-2.5 rounded shadow text-xs animate-fade-in">'
                '⚠️ System intervention overridden. Authority reduced to LoA 2 (Manual Monitoring). You are now responsible for detecting anomalies.'
                '</div>'
            )
        return JsonResponse({'success': True, 'message': 'Overridden. LoA reduced to 2.'})

    # -------------------------------------------------------------
    # HANDLE STOP ACTIONS: 'APPROVE' or 'RAISE_ALARM'
    # -------------------------------------------------------------
    if action_type in ['APPROVE', 'RAISE_ALARM']:
        trial.completed = True
        trial.is_active = False
        trial.save()

        has_fault = getattr(trial, 'has_fault', trial.fault_code != 'NOMINAL')
        fault_start_step = getattr(trial, 'fault_start_step', 10)

        if action_type == 'RAISE_ALARM':
            is_correct = has_fault
            ttd_steps = max(0, time_step - fault_start_step) if is_correct else 0
        else:  # APPROVE
            is_correct = has_fault
            ttd_steps = max(0, time_step - fault_start_step) if is_correct else 0

        try:
            curr_idx = sequence.index(trial.fault_code)
        except ValueError:
            curr_idx = 0

        if curr_idx + 1 < len(sequence):
            next_fault = sequence[curr_idx + 1]
            next_trial = Trial.objects.create(
                participant=trial.participant,
                fault_code=next_fault,
                condition=trial.condition
            )
            next_url = reverse('trial_dashboard', kwargs={'trial_id': next_trial.id})
        else:
            next_url = reverse('nasa_tlx', kwargs={'participant_id': trial.participant.id})

        if request.headers.get('HX-Request'):
            response = HttpResponse('<div class="text-emerald-400 font-bold p-2">Loading next scenario...</div>')
            response['HX-Redirect'] = next_url
            return response

        return redirect(next_url)

    return JsonResponse({'success': True, 'message': 'Action recorded.'})

def nasa_tlx(request, participant_id):
    """
    Renders and handles the NASA-TLX workload survey after all trial datasets are completed.
    """
    participant = get_object_or_404(Participant, pk=participant_id)

    if request.method == 'POST':
        # 1. Extract values from the form POST request
        mental_demand = int(request.POST.get('mental_demand', 50))
        physical_demand = int(request.POST.get('physical_demand', 50))
        temporal_demand = int(request.POST.get('temporal_demand', 50))
        performance = int(request.POST.get('performance', 50))
        effort = int(request.POST.get('effort', 50))
        frustration = int(request.POST.get('frustration', 50))

        # 2. Save or update the NasaTlxResponse instance
        NasaTlxResponse.objects.update_or_create(
            participant=participant,
            defaults={
                'mental_demand': mental_demand,
                'physical_demand': physical_demand,
                'temporal_demand': temporal_demand,
                'performance': performance,
                'effort': effort,
                'frustration': frustration,
            }
        )

        # 3. Redirect to your next route (replace 'debriefing' or 'thank_you' with your actual view name)
        return redirect('debriefing', participant_id=participant.id)

    return render(request, 'experiment/nasa_tlx.html', {'participant': participant})

def debriefing_view(request, participant_id):
    """
    Renders the final thank-you/debriefing screen after the NASA-TLX survey.
    """
    participant = get_object_or_404(Participant, pk=participant_id)
    return render(request, 'experiment/debriefing.html', {'participant': participant})
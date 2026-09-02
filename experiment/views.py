import os
import random
import logging

import pandas as pd
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.urls import reverse
from .models import *
from .telemetry_configs import get_dataset_config

logger = logging.getLogger(__name__)


def get_session_sequence():
    logger.info("Fetching session sequence from CSV.")
    csv_path = os.path.join('data', 'tep_10vars_10sessions_ground_truth.csv')
    try:
        df = pd.read_csv(csv_path, usecols=['SESSION_ID'])
        sequence = list(df['SESSION_ID'].unique())
        logger.info(f"Successfully loaded session sequence with {len(sequence)} items.")
        return sequence
    except Exception as e:
        logger.error(f"Failed to read session sequence CSV from {csv_path}: {e}", exc_info=True)
        raise


def experiment_entry(request):
    """Entry point: Consent Form"""
    logger.info(f"experiment_entry called with method {request.method}.")
    if request.method == 'POST':
        consented = request.POST.get('consent') == 'true'
        logger.info(f"Consent submitted: {consented}")
        if consented:
            # Create a new participant record
            participant = Participant.objects.create()
            logger.info(f"Created new participant with ID: {participant.id}")
            return redirect('experiment_intro', participant_id=participant.id)
        else:
            logger.warning("User submitted consent form without agreeing.")
            return render(request, 'experiment/consent.html', {'error': 'You must agree to participate in the study.'})

    return render(request, 'experiment/consent.html')


def experiment_intro(request, participant_id):
    """Introduction to the study goals and system role"""
    logger.info(f"experiment_intro called for participant_id: {participant_id} with method {request.method}.")
    participant = get_object_or_404(Participant, pk=participant_id)

    if request.method == 'POST':
        logger.info(f"Participant {participant_id} proceeding to instructions.")
        return redirect('experiment_instructions', participant_id=participant.id)

    return render(request, 'experiment/intro.html', {'participant': participant})


import random
from django.shortcuts import render, redirect, get_object_or_404

def experiment_instructions(request, participant_id):
    logger.info(f"experiment_instructions called for participant_id: {participant_id} with method {request.method}.")
    participant = get_object_or_404(Participant, pk=participant_id)

    # 1. On GET request: Pick condition once and store it in Django's session
    if 'condition' not in request.session:
        chosen_condition = random.choice(['FIXED_LOW', 'FIXED_MEDIUM', 'ADAPTIVE_META'])
        request.session['condition'] = chosen_condition
        logger.info(f"Assigned new condition '{chosen_condition}' to session for participant {participant_id}.")

    condition = request.session['condition']
    logger.info(f"Current active session condition for participant {participant_id}: {condition}")

    # 2. On POST request: Read condition from session and create the trial
    if request.method == 'POST':
        logger.info(f"Creating first trial for participant {participant_id}.")
        sequence = get_session_sequence()
        first_fault = sequence[0] if sequence else 'Disturbance_01'
        logger.info(f"First fault assigned: {first_fault}")

        first_trial = Trial.objects.create(
            participant=participant,
            fault_code=first_fault,
            condition=condition,
            completed=False
        )
        logger.info(f"Successfully created first trial with ID: {first_trial.id}")

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
    logger.info("start_experiment view triggered.")
    # 1. Create new participant
    participant = Participant.objects.create(assigned_condition='FIXED_MEDIUM')
    logger.info(f"Created participant {participant.id} with condition FIXED_MEDIUM.")

    # 2. Initialize first dataset trial (Disturbance_01)
    first_trial = Trial.objects.create(
        participant=participant,
        fault_code='Disturbance_01',
        condition=participant.assigned_condition
    )
    logger.info(f"Initialized trial {first_trial.id} for participant {participant.id}.")

    # 3. Redirect to the newly created trial ID
    return redirect('trial_dashboard', trial_id=first_trial.id)


def trial_dashboard(request, trial_id):
    """
    Renders the SCADA Control Dashboard for a specific trial using dynamic CSV sequence.
    """
    logger.info(f"trial_dashboard accessed for trial_id: {trial_id}")
    trial = get_object_or_404(Trial, pk=trial_id)

    # 1. Get dataset configuration (defaults to 'TEP_10VARS')
    dataset_type = getattr(trial, 'dataset_type', 'TEP_10VARS')
    logger.info(f"Loading dataset_config for type: {dataset_type}")
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
    logger.info(f"submit_action called for trial_id: {trial_id}")
    trial = get_object_or_404(Trial, pk=trial_id)
    sequence = get_session_sequence()

    action_type = request.POST.get('action_type')
    try:
        time_step = int(request.POST.get('time_step', 1))
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid time_step received for trial {trial_id}: {request.POST.get('time_step')}. Defaulting to 1. Error: {e}")
        time_step = 1

    selected_root_cause = request.POST.get('selected_root_cause', '')
    logger.info(f"Processing action_type: '{action_type}', time_step: {time_step}, selected_root_cause: '{selected_root_cause}' for trial {trial_id}")

    action_log = ActionLog.objects.create(
        trial=trial,
        time_step=time_step,
        action_type=action_type,
        selected_root_cause=selected_root_cause
    )
    logger.info(f"Created ActionLog entry with ID: {action_log.id}")

    # -------------------------------------------------------------
    # HANDLE CONFIRMED OVERRIDE: Demote LoA to 2 & keep monitoring
    # -------------------------------------------------------------
    if action_type in ['OVERRIDE', 'OVERRIDE_CONFIRMED']:
        logger.info(f"Handling override action for trial {trial_id}.")
        if hasattr(trial, 'assigned_loa'):
            trial.assigned_loa = 2
        trial.is_overridden = True
        trial.save()
        logger.info(f"Trial {trial_id} updated: is_overridden=True, assigned_loa=2.")

        if request.headers.get('HX-Request'):
            logger.info(f"Returning HTMX response for override in trial {trial_id}.")
            return HttpResponse(
                '<div class="bg-amber-950/80 border border-amber-500/80 text-amber-300 font-bold p-2.5 rounded shadow text-xs animate-fade-in">'
                '⚠️ System intervention overridden. Authority reduced to LoA 2 (Manual Monitoring). You are now responsible for detecting anomalies.'
                '</div>'
            )
        logger.info(f"Returning JSON response for override in trial {trial_id}.")
        return JsonResponse({'success': True, 'message': 'Overridden. LoA reduced to 2.'})

    # -------------------------------------------------------------
    # HANDLE STOP ACTIONS: 'APPROVE' or 'RAISE_ALARM'
    # -------------------------------------------------------------
    if action_type in ['APPROVE', 'RAISE_ALARM']:
        logger.info(f"Handling stop action '{action_type}' for trial {trial_id}.")
        trial.completed = True
        trial.is_active = False
        trial.save()
        logger.info(f"Trial {trial_id} marked as completed and inactive.")

        has_fault = getattr(trial, 'has_fault', trial.fault_code != 'NOMINAL')
        fault_start_step = getattr(trial, 'fault_start_step', 10)

        if action_type == 'RAISE_ALARM':
            is_correct = has_fault
            ttd_steps = max(0, time_step - fault_start_step) if is_correct else 0
        else:  # APPROVE
            is_correct = has_fault
            ttd_steps = max(0, time_step - fault_start_step) if is_correct else 0

        logger.info(f"Action evaluation for trial {trial_id}: has_fault={has_fault}, is_correct={is_correct}, ttd_steps={ttd_steps}")

        try:
            curr_idx = sequence.index(trial.fault_code)
        except ValueError:
            logger.warning(f"Fault code '{trial.fault_code}' not found in sequence. Defaulting index to 0.")
            curr_idx = 0

        if curr_idx + 1 < len(sequence):
            next_fault = sequence[curr_idx + 1]
            logger.info(f"Next fault in sequence identified: '{next_fault}'")
            next_trial = Trial.objects.create(
                participant=trial.participant,
                fault_code=next_fault,
                condition=trial.condition
            )
            logger.info(f"Created next trial with ID: {next_trial.id}")
            next_url = reverse('trial_dashboard', kwargs={'trial_id': next_trial.id})
        else:
            logger.info(f"Reached end of sequence for participant {trial.participant.id}. Redirecting to NASA-TLX.")
            next_url = reverse('nasa_tlx', kwargs={'participant_id': trial.participant.id})

        if request.headers.get('HX-Request'):
            logger.info(f"Returning HTMX redirect to '{next_url}' for trial {trial_id}.")
            response = HttpResponse('<div class="text-emerald-400 font-bold p-2">Loading next scenario...</div>')
            response['HX-Redirect'] = next_url
            return response

        logger.info(f"Redirecting to '{next_url}' for trial {trial_id}.")
        return redirect(next_url)

    logger.info(f"Standard action recorded for trial {trial_id}. Returning JSON response.")
    return JsonResponse({'success': True, 'message': 'Action recorded.'})

def nasa_tlx(request, participant_id):
    """
    Renders and handles the NASA-TLX workload survey after all trial datasets are completed.
    """
    logger.info(f"nasa_tlx called for participant_id: {participant_id} with method {request.method}.")
    participant = get_object_or_404(Participant, pk=participant_id)

    if request.method == 'POST':
        # 1. Extract values from the form POST request
        mental_demand = int(request.POST.get('mental_demand', 50))
        physical_demand = int(request.POST.get('physical_demand', 50))
        temporal_demand = int(request.POST.get('temporal_demand', 50))
        performance = int(request.POST.get('performance', 50))
        effort = int(request.POST.get('effort', 50))
        frustration = int(request.POST.get('frustration', 50))

        logger.info(f"Received NASA-TLX metrics for participant {participant_id}: "
                    f"Mental={mental_demand}, Physical={physical_demand}, Temporal={temporal_demand}, "
                    f"Performance={performance}, Effort={effort}, Frustration={frustration}")

        # 2. Save or update the NasaTlxResponse instance
        response_obj, created = NasaTlxResponse.objects.update_or_create(
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
        logger.info(f"NasaTlxResponse {'created' if created else 'updated'} for participant {participant_id}.")

        # 3. Redirect to your next route (replace 'debriefing' or 'thank_you' with your actual view name)
        return redirect('debriefing', participant_id=participant.id)

    return render(request, 'experiment/nasa_tlx.html', {'participant': participant})

def debriefing_view(request, participant_id):
    """
    Renders the final thank-you/debriefing screen after the NASA-TLX survey.
    """
    logger.info(f"debriefing_view accessed for participant_id: {participant_id}")
    participant = get_object_or_404(Participant, pk=participant_id)
    return render(request, 'experiment/debriefing.html', {'participant': participant})
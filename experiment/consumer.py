import os
import json
import asyncio
import pandas as pd
import numpy as np
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from .models import *

from django.urls import reverse
from .telemetry_configs import get_dataset_config


_CSV_CACHE = None


def load_master_csv():
    global _CSV_CACHE
    if _CSV_CACHE is not None:
        return _CSV_CACHE

    csv_path = os.path.join('data', 'tep_10vars_10sessions_ground_truth.csv')
    df = pd.read_csv(csv_path)

    # Standardize column names to avoid KeyError (e.g. 'Step' vs 'STEP' vs 'step')
    df.columns = df.columns.str.strip()

    # Standardize SESSION_ID values
    if 'SESSION_ID' in df.columns:
        df['SESSION_ID'] = df['SESSION_ID'].astype(str).str.strip()

    _CSV_CACHE = df
    return _CSV_CACHE


def get_session_sequence():
    """Extracts unique session IDs in order from CSV."""
    df = load_master_csv()
    return list(df['SESSION_ID'].unique())


class TrialConsumer(AsyncWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trial_data = {
            'session_id': 'Disturbance_01',
            'condition': 'ADAPTIVE_META',
            'next_url': '/dashboard/'
        }

    async def connect(self):
        await self.accept()

        info = await self.get_trial_info()
        if info:
            self.trial_data = info

        await self.send(text_data=json.dumps({
            'session_id': self.trial_data['session_id'],
            'condition': self.trial_data['condition'],
            'time_step': 1,
            'trial_complete': False
        }))

        self.streaming_task = asyncio.create_task(self.stream_tep_data())

    async def disconnect(self, close_code):
        if hasattr(self, 'streaming_task') and not self.streaming_task.done():
            self.streaming_task.cancel()
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    @sync_to_async
    def get_trial_info(self):
        try:
            url_kwargs = self.scope.get('url_route', {}).get('kwargs', {})
            raw_id = url_kwargs.get('trial_id') or url_kwargs.get('id') or url_kwargs.get('pk')

            if not raw_id:
                raise ValueError("No trial ID found in URL parameters")

            trial = Trial.objects.select_related('participant').get(pk=int(raw_id))
            session_list = get_session_sequence()
            current_session = str(trial.fault_code).strip()
            participant_id = trial.participant.id if trial.participant else 'DEFAULT'

            try:
                curr_idx = session_list.index(current_session)
                if curr_idx + 1 < len(session_list):
                    next_fault = session_list[curr_idx + 1]

                    # Get or create the next trial database record
                    next_trial, _ = Trial.objects.get_or_create(
                        participant=trial.participant,
                        fault_code=next_fault,
                        condition=trial.condition
                    )
                    next_url = reverse('trial_dashboard', kwargs={'trial_id': next_trial.id})
                else:
                    next_url = reverse('nasa_tlx', kwargs={'participant_id': participant_id})
            except (ValueError, Exception) as e:
                print(f"Error determining next trial: {e}")
                next_url = reverse('nasa_tlx', kwargs={'participant_id': participant_id})

            return {
                'trial_id': trial.id,
                'session_id': current_session,
                'condition': trial.condition,
                'next_url': next_url,
                'session_sequence': session_list
            }
        except Exception as e:
            print(f"Error fetching trial info: {e}")
            return {
                'session_id': 'Disturbance_01',
                'condition': 'ADAPTIVE_META',
                'next_url': '/dashboard/'
            }

    async def stream_tep_data(self):
        try:
            session_id = str(self.trial_data.get('session_id', 'Disturbance_01')).strip()
            condition = self.trial_data.get('condition', 'ADAPTIVE_META')
            next_url = self.trial_data.get('next_url', '/dashboard/')

            master_df = load_master_csv()

            # Find the step column robustly
            step_col = next((c for c in master_df.columns if c.lower() == 'step'), None)
            if not step_col:
                print("❌ ERROR: Could not find any column named 'step' or 'STEP' in CSV!")
                return

            session_df = master_df[master_df['SESSION_ID'] == session_id].sort_values(step_col)
            fault_rows = session_df[session_df['SYSTEM_GROUND_TRUTH_FAULT_ID'] != 0]

            if not fault_rows.empty:
                first_fault = fault_rows[step_col].iloc[0]
            else:
                first_fault = float('inf')

            if len(session_df) == 0:
                print(f"❌ WARNING: CSV has 0 rows matching SESSION_ID '{session_id}'")
                return

            for _, row in session_df.iterrows():
                step_idx = int(row[step_col]) if step_col else 1
                has_fault = bool(step_idx >= first_fault)
                vars_data = {}
                alarms = {}

                dataset_config = get_dataset_config('TEP_10VARS')
                SELECTED_NAMES = [s['key'] for s in dataset_config.get('sensors', [])]

                for key in SELECTED_NAMES:
                    val = float(row[key]) if key in row else 0.0
                    vars_data[key] = round(val, 2)

                    hi_alarm = int(row.get(f"ALM_{key}_HI", 0))
                    lo_alarm = int(row.get(f"ALM_{key}_LO", 0))
                    alarms[f"{key}_alarm"] = bool(hi_alarm or lo_alarm)

                system_fault = int(row.get('SYSTEM_GROUND_TRUTH_FAULT_ID', 0))
                is_alarm_flood = bool(row.get('ALARM_FLOOD_ACTIVE', 0))

                active_alarm_count = sum(alarms.values())
                ai_risk = float(np.clip(active_alarm_count / 5.0, 0.0, 1.0))
                novelty = 0.85 if is_alarm_flood else round(ai_risk * 0.7, 2)
                workload = float(np.clip(0.15 + (ai_risk * 0.50), 0.15, 1.0))

                if condition == 'FIXED_LOW':
                    assigned_loa = 2
                elif condition == 'FIXED_MEDIUM':
                    assigned_loa = 4
                else:
                    assigned_loa = 2 if (novelty > 0.65 or ai_risk > 0.75) else (
                        4 if (novelty > 0.35 or ai_risk > 0.45) else 8)

                predicted_root_cause = f"Multivariate Anomaly (IDV{system_fault})" if system_fault > 0 else "System Nominal"

                # Trigger Modal Flag for Frontend Interventions
                system_triggered_stop = False
                auto_executed = False
                action_message = ""

                if assigned_loa >= 8:
                    auto_executed = True
                    action_message = f"Autonomous Override Executed: Mitigated {predicted_root_cause}"
                if assigned_loa >= 4 and ai_risk >= 0.45:
                    system_triggered_stop = True
                    action_message = f"System Intervention Required: High Risk Detected ({ai_risk:.2f})"

                payload = {
                    'time_step': step_idx,
                    'has_fault': has_fault,
                    'vars': vars_data,
                    'alarms': alarms,
                    'situational_novelty': round(novelty, 2),
                    'ai_risk': round(ai_risk, 2),
                    'operator_workload': round(workload, 2),
                    'assigned_loa': assigned_loa,
                    'predicted_root_cause': predicted_root_cause,
                    'suggested_root_cause': predicted_root_cause,
                    'system_triggered_stop': system_triggered_stop,
                    'trust_score': round(float(np.clip(1.0 - (novelty * 0.50), 0.40, 0.99)), 2),
                    'auto_executed': auto_executed,
                    'action_message': action_message
                }

                await self.send(text_data=json.dumps(payload))

                # --- AUTO-TIMEOUT AT STEP 960 ---
                if step_idx >= 960:
                    break

                await asyncio.sleep(0.15)

            # Mark current trial completed in DB
            trial_id = self.trial_data.get('trial_id')
            if trial_id:
                await sync_to_async(Trial.objects.filter(id=trial_id).update)(completed=True)

            # Trigger frontend redirect to next distribution
            await self.send(text_data=json.dumps({
                'trial_complete': True,
                'next_url': next_url,
                'has_fault': has_fault,
                'fault_code': self.trial_data.get('fault_code', 'NOMINAL')
            }))

        except asyncio.CancelledError:
            print("DEBUG: Stream task cancelled on disconnect.")
        except Exception as e:
            print(f"❌ EXCEPTION IN STREAM LOOP: {e}")
from django.db import models
import uuid


class Participant(models.Model):
    """
    Represents an operator/subject in the experiment.
    """
    id = models.CharField(max_length=64, primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # Updated to match consumer conditions (FIXED_LOW, FIXED_MEDIUM, ADAPTIVE_META)
    assigned_condition = models.CharField(
        max_length=32,
        choices=[
            ('FIXED_LOW', 'Fixed Low (LoA 2)'),
            ('FIXED_MEDIUM', 'Fixed Medium (LoA 4)'),
            ('ADAPTIVE_META', 'Adaptive Metacognitive LoA'),
        ],
        default='ADAPTIVE_META'
    )

    def __str__(self):
        return f"Participant {str(self.id)[:8]}"


class Trial(models.Model):
    """
    Tracks a single fault scenario execution for a participant.
    """
    # Updated choices to match exact CSV SESSION_ID values
    FAULT_CODE_CHOICES = [
        ('Disturbance_01', 'Disturbance 01'),
        ('Disturbance_02', 'Disturbance 02'),
        ('Disturbance_04', 'Disturbance 04'),
        ('Disturbance_06', 'Disturbance 06'),
        ('Disturbance_07', 'Disturbance 07'),
        ('Disturbance_08', 'Disturbance 08'),
        ('Disturbance_11', 'Disturbance 11'),
        ('Disturbance_12', 'Disturbance 12'),
        ('Disturbance_14', 'Disturbance 14'),
        ('Disturbance_18', 'Disturbance 18'),
    ]

    CONDITION_CHOICES = [
        ('FIXED_LOW', 'Fixed Low'),
        ('FIXED_MEDIUM', 'Fixed Medium'),
        ('ADAPTIVE_META', 'Adaptive Meta'),
    ]

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='trials')
    fault_code = models.CharField(
        max_length=32,
        choices=FAULT_CODE_CHOICES,
        default='Disturbance_01',
        help_text="Matches exact SESSION_ID in tep_10vars_10sessions_ground_truth.csv"
    )
    condition = models.CharField(
        max_length=32,
        choices=CONDITION_CHOICES,
        default='ADAPTIVE_META'
    )

    start_time = models.DateTimeField(auto_now_add=True)
    completed = models.BooleanField(default=False)

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f"Trial #{self.id} | Participant {str(self.participant_id)[:8]} | {self.fault_code}"


class ActionLog(models.Model):
    """
    Logs every operator interaction during a trial.
    """
    ACTION_TYPES = [
        ('RAISE_ALARM', 'Raised Anomaly Alarm (TTD)'),
        ('SUBMIT_RCA', 'Submitted Root Cause Diagnosis'),
        ('APPROVE', 'Executed AI Action'),
        ('OVERRIDE', 'Overrode AI / Manual Control'),
    ]

    trial = models.ForeignKey(Trial, on_delete=models.CASCADE, related_name='action_logs')
    timestamp = models.DateTimeField(auto_now_add=True)
    time_step = models.IntegerField(help_text="Simulation step (1-960) when action occurred")
    action_type = models.CharField(max_length=32, choices=ACTION_TYPES)
    selected_root_cause = models.CharField(max_length=64, blank=True, null=True, help_text="Populated for SUBMIT_RCA")

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"Action [{self.action_type}] @ Step {self.time_step} (Trial #{self.trial_id})"


class NasaTlxResponse(models.Model):
    """
    Stores the subjective workload assessment completed after all trial datasets.
    """
    participant = models.OneToOneField(Participant, on_delete=models.CASCADE, related_name='nasa_tlx')
    submitted_at = models.DateTimeField(auto_now_add=True)

    mental_demand = models.IntegerField(default=50)
    physical_demand = models.IntegerField(default=50)
    temporal_demand = models.IntegerField(default=50)
    performance = models.IntegerField(default=50)
    effort = models.IntegerField(default=50)
    frustration = models.IntegerField(default=50)

    def calculate_raw_score(self):
        """Calculates unweighted Raw NASA-TLX (RTLX) average score."""
        scores = [
            self.mental_demand, self.physical_demand, self.temporal_demand,
            self.performance, self.effort, self.frustration
        ]
        return sum(scores) / len(scores)

    def __str__(self):
        return f"NASA-TLX for Participant {str(self.participant_id)[:8]} (Score: {self.calculate_raw_score():.1f})"
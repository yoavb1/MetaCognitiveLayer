from django.urls import path
from django.views.generic.base import RedirectView
from . import views

# urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.experiment_entry, name='experiment_consent'),
    path('intro/<uuid:participant_id>/', views.experiment_intro, name='experiment_intro'),
    path('instructions/<uuid:participant_id>/', views.experiment_instructions, name='experiment_instructions'),
    path('', views.start_experiment, name='start_experiment'),
    path('trial/<int:trial_id>/', views.trial_dashboard, name='trial_dashboard'),
    path('trial/<int:trial_id>/submit/', views.submit_action, name='submit_action'),
    path('participant/<str:participant_id>/nasa-tlx/', views.nasa_tlx, name='nasa_tlx'),
    path('debriefing/<uuid:participant_id>/', views.debriefing_view, name='debriefing'),
]
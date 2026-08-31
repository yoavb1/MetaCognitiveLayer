# routing.py
from django.urls import re_path
from . import consumer

websocket_urlpatterns = [
    # Uses regex to match integer trial_id cleanly
    re_path(r'ws/trial/(?P<trial_id>\d+)/$', consumer.TrialConsumer.as_asgi()),
]
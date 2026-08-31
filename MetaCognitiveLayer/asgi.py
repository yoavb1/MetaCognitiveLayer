"""
ASGI config for MetaCognitiveLayer project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/asgi/
"""

import os

import experiment.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MetaCognitiveLayer.settings')

# 2. Initialize Django ASGI application early
from django.core.asgi import get_asgi_application
django_asgi_app = get_asgi_application()

# 3. Import channels routing AFTER get_asgi_application()
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import experiment.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            experiment.routing.websocket_urlpatterns
        )
    ),
})
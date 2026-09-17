"""
ASGI config for prathamesp32_project project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from core.routing import websocket_urlpatterns  # 'core' app ki routing import ki gayi hai

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'prathamesp32_project.settings')

# Standard Django ASGI application initialize karein
django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": URLRouter(websocket_urlpatterns),  # WebSocket routing yahan enable kar di gayi hai
})

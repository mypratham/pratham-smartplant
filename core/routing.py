from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Purana route (as it is rakha gaya hai)
    re_path(r"^ws/mcp/?$", consumers.MCPServerConsumer.as_asgi()),

    # ESP32 audio WebSocket route; captures the ID from the URL
    re_path(r"^ws/audio/(?P<device_id>[^/]+)/?$",
        consumers.AudioConsumer.as_asgi(),
    ),

]
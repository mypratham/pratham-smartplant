from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Purana route (as it is rakha gaya hai)
    re_path(r"^ws/mcp/?$", consumers.MCPServerConsumer.as_asgi()),

]
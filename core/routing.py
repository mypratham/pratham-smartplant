from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # ? lagane se /ws/mcp/ aur /ws/mcp dono requests bina 301 error ke accept ho jayengi
    re_path(r"^ws/mcp/?$", consumers.MCPServerConsumer.as_asgi()),
]
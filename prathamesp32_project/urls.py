"""
URL configuration for prathamesp32_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core.views import (
    dashboard,
    device_command,
    device_heartbeat,
    plant_ai_config_view,
    unified_plant_ai_chat_view,
    knowledge_base_api,
    view_document_chunks,
    update_chunk_api,
    delete_chunk_api,
    set_reminder_api,
    update_delete_reminder_api, 
    audio_upload_view,
    device_pair,      # 👈 Yahan add kar diya gaya hai
    check_pairing,    # 👈 Yahan add kar diya gaya hai
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', dashboard, name='dashboard'),
    path('api/devices/<str:plant_id>/command/', device_command, name='device_command'),
    path('api/devices/<str:plant_id>/heartbeat/', device_heartbeat, name='device_heartbeat'),
    path('api/devices/<str:plant_id>/ai-config/', plant_ai_config_view, name='plant_ai_config'),
    path('api/devices/<str:plant_id>/ai-chat/', unified_plant_ai_chat_view, name='unified_plant_ai_chat'),
    path('api/devices/<str:plant_id>/responses/', unified_plant_ai_chat_view, name='device_responses'),
    path('api/knowledge-base/', knowledge_base_api, name='knowledge_base_api'),
    path('api/knowledge-base/chunks/<int:doc_id>/', view_document_chunks, name='view_document_chunks'),
    path('api/knowledge-base/chunk/update/<int:chunk_id>/', update_chunk_api, name='update_chunk_api'),
    path('api/knowledge-base/chunk/delete/<int:chunk_id>/', delete_chunk_api, name='delete_chunk_api'),
    path('api/devices/<str:plant_id>/reminder/', set_reminder_api, name='set_reminder'),
    path('api/devices/<str:plant_id>/reminder/<int:reminder_id>/', update_delete_reminder_api, name='update_delete_reminder'),
    path('api/devices/<str:plant_id>/audio/', audio_upload_view, name='audio_upload'),
    path('api/devices/pair/', device_pair, name='device_pair'),
    path('api/devices/check-pairing/', check_pairing, name='check_pairing'),
]

# Media files serve karne ke liye yeh zaroor add karein taaki 404 error na aaye:
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
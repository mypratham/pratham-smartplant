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
from django.urls import re_path
from django.views.static import serve
from django.views.generic import RedirectView
from core.views import admin_dashboard
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
    admin_login_api,      # <-- Yahan add karein
    admin_register_api    # <-- Yahan add karein
    )

from core.views import device_settings_api

from core.views import device_language_api

from core.views import device_settings_page, settings_login_api, my_devices_api

from core.views import device_contacts_api, device_contact_detail_api, device_contacts_import_api

from core.views import device_telegram_sync_api

from core.views import admin_devices_api, admin_notices_api, admin_notice_cancel_api

from core.views import device_admin_page

urlpatterns = [
    path('device-admin/', device_admin_page, name='device_admin_page'),
    path('api/admin/devices/', admin_devices_api, name='admin_devices'),
    path('api/admin/notices/', admin_notices_api, name='admin_notices'),
    path('api/admin/notices/<int:notice_id>/', admin_notice_cancel_api, name='admin_notice_cancel'),
    path('api/devices/<str:plant_id>/telegram/sync/', device_telegram_sync_api, name='device_telegram_sync'),
    path('api/devices/<str:plant_id>/contacts/', device_contacts_api, name='device_contacts'),
    path('api/devices/<str:plant_id>/contacts/import/', device_contacts_import_api, name='device_contacts_import'),
    path('api/devices/<str:plant_id>/contacts/<int:contact_id>/', device_contact_detail_api, name='device_contact_detail'),
    path('device-settings/', device_settings_page, name='device_settings_page'),
    path('api/settings-login/', settings_login_api, name='settings_login'),
    path('api/my-devices/', my_devices_api, name='my_devices'),
    path('api/devices/<str:plant_id>/language/', device_language_api, name='device_language'),
    path('api/devices/<str:plant_id>/settings/', device_settings_api, name='device_settings'),
    # 1. Admin & Dashboard Routes
    path('admin/', admin.site.urls),
    path('', dashboard, name='dashboard'),
    path("admin-dashboard/", admin_dashboard, name="admin_dashboard"),
    path('api/admin/login/', admin_login_api, name='admin_login_api'),
    path('api/admin/register/', admin_register_api, name='admin_register_api'),
    path("flash/", RedirectView.as_view(url="/flash/install.html")),
    re_path(r"^flash/(?P<path>.+)$", serve, {"document_root": settings.BASE_DIR / "flash"}),
    
    # 2. STATIC Device Endpoints (MUST COME BEFORE <str:plant_id>)
    # Pehle static routes check hone chahiye taaki 'check-pairing' ko Django plant_id na samajh le
    path('api/devices/pair/', device_pair, name='device_pair'),
    path('api/devices/check-pairing/', check_pairing, name='check_pairing'),
    
    # 3. DYNAMIC Device Specific Endpoints (<str:plant_id>)
    path('api/devices/<str:plant_id>/command/', device_command, name='device_command'),
    path('api/devices/<str:plant_id>/heartbeat/', device_heartbeat, name='device_heartbeat'),
    path('api/devices/<str:plant_id>/ai-config/', plant_ai_config_view, name='plant_ai_config'),
    path('api/devices/<str:plant_id>/ai-chat/', unified_plant_ai_chat_view, name='unified_plant_ai_chat'),
    path('api/devices/<str:plant_id>/responses/', unified_plant_ai_chat_view, name='device_responses'),
    path(
        "api/reminder/<str:plant_id>/",
        set_reminder_api,
        name="set_reminder_api"
    ),

    path(
        "api/reminder/<str:plant_id>/<int:reminder_id>/",
        update_delete_reminder_api,
        name="update_delete_reminder_api"
    ),
    path('api/devices/<str:plant_id>/audio/', audio_upload_view, name='audio_upload'),

    # 4. Knowledge Base Endpoints
    path('api/knowledge-base/', knowledge_base_api, name='knowledge_base_api'),
    path('api/knowledge-base/chunks/<int:doc_id>/', view_document_chunks, name='view_document_chunks'),
    path('api/knowledge-base/chunk/update/<int:chunk_id>/', update_chunk_api, name='update_chunk_api'),
    path('api/knowledge-base/chunk/delete/<int:chunk_id>/', delete_chunk_api, name='delete_chunk_api'),
]

# Media files serve in DEBUG mode
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
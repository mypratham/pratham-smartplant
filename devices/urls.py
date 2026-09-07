from django.urls import path

from .views import (
    DeviceListCreateView,
    DeviceDetailView,
    DeviceHeartbeatView,
    DeviceStatusView,
    DeviceConfigView,
    QROnboardView,
    DeviceAIChatView,
)

urlpatterns = [

    path(
        "",
        DeviceListCreateView.as_view(),
        name="device-list-create"
    ),

    path(
        "<str:plant_id>/",
        DeviceDetailView.as_view(),
        name="device-detail"
    ),

    path(
        "<str:plant_id>/heartbeat/",
        DeviceHeartbeatView.as_view(),
        name="device-heartbeat"
    ),

    path(
        "<str:plant_id>/status/",
        DeviceStatusView.as_view(),
        name="device-status"
    ),

    path(
        "<str:plant_id>/config/",
        DeviceConfigView.as_view(),
        name="device-config"
    ),

    path(
        "<str:plant_id>/ai-chat/",
        DeviceAIChatView.as_view(),
        name="device-ai-chat"
    ),

    path(
        "onboard/",
        QROnboardView.as_view(),
        name="device-onboard"
    ),
]
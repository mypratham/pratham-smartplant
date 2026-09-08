from django.urls import path

from .views import (
    DeviceListCreateView,
    DeviceDetailView,
    DeviceHeartbeatView,
    DeviceStatusView,
    DeviceConfigView,
    DeviceAIChatView,
    DeviceAIStatusView,
    SaveTouchView,
    SaveRemindersView,
    SaveConfigView,
    PowerToggleView,
    RestartView,
    QROnboardView,
    plant_dashboard_view,
)


urlpatterns = [

    # -----------------------------------------------------
    # DEVICE
    # -----------------------------------------------------

    path(
        "",
        DeviceListCreateView.as_view(),
        name="device-list-create"
    ),

    path(
        "onboard/",
        QROnboardView.as_view(),
        name="device-onboard"
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

    # -----------------------------------------------------
    # DASHBOARD API
    # -----------------------------------------------------

    path(
        "<str:plant_id>/save-touch/",
        SaveTouchView.as_view(),
        name="save-touch"
    ),

    path(
        "<str:plant_id>/save-reminders/",
        SaveRemindersView.as_view(),
        name="save-reminders"
    ),

    path(
        "<str:plant_id>/save-config/",
        SaveConfigView.as_view(),
        name="save-config"
    ),

    path(
        "<str:plant_id>/power-toggle/",
        PowerToggleView.as_view(),
        name="power-toggle"
    ),

    path(
        "<str:plant_id>/restart/",
        RestartView.as_view(),
        name="restart"
    ),

    # -----------------------------------------------------
    # AI
    # -----------------------------------------------------

    path(
        "<str:plant_id>/ai-chat/",
        DeviceAIChatView.as_view(),
        name="device-ai-chat"
    ),

    path(
        "<str:plant_id>/ai-status/",
        DeviceAIStatusView.as_view(),
        name="device-ai-status"
    ),

    # -----------------------------------------------------
    # DASHBOARD
    # -----------------------------------------------------

    path(
        "<str:plant_id>/dashboard/",
        plant_dashboard_view,
        name="plant_dashboard"
    ),
]

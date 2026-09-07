from django.contrib import admin

from .models import Device, DeviceConfig


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):

    list_display = (
        "plant_id",
        "device_name",
        "user",
        "is_active",
        "last_seen",
        "created_at",
    )

    search_fields = (
        "plant_id",
        "device_name",
        "user__email",
    )

    list_filter = (
        "is_active",
        "created_at",
    )

    readonly_fields = (
        "qr_code_token",
        "last_seen",
        "created_at",
    )


@admin.register(DeviceConfig)
class DeviceConfigAdmin(admin.ModelAdmin):

    list_display = (
        "device",
        "webhook_url",
        "api_endpoint",
        "updated_at",
    )

    readonly_fields = (
        "updated_at",
    )
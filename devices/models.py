import secrets

from django.conf import settings
from django.db import models


def generate_qr_token():
    return secrets.token_urlsafe(32)


class Device(models.Model):

    id = models.BigAutoField(primary_key=True)

    plant_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="devices"
    )

    device_name = models.CharField(
        max_length=150
    )

    qr_code_token = models.CharField(
        max_length=100,
        unique=True,
        default=generate_qr_token,
        editable=False
    )

    is_active = models.BooleanField(
        default=False
    )

    last_seen = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.device_name} ({self.plant_id})"


class DeviceConfig(models.Model):

    id = models.BigAutoField(primary_key=True)

    device = models.OneToOneField(
        Device,
        on_delete=models.CASCADE,
        related_name="config"
    )

    webhook_url = models.URLField(
        blank=True,
        default=""
    )

    api_endpoint = models.URLField(
        blank=True,
        default=""
    )

    custom_settings = models.JSONField(
        default=dict,
        blank=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"Config: {self.device.plant_id}"
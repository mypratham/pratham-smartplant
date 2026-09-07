from rest_framework import serializers

from .models import Device, DeviceConfig


# =========================================================
# DEVICE CONFIG SERIALIZER
# =========================================================

class DeviceConfigSerializer(serializers.ModelSerializer):

    class Meta:
        model = DeviceConfig

        fields = [
            "id",
            "webhook_url",
            "api_endpoint",
            "custom_settings",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "updated_at",
        ]


# =========================================================
# DEVICE SERIALIZER
# =========================================================

class DeviceSerializer(serializers.ModelSerializer):

    config = DeviceConfigSerializer(
        read_only=True
    )

    class Meta:
        model = Device

        fields = [
            "id",
            "plant_id",
            "user",
            "device_name",
            "qr_code_token",
            "is_active",
            "last_seen",
            "created_at",
            "config",
        ]

        read_only_fields = [
            "id",
            "qr_code_token",
            "is_active",
            "last_seen",
            "created_at",
        ]

    def create(self, validated_data):

        device = Device.objects.create(
            **validated_data
        )

        DeviceConfig.objects.get_or_create(
            device=device
        )

        return device
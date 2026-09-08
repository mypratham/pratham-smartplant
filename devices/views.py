
import asyncio
import json
import logging
import os

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_1

from .models import Device, DeviceConfig
from .serializers import DeviceSerializer, DeviceConfigSerializer


logger = logging.getLogger(__name__)


# =========================================================
# CONFIG
# =========================================================

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883

AI_REQUEST_TOPIC = "pratham/plant01/ai/request"


# =========================================================
# PERMISSION
# =========================================================

def can_manage(user, device):
    return user.is_staff or device.user_id == user.id


# =========================================================
# MQTT PUBLISH
# =========================================================

async def mqtt_publish(topic, payload):

    client = MQTTClient()

    try:
        await client.connect(
            "mqtt://" + MQTT_HOST + ":" + str(MQTT_PORT)
        )

        if isinstance(payload, dict):
            payload = json.dumps(payload)

        await client.publish(
            topic,
            payload.encode("utf-8"),
            QOS_1
        )

        return True

    except Exception as e:
        logger.exception("[MQTT] Error: %s", e)
        return False

    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def publish_mqtt(topic, payload):

    try:
        return asyncio.run(
            mqtt_publish(topic, payload)
        )
    except Exception as e:
        logger.exception("[MQTT] Run error: %s", e)
        return False


# =========================================================
# AI MQTT
# =========================================================

async def publish_ai_request_mqtt(plant_id, message):

    return await mqtt_publish(
        AI_REQUEST_TOPIC,
        {
            "type": "ai_request",
            "plant_id": plant_id,
            "message": message,
            "source": "django",
            "timestamp": int(
                timezone.now().timestamp()
            )
        }
    )


# =========================================================
# DEVICE LIST + CREATE
# =========================================================

class DeviceListCreateView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        if request.user.is_staff:
            devices = Device.objects.all()
        else:
            devices = Device.objects.filter(
                user=request.user
            )

        devices = devices.order_by("-created_at")

        return Response(
            DeviceSerializer(
                devices,
                many=True
            ).data
        )

    def post(self, request):

        data = request.data.copy()

        if not request.user.is_staff:
            data["user"] = request.user.id

        serializer = DeviceSerializer(
            data=data
        )

        serializer.is_valid(
            raise_exception=True
        )

        device = serializer.save()

        DeviceConfig.objects.get_or_create(
            device=device
        )

        return Response(
            DeviceSerializer(device).data,
            status=status.HTTP_201_CREATED
        )


# =========================================================
# DEVICE DETAIL
# =========================================================

class DeviceDetailView(APIView):

    permission_classes = [IsAuthenticated]

    def get_object(self, plant_id):

        return Device.objects.filter(
            plant_id=plant_id
        ).first()

    def get(self, request, plant_id):

        device = self.get_object(plant_id)

        if not device:
            return Response(
                {"detail": "Device not found."},
                status=404
            )

        if not can_manage(request.user, device):
            return Response(
                {"detail": "Forbidden."},
                status=403
            )

        return Response(
            DeviceSerializer(device).data
        )

    def put(self, request, plant_id):

        device = self.get_object(plant_id)

        if not device:
            return Response(
                {"detail": "Device not found."},
                status=404
            )

        if not can_manage(request.user, device):
            return Response(
                {"detail": "Forbidden."},
                status=403
            )

        data = request.data.copy()

        if not request.user.is_staff:
            data["user"] = request.user.id

        serializer = DeviceSerializer(
            device,
            data=data,
            partial=True
        )

        serializer.is_valid(
            raise_exception=True
        )

        device = serializer.save()

        return Response(
            DeviceSerializer(device).data
        )

    def delete(self, request, plant_id):

        device = self.get_object(plant_id)

        if not device:
            return Response(
                {"detail": "Device not found."},
                status=404
            )

        if not can_manage(request.user, device):
            return Response(
                {"detail": "Forbidden."},
                status=403
            )

        device.delete()

        return Response(
            status=status.HTTP_204_NO_CONTENT
        )


# =========================================================
# HEARTBEAT
# =========================================================

class DeviceHeartbeatView(APIView):

    permission_classes = [AllowAny]

    def post(self, request, plant_id):

        device = Device.objects.filter(
            plant_id=plant_id
        ).first()

        if not device:
            return Response(
                {
                    "success": False,
                    "message": "Unknown device."
                },
                status=404
            )

        supplied_token = (
            request.data.get("device_token")
            or request.headers.get("X-Device-Token")
        )

        if supplied_token != device.qr_code_token:
            return Response(
                {
                    "success": False,
                    "message": "Invalid device token."
                },
                status=401
            )

        device.is_active = True
        device.last_seen = timezone.now()

        device.save(
            update_fields=[
                "is_active",
                "last_seen"
            ]
        )

        config, _ = DeviceConfig.objects.get_or_create(
            device=device
        )

        return Response(
            {
                "success": True,
                "plant_id": device.plant_id,
                "device_name": device.device_name,
                "is_active": device.is_active,
                "last_seen": device.last_seen,
                "config": DeviceConfigSerializer(config).data
            }
        )


# =========================================================
# STATUS
# =========================================================

class DeviceStatusView(APIView):

    permission_classes = [AllowAny]

    def get(self, request, plant_id):

        device = Device.objects.filter(
            plant_id=plant_id
        ).first()

        if not device:
            return Response(
                {
                    "success": False,
                    "detail": "Device not found."
                },
                status=404
            )

        return Response(
            {
                "success": True,
                "plant_id": device.plant_id,
                "device_name": device.device_name,
                "is_active": device.is_active,
                "last_seen": device.last_seen
            }
        )


# =========================================================
# CONFIG
# =========================================================

class DeviceConfigView(APIView):

    permission_classes = [AllowAny]

    def get_device(self, plant_id):

        device = Device.objects.filter(
            plant_id=plant_id
        ).first()

        if not device:
            return None

        return device

    def get(self, request, plant_id):

        device = self.get_device(plant_id)

        if not device:
            return Response(
                {
                    "success": False,
                    "detail": "Device not found."
                },
                status=404
            )

        config, _ = DeviceConfig.objects.get_or_create(
            device=device
        )

        return Response(
            {
                "success": True,
                **DeviceConfigSerializer(config).data
            }
        )

    def put(self, request, plant_id):

        device = self.get_device(plant_id)

        if not device:
            return Response(
                {
                    "success": False,
                    "detail": "Device not found."
                },
                status=404
            )

        config, _ = DeviceConfig.objects.get_or_create(
            device=device
        )

        serializer = DeviceConfigSerializer(
            config,
            data=request.data,
            partial=True
        )

        serializer.is_valid(
            raise_exception=True
        )

        config = serializer.save()

        return Response(
            {
                "success": True,
                **DeviceConfigSerializer(config).data
            }
        )


# =========================================================
# AI CHAT
# =========================================================

class DeviceAIChatView(APIView):

    permission_classes = [AllowAny]

    def post(self, request, plant_id):

        try:

            device = Device.objects.filter(
                plant_id=plant_id
            ).first()

            if not device:
                return Response(
                    {
                        "success": False,
                        "reply": "Device not found."
                    },
                    status=404
                )

            device_token = (
                request.headers.get("X-Device-Token")
                or request.data.get("device_token")
            )

            if device_token != device.qr_code_token:
                return Response(
                    {
                        "success": False,
                        "reply": "Invalid device token."
                    },
                    status=401
                )

            message = str(
                request.data.get(
                    "message",
                    request.data.get(
                        "user_message",
                        ""
                    )
                )
            ).strip()

            if not message:
                return Response(
                    {
                        "success": False,
                        "reply": "Message is empty."
                    },
                    status=400
                )

            message = message[:500]

            mqtt_ok = asyncio.run(
                publish_ai_request_mqtt(
                    plant_id,
                    message
                )
            )

            if not mqtt_ok:
                return Response(
                    {
                        "success": False,
                        "reply": "AI service unavailable.",
                        "pending": False
                    },
                    status=503
                )

            # Pending state
            cache.set(
                "ai_status_" + plant_id,
                {
                    "pending": True,
                    "reply": "Message received. Plant AI is thinking..."
                },
                timeout=300
            )

            return Response(
                {
                    "success": True,
                    "reply": "Message received. Plant AI is thinking...",
                    "plant_id": plant_id,
                    "pending": True
                },
                status=202
            )

        except Exception as e:

            logger.exception(
                "[AI CHAT] %s",
                e
            )

            return Response(
                {
                    "success": False,
                    "reply": "AI service error.",
                    "pending": False
                },
                status=500
            )


# =========================================================
# AI STATUS
# =========================================================

class DeviceAIStatusView(APIView):

    permission_classes = [AllowAny]

    def get(self, request, plant_id):

        result = cache.get(
            "ai_status_" + plant_id
        )

        if not result:
            return Response(
                {
                    "success": True,
                    "pending": False,
                    "reply": ""
                }
            )

        return Response(
            {
                "success": True,
                **result
            }
        )

    def post(self, request, plant_id):

        data = request.data

        reply = data.get(
            "reply",
            ""
        )

        pending = data.get(
            "pending",
            False
        )

        cache.set(
            "ai_status_" + plant_id,
            {
                "pending": pending,
                "reply": reply
            },
            timeout=300
        )

        return Response(
            {
                "success": True
            }
        )


# =========================================================
# SAVE TOUCH
# =========================================================

class SaveTouchView(APIView):

    permission_classes = [AllowAny]

    def post(self, request, plant_id):

        device = Device.objects.filter(
            plant_id=plant_id
        ).first()

        if not device:
            return Response(
                {
                    "success": False,
                    "message": "Device not found."
                },
                status=404
            )

        config, _ = DeviceConfig.objects.get_or_create(
            device=device
        )

        settings_data = config.custom_settings or {}

        touch_data = request.data

        settings_data["touch"] = touch_data

        config.custom_settings = settings_data
        config.save()

        publish_mqtt(
            "pratham/" + plant_id + "/command",
            {
                "type": "touch",
                "plant_id": plant_id,
                "data": touch_data
            }
        )

        return Response(
            {
                "success": True,
                "message": "Touch settings saved.",
                "data": touch_data
            }
        )


# =========================================================
# SAVE REMINDERS
# =========================================================

class SaveRemindersView(APIView):

    permission_classes = [AllowAny]

    def post(self, request, plant_id):

        device = Device.objects.filter(
            plant_id=plant_id
        ).first()

        if not device:
            return Response(
                {
                    "success": False,
                    "message": "Device not found."
                },
                status=404
            )

        config, _ = DeviceConfig.objects.get_or_create(
            device=device
        )

        settings_data = config.custom_settings or {}

        reminders = request.data

        settings_data["reminders"] = reminders

        config.custom_settings = settings_data
        config.save()

        publish_mqtt(
            "pratham/" + plant_id + "/command",
            {
                "type": "reminders",
                "plant_id": plant_id,
                "data": reminders
            }
        )

        return Response(
            {
                "success": True,
                "message": "Reminders saved.",
                "data": reminders
            }
        )


# =========================================================
# SAVE CONFIG
# =========================================================

class SaveConfigView(APIView):

    permission_classes = [AllowAny]

    def post(self, request, plant_id):

        device = Device.objects.filter(
            plant_id=plant_id
        ).first()

        if not device:
            return Response(
                {
                    "success": False,
                    "message": "Device not found."
                },
                status=404
            )

        config, _ = DeviceConfig.objects.get_or_create(
            device=device
        )

        data = request.data.copy()

        custom = config.custom_settings or {}

        custom.update(
            data.get(
                "custom_settings",
                {}
            )
        )

        config.webhook_url = data.get(
            "webhook_url",
            config.webhook_url
        )

        config.api_endpoint = data.get(
            "api_endpoint",
            config.api_endpoint
        )

        config.custom_settings = custom

        config.save()

        publish_mqtt(
            "pratham/" + plant_id + "/command",
            {
                "type": "config",
                "plant_id": plant_id,
                "data": data
            }
        )

        return Response(
            {
                "success": True,
                "message": "Configuration saved.",
                "config": DeviceConfigSerializer(config).data
            }
        )


# =========================================================
# POWER TOGGLE
# =========================================================

class PowerToggleView(APIView):

    permission_classes = [AllowAny]

    def post(self, request, plant_id):

        device = Device.objects.filter(
            plant_id=plant_id
        ).first()

        if not device:
            return Response(
                {
                    "success": False,
                    "message": "Device not found."
                },
                status=404
            )

        state = request.data.get(
            "power",
            request.data.get(
                "state",
                None
            )
        )

        if isinstance(state, str):
            state = state.lower() in [
                "true",
                "1",
                "on"
            ]

        config, _ = DeviceConfig.objects.get_or_create(
            device=device
        )

        custom = config.custom_settings or {}

        custom["power"] = bool(state)

        config.custom_settings = custom
        config.save()

        mqtt_ok = publish_mqtt(
            "pratham/" + plant_id + "/command",
            {
                "type": "power",
                "plant_id": plant_id,
                "state": bool(state)
            }
        )

        return Response(
            {
                "success": True,
                "power": bool(state),
                "mqtt": mqtt_ok
            }
        )


# =========================================================
# RESTART
# =========================================================

class RestartView(APIView):

    permission_classes = [AllowAny]

    def post(self, request, plant_id):

        device = Device.objects.filter(
            plant_id=plant_id
        ).first()

        if not device:
            return Response(
                {
                    "success": False,
                    "message": "Device not found."
                },
                status=404
            )

        mqtt_ok = publish_mqtt(
            "pratham/" + plant_id + "/command",
            {
                "type": "restart",
                "plant_id": plant_id
            }
        )

        return Response(
            {
                "success": mqtt_ok,
                "message":
                    "Restart command sent."
                    if mqtt_ok
                    else
                    "MQTT unavailable."
            }
        )


# =========================================================
# QR ONBOARDING
# =========================================================

class QROnboardView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):

        qr_token = request.data.get(
            "qr_code_token"
        )

        if not qr_token:
            return Response(
                {
                    "success": False,
                    "message":
                        "qr_code_token is required."
                },
                status=400
            )

        device = Device.objects.filter(
            qr_code_token=qr_token
        ).first()

        if not device:
            return Response(
                {
                    "success": False,
                    "message":
                        "Invalid QR token."
                },
                status=404
            )

        return Response(
            {
                "success": True,
                "plant_id": device.plant_id,
                "device_name": device.device_name,
                "device_token":
                    device.qr_code_token,
                "message":
                    "Device token accepted."
            }
        )


# =========================================================
# DASHBOARD
# =========================================================

@csrf_exempt
def plant_dashboard_view(request, plant_id):

    html_path = os.path.join(
        settings.BASE_DIR,
        "templates",
        "plant_dashboard.html"
    )

    try:

        with open(
            html_path,
            "r",
            encoding="utf-8"
        ) as f:

            content = f.read()

        content = content.replace(
            "{{ plant_id }}",
            plant_id
        )

        return HttpResponse(
            content
        )

    except Exception as e:

        return HttpResponse(
            f"Template not found: {e}",
            status=404
        )

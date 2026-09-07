import asyncio
import json
import logging

from django.utils import timezone
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
# PERMISSION HELPER
# =========================================================

def can_manage(user, device):
    """
    Staff users can manage every device.
    Normal users can manage only their own devices.
    """
    return user.is_staff or device.user_id == user.id


# =========================================================
# DJANGO -> AMQTT AI REQUEST
# =========================================================

AI_REQUEST_TOPIC = "pratham/plant01/ai/request"

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883


async def publish_ai_request_mqtt(
    plant_id,
    message
):
    """
    Django -> AMQTT -> ai_brain.py

    Django sirf AI request MQTT topic par publish karega.
    ai_brain.py request receive karke Gemini call karega.
    """

    client = MQTTClient()

    try:

        logger.info(
            "[AI MQTT] Connecting to AMQTT..."
        )

        await client.connect(
            "mqtt://"
            + MQTT_HOST
            + ":"
            + str(MQTT_PORT)
        )

        payload = {
            "type": "ai_request",
            "plant_id": plant_id,
            "message": message,
            "source": "django",
            "timestamp": int(
                timezone.now().timestamp()
            )
        }

        payload_string = json.dumps(
            payload,
            ensure_ascii=False
        )

        logger.info(
            "[AI MQTT] Publishing: %s",
            payload_string
        )

        await client.publish(
            AI_REQUEST_TOPIC,
            payload_string.encode("utf-8"),
            QOS_1
        )

        logger.info(
            "[AI MQTT] AI request published successfully."
        )

        return True

    except Exception as e:

        logger.exception(
            "[AI MQTT] Publish error: %s",
            e
        )

        return False

    finally:

        try:

            await client.disconnect()

        except Exception:

            pass

# =========================================================
# DEVICE LIST + CREATE
# =========================================================

class DeviceListCreateView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):

        if request.user.is_staff:
            devices = Device.objects.all()
        else:
            devices = Device.objects.filter(user=request.user)

        devices = devices.order_by("-created_at")

        serializer = DeviceSerializer(
            devices,
            many=True
        )

        return Response(serializer.data)

    def post(self, request):

        data = request.data.copy()

        # Normal user can create device only for himself
        if not request.user.is_staff:
            data["user"] = request.user.id

        serializer = DeviceSerializer(data=data)

        serializer.is_valid(raise_exception=True)

        device = serializer.save()

        # Automatically create configuration
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

    # -----------------------------------------------------
    # GET
    # -----------------------------------------------------

    def get(self, request, plant_id):

        device = self.get_object(plant_id)

        if not device:

            return Response(
                {
                    "detail": "Device not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        if not can_manage(request.user, device):

            return Response(
                {
                    "detail": "Forbidden."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        return Response(
            DeviceSerializer(device).data
        )

    # -----------------------------------------------------
    # PUT
    # -----------------------------------------------------

    def put(self, request, plant_id):

        device = self.get_object(plant_id)

        if not device:

            return Response(
                {
                    "detail": "Device not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        if not can_manage(request.user, device):

            return Response(
                {
                    "detail": "Forbidden."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        data = request.data.copy()

        # Normal user cannot transfer device to another user
        if not request.user.is_staff:
            data["user"] = request.user.id

        serializer = DeviceSerializer(
            device,
            data=data,
            partial=True
        )

        serializer.is_valid(raise_exception=True)

        device = serializer.save()

        return Response(
            DeviceSerializer(device).data
        )

    # -----------------------------------------------------
    # DELETE
    # -----------------------------------------------------

    def delete(self, request, plant_id):

        device = self.get_object(plant_id)

        if not device:

            return Response(
                {
                    "detail": "Device not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        if not can_manage(request.user, device):

            return Response(
                {
                    "detail": "Forbidden."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        device.delete()

        return Response(
            status=status.HTTP_204_NO_CONTENT
        )


# =========================================================
# DEVICE HEARTBEAT
# ESP32 -> Django
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
                status=status.HTTP_404_NOT_FOUND
            )

        # Device token can come from JSON
        # or HTTP header
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
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Update device status
        device.is_active = True
        device.last_seen = timezone.now()

        device.save(
            update_fields=[
                "is_active",
                "last_seen"
            ]
        )

        # Ensure config exists
        config, created = DeviceConfig.objects.get_or_create(
            device=device
        )

        return Response(
            {
                "success": True,
                "plant_id": device.plant_id,
                "device_name": device.device_name,
                "is_active": device.is_active,
                "last_seen": device.last_seen,
                "config": DeviceConfigSerializer(config).data,
            }
        )


# =========================================================
# DEVICE STATUS
# =========================================================

class DeviceStatusView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, plant_id):

        device = Device.objects.filter(
            plant_id=plant_id
        ).first()

        if not device:

            return Response(
                {
                    "detail": "Device not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        if not can_manage(request.user, device):

            return Response(
                {
                    "detail": "Forbidden."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        return Response(
            {
                "plant_id": device.plant_id,
                "device_name": device.device_name,
                "is_active": device.is_active,
                "last_seen": device.last_seen,
            }
        )

# =========================================================
# DEVICE AI CHAT
# ESP32 -> Django -> AMQTT/GEMINI -> Django -> ESP32
# =========================================================

# =========================================================
# DEVICE AI CHAT
# =========================================================

class DeviceAIChatView(APIView):

    permission_classes = [AllowAny]

    def post(
        self,
        request,
        plant_id
    ):

        try:

            # =================================================
            # DEVICE
            # =================================================

            try:

                device = Device.objects.get(
                    plant_id=plant_id
                )

            except Device.DoesNotExist:

                return Response(
                    {
                        "success": False,
                        "reply": "Device not found."
                    },
                    status=status.HTTP_404_NOT_FOUND
                )


            # =================================================
            # DEVICE TOKEN
            # =================================================

            device_token = (
                request.headers.get(
                    "X-Device-Token"
                )
                or request.data.get(
                    "device_token"
                )
            )


            # =================================================
            # TOKEN CHECK
            # =================================================

            if not device_token:

                return Response(
                    {
                        "success": False,
                        "reply": "Device token required."
                    },
                    status=status.HTTP_401_UNAUTHORIZED
                )


            # =================================================
            # TOKEN VALIDATION
            # =================================================

            if device_token != device.qr_code_token:

                return Response(
                    {
                        "success": False,
                        "reply": "Invalid device token."
                    },
                    status=status.HTTP_401_UNAUTHORIZED
                )


            # =================================================
            # ACTIVE CHECK
            # =================================================

            if hasattr(device, "is_active"):

                if not device.is_active:

                    return Response(
                        {
                            "success": False,
                            "reply": "Device is inactive."
                        },
                        status=status.HTTP_403_FORBIDDEN
                    )


            # =================================================
            # USER MESSAGE
            # =================================================

            user_message = str(

                request.data.get(
                    "message",
                    ""
                )

            ).strip()


            # =================================================
            # ALTERNATIVE FIELD
            # =================================================

            if not user_message:

                user_message = str(

                    request.data.get(
                        "user_message",
                        ""
                    )

                ).strip()


            # =================================================
            # EMPTY MESSAGE
            # =================================================

            if not user_message:

                return Response(
                    {
                        "success": False,
                        "reply": "Message is empty."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )


            # =================================================
            # LIMIT
            # =================================================

            if len(user_message) > 500:

                user_message = user_message[:500]


            logger.info(
                "[AI CHAT] Plant=%s Message=%s",
                plant_id,
                user_message
            )


            # =================================================
            # DJANGO -> MQTT -> AI BRAIN
            # =================================================

            mqtt_ok = asyncio.run(

                publish_ai_request_mqtt(

                    plant_id=plant_id,

                    message=user_message

                )

            )


            # =================================================
            # MQTT FAILED
            # =================================================

            if not mqtt_ok:

                logger.error(
                    "[AI CHAT] MQTT publish failed."
                )

                return Response(
                    {
                        "success": False,
                        "reply": "AI service unavailable.",
                        "pending": False
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )


            # =================================================
            # SUCCESS
            # =================================================

            return Response(

                {
                    "success": True,

                    "reply":
                        "Message received. Plant AI is thinking...",

                    "plant_id":
                        plant_id,

                    "pending":
                        True

                },

                status=status.HTTP_202_ACCEPTED

            )


        # =====================================================
        # ERROR
        # =====================================================

        except Exception as e:

            logger.exception(
                "[AI CHAT] Error: %s",
                e
            )

            return Response(
                {
                    "success": False,
                    "reply": "AI service error.",
                    "pending": False
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# =========================================================
# DEVICE CONFIG
# =========================================================

class DeviceConfigView(APIView):

    permission_classes = [IsAuthenticated]

    def get_device(self, request, plant_id):

        device = Device.objects.filter(
            plant_id=plant_id
        ).first()

        if not device:

            return None, Response(
                {
                    "detail": "Device not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        if not can_manage(request.user, device):

            return None, Response(
                {
                    "detail": "Forbidden."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        return device, None

    # -----------------------------------------------------
    # GET CONFIG
    # -----------------------------------------------------

    def get(self, request, plant_id):

        device, error = self.get_device(
            request,
            plant_id
        )

        if error:
            return error

        config, created = DeviceConfig.objects.get_or_create(
            device=device
        )

        return Response(
            DeviceConfigSerializer(config).data
        )

    # -----------------------------------------------------
    # UPDATE CONFIG
    # -----------------------------------------------------

    def put(self, request, plant_id):

        device, error = self.get_device(
            request,
            plant_id
        )

        if error:
            return error

        config, created = DeviceConfig.objects.get_or_create(
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
            DeviceConfigSerializer(config).data
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
                    "message": "qr_code_token is required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        device = Device.objects.filter(
            qr_code_token=qr_token
        ).first()

        if not device:

            return Response(
                {
                    "success": False,
                    "message": "Invalid QR token."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(
            {
                "success": True,
                "plant_id": device.plant_id,
                "device_name": device.device_name,
                "message": "Device token accepted."
            }
        )
import asyncio
import json
import logging
import os
import time

import requests

from amqtt.broker import Broker
from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_1


# =========================================================
# PRATHAM PLANT AI BRAIN
# AMQTT + DJANGO + GEMINI REST API + ESP32
# =========================================================


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] :: %(levelname)s :: %(message)s"
)

logger = logging.getLogger("PRATHAM-AI")


# =========================================================
# GEMINI CONFIGURATION
# =========================================================

GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY",
    "AQ.Ab8RN6IZ4NxpBe2wkqgKPV0YHWBqRlQphcy5RnLtCUYZEz254w"
)

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-1.5-flash"
)

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/"
    "v1beta/models/"
    + GEMINI_MODEL
    + ":generateContent"
)


# =========================================================
# LIVE DJANGO CONFIGURATION
# =========================================================

DJANGO_URL = os.environ.get(
    "DJANGO_URL",
    "https://smartplant.agrowillbiotech.com"
)

PLANT_ID = os.environ.get(
    "PLANT_ID",
    "pratham_plant_01"
)

DEVICE_TOKEN = os.environ.get(
    "DEVICE_TOKEN",
    "Pa4njodWH_pM7zGnswVhq-R6KRzLQClyMGB0aP2xhpw"
)


# =========================================================
# MQTT CONFIGURATION
# =========================================================

MQTT_HOST = os.environ.get(
    "MQTT_HOST",
    "0.0.0.0"
)

MQTT_PORT = int(
    os.environ.get(
        "MQTT_PORT",
        "1883"
    )
)

MQTT_CLIENT_HOST = os.environ.get(
    "MQTT_CLIENT_HOST",
    "127.0.0.1"
)

MQTT_CLIENT_PORT = int(
    os.environ.get(
        "MQTT_CLIENT_PORT",
        "1883"
    )
)


# =========================================================
# MQTT TOPICS
# =========================================================

MQTT_BASE = f"pratham/{PLANT_ID}"

STATUS_TOPIC = (
    f"{MQTT_BASE}/status"
)

COMMAND_TOPIC = (
    f"{MQTT_BASE}/command"
)

AI_REQUEST_TOPIC = (
    f"{MQTT_BASE}/ai/request"
)


# =========================================================
# AMQTT BROKER CONFIGURATION
# =========================================================

BROKER_CONFIG = {
    "listeners": {
        "default": {
            "type": "tcp",
            "bind": MQTT_HOST + ":" + str(MQTT_PORT)
        }
    },
    "sys_interval": 10,
    "auth": {
        "allow-anonymous": True
    }
}


# =========================================================
# GLOBALS & CONSTANTS
# =========================================================

broker = None
mqtt_client = None

MAX_AI_WORDS = 10
MAX_OLED_LENGTH = 18
AI_COOLDOWN = 3
last_ai_request = 0


# =========================================================
# DJANGO LIVE ENDPOINTS
# =========================================================

DJANGO_HEARTBEAT_URL = (
    DJANGO_URL.rstrip("/")
    + "/api/devices/"
    + PLANT_ID
    + "/heartbeat/"
)

DJANGO_AI_STATUS_URL = (
    DJANGO_URL.rstrip("/")
    + "/api/devices/"
    + PLANT_ID
    + "/ai-status/"
)


# =========================================================
# JSON HELPER
# =========================================================

def parse_json_message(payload):
    try:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="ignore")
        return json.loads(payload)
    except Exception as e:
        logger.warning("Invalid JSON message: %s", e)
        return {"message": str(payload)}


# =========================================================
# OLED TEXT CLEANER
# =========================================================

def clean_ai_response(text):
    if not text:
        return "Hello Plant!"

    text = str(text)
    text = text.replace("\n", " ").replace("\r", " ").replace('"', "").strip()
    words = text.split()

    if len(words) > MAX_AI_WORDS:
        text = " ".join(words[:MAX_AI_WORDS])

    if len(text) > MAX_OLED_LENGTH:
        text = text[:MAX_OLED_LENGTH - 2] + ".."

    return text


# =========================================================
# GEMINI REST API
# =========================================================

def call_gemini_api(message_text, plant_data=None):
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is not configured.")
        return "AI Offline"

    if plant_data is None:
        plant_data = {}

    try:
        sensor_json = json.dumps(plant_data, ensure_ascii=False)
    except Exception:
        sensor_json = "{}"

    prompt = f"""
You are Pratham Plant AI.
You are the friendly AI companion inside a smart IoT plant device created by Pratham Gurukul.

Plant ID:
{PLANT_ID}

Incoming event:
{message_text}

Device sensor data:
{sensor_json}

Give a very short response suitable for a tiny 128x64 OLED display.

Rules:
- Maximum 10 words.
- Preferably keep it under 18 characters.
- Simple English.
- Friendly & slightly witty.
- No markdown, emojis, or explanations.
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    # API Key URL me attach karein
    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"

    headers = {
        "Content-Type": "application/json"
    }

    try:
        logger.info("Sending request to Gemini...")
        # URL variable use karein (GEMINI_API_URL nahi)
        response = requests.post(url, headers=headers, json=payload, timeout=30)

        logger.info("Gemini HTTP: %s", response.status_code)

        if response.status_code != 200:
            logger.error("Gemini HTTP error: %s", response.text[:1000])
            return "AI Error"

        data = response.json()
        candidates = data.get("candidates", [])

        if not candidates:
            return "AI Unavailable"

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return "AI Unavailable"

        ai_reply = "".join([str(p.get("text", "")) for p in parts if isinstance(p, dict)]).strip()

        if not ai_reply:
            return "AI Unavailable"

        ai_reply = clean_ai_response(ai_reply)
        logger.info("Gemini Reply: %s", ai_reply)
        return ai_reply

    except requests.exceptions.Timeout:
        logger.error("Gemini request timeout.")
        return "AI Timeout"
    except requests.exceptions.ConnectionError as e:
        logger.error("Gemini connection error: %s", e)
        return "AI Offline"
    except Exception as e:
        logger.exception("Gemini API Error: %s", e)
        return "AI Error"

# =========================================================
# ASYNC GEMINI WRAPPER
# =========================================================

async def ai_brain_process(message_text, plant_data=None):
    global last_ai_request
    now = time.time()

    if now - last_ai_request < AI_COOLDOWN:
        logger.info("Gemini cooldown active.")
        return None

    last_ai_request = now

    try:
        result = await asyncio.to_thread(call_gemini_api, message_text, plant_data)
        return result
    except Exception as e:
        logger.exception("AI wrapper error: %s", e)
        return "AI Error"


# =========================================================
# EXPRESSION DETECTOR
# =========================================================

def detect_expression(text):
    if not text:
        return "happy"

    t = text.lower()
    if any(word in t for word in ["water", "thirsty", "hot", "heat", "warning", "dry", "danger"]):
        return "surprised"
    if any(word in t for word in ["great", "good", "healthy", "perfect", "happy", "awesome"]):
        return "excited"
    if any(word in t for word in ["sad", "problem", "bad"]):
        return "sad"

    return "happy"


# =========================================================
# SEND COMMAND TO ESP32
# =========================================================

async def send_command_to_esp32(text, expression="happy"):
    global mqtt_client

    if mqtt_client is None:
        logger.error("MQTT client not available.")
        return False

    try:
        payload = {
            "type": "ai",
            "plant_id": PLANT_ID,
            "text": clean_ai_response(text),
            "expr": expression,
            "timestamp": int(time.time())
        }

        payload_string = json.dumps(payload, ensure_ascii=False)
        logger.info("Publishing AI command: %s", payload_string)

        await mqtt_client.publish(COMMAND_TOPIC, payload_string.encode("utf-8"), QOS_1)
        logger.info("AI command sent to ESP32.")
        return True

    except Exception as e:
        logger.exception("MQTT publish error: %s", e)
        return False


# =========================================================
# SEND AI RESULT TO DJANGO (LIVE SERVER)
# =========================================================

def send_ai_result_to_django(reply, pending=False):
    if not DEVICE_TOKEN:
        logger.warning("DEVICE_TOKEN not configured.")
        return False

    try:
        headers = {
            "Content-Type": "application/json",
            "X-Device-Token": DEVICE_TOKEN
        }

        payload = {
            "reply": clean_ai_response(reply),
            "pending": pending,
            "plant_id": PLANT_ID,
            "timestamp": int(time.time())
        }

        logger.info("Sending AI result to Django Live API...")
        response = requests.post(DJANGO_AI_STATUS_URL, headers=headers, json=payload, timeout=10)

        logger.info("Django AI status HTTP: %s", response.status_code)
        return response.status_code == 200

    except Exception as e:
        logger.exception("Django AI status error: %s", e)
        return False


# =========================================================
# DJANGO HEARTBEAT (LIVE SERVER)
# =========================================================

def send_django_heartbeat():
    if not DEVICE_TOKEN:
        logger.warning("DEVICE_TOKEN not configured.")
        return False

    try:
        headers = {
            "Content-Type": "application/json",
            "X-Device-Token": DEVICE_TOKEN
        }

        payload = {
            "device_token": DEVICE_TOKEN
        }

        logger.info("Sending Heartbeat to Django Live API...")
        response = requests.post(DJANGO_HEARTBEAT_URL, headers=headers, json=payload, timeout=10)

        logger.info("Django Heartbeat HTTP: %s", response.status_code)
        return response.status_code == 200

    except Exception as e:
        logger.exception("Django heartbeat error: %s", e)
        return False


# =========================================================
# DJANGO HEARTBEAT LOOP
# =========================================================

async def django_heartbeat_loop():
    while True:
        try:
            await asyncio.to_thread(send_django_heartbeat)
        except Exception as e:
            logger.exception("Heartbeat loop error: %s", e)
        await asyncio.sleep(60)


# =========================================================
# PROCESS AI REQUEST FROM DJANGO
# =========================================================

async def process_ai_request(decoded_msg):
    logger.info("AI REQUEST RECEIVED: %s", decoded_msg)
    data = parse_json_message(decoded_msg)

    request_plant_id = str(data.get("plant_id", PLANT_ID))
    if request_plant_id != PLANT_ID:
        logger.warning("Ignoring AI request for plant: %s", request_plant_id)
        return

    user_message = str(data.get("message", "")).strip()
    if not user_message:
        logger.warning("Empty AI request received.")
        return

    ai_reply = await ai_brain_process(user_message, data)
    if not ai_reply:
        return

    expression = detect_expression(ai_reply)
    esp_ok = await send_command_to_esp32(ai_reply, expression)
    django_ok = await asyncio.to_thread(send_ai_result_to_django, ai_reply, False)

    logger.info("AI REQUEST COMPLETE | ESP32=%s | DJANGO=%s", esp_ok, django_ok)


# =========================================================
# PROCESS ESP32 STATUS EVENT
# =========================================================

async def process_esp32_status(decoded_msg):
    logger.info("ESP32 STATUS: %s", decoded_msg)
    data = parse_json_message(decoded_msg)

    message_plant_id = str(data.get("plant_id", PLANT_ID))
    if message_plant_id != PLANT_ID:
        return

    event = data.get("event", "")
    touch_pressed = data.get("touch_pressed", False)
    message_text = str(data.get("message", "")).strip()

    ai_trigger = touch_pressed or event in ["touch", "ask_ai"] or bool(message_text)

    if not ai_trigger:
        logger.info("ESP32 event does not require AI processing.")
        return

    ai_message = message_text or "The plant was touched. Greet the user."
    ai_reply = await ai_brain_process(ai_message, data)

    if not ai_reply:
        return

    expression = detect_expression(ai_reply)
    esp_ok = await send_command_to_esp32(ai_reply, expression)
    django_ok = await asyncio.to_thread(send_ai_result_to_django, ai_reply, False)

    logger.info("ESP32 AI COMPLETE | ESP32=%s | DJANGO=%s", esp_ok, django_ok)


# =========================================================
# PROCESS MQTT EVENT
# =========================================================

async def process_esp32_event(topic, decoded_msg):
    if topic == AI_REQUEST_TOPIC:
        await process_ai_request(decoded_msg)
    elif topic == STATUS_TOPIC:
        await process_esp32_status(decoded_msg)


# =========================================================
# AMQTT MESSAGE RECEIVER & CLIENT MANAGEMENT
# =========================================================

async def mqtt_receive_loop():
    global mqtt_client
    while True:
        try:
            message = await mqtt_client.deliver_message()
            packet = message.publish_packet
            topic = packet.variable_header.topic_name
            decoded_msg = packet.payload.data.decode("utf-8", errors="ignore")

            await process_esp32_event(topic, decoded_msg)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("MQTT receive error: %s", e)
            await asyncio.sleep(3)
            break

async def connect_mqtt_client():
    global mqtt_client
    mqtt_client = MQTTClient()

    try:
        await mqtt_client.connect(f"mqtt://{MQTT_CLIENT_HOST}:{MQTT_CLIENT_PORT}")
        await mqtt_client.subscribe([(STATUS_TOPIC, QOS_1), (AI_REQUEST_TOPIC, QOS_1)])
        logger.info("Subscribed to MQTT topics successfully.")
        return True
    except Exception as e:
        logger.exception("AMQTT connection error: %s", e)
        return False

async def start_broker():
    global broker
    broker = Broker(BROKER_CONFIG)
    await broker.start()
    logger.info("AMQTT Broker started on %s:%s", MQTT_HOST, MQTT_PORT)

async def broker_controller():
    await start_broker()
    asyncio.create_task(django_heartbeat_loop())

    while True:
        connected = await connect_mqtt_client()
        if not connected:
            await asyncio.sleep(5)
            continue

        try:
            await mqtt_receive_loop()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("MQTT loop error: %s", e)

        await asyncio.sleep(5)


# =========================================================
# MAIN EXECUTION
# =========================================================

def main():
    logger.info("Starting PRATHAM PLANT AI BRAIN - LIVE ENVIRONMENT")
    logger.info("Target Django Domain: %s", DJANGO_URL)

    try:
        asyncio.run(broker_controller())
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")
    except Exception as e:
        logger.exception("Fatal error: %s", e)

if __name__ == "__main__":
    main()
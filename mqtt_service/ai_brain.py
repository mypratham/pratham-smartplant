import asyncio
import json
import logging
import os
import time

import requests

from amqtt.broker import Broker
from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_1
from dotenv import load_dotenv

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

# IMPORTANT:
# Gemini API key environment variable se aayegi.
# Code me actual API key mat rakhein.

load_dotenv()

# Gemini API Key (.env file se fetch hogi)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY nahi mila! Kripya .env file check karein.")

GEMINI_MODEL = "gemini-3.6-flash"

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/"
    "v1beta/models/"
    + GEMINI_MODEL
    + ":generateContent"
)


# =========================================================
# DJANGO CONFIGURATION
# =========================================================

DJANGO_URL = os.environ.get(
    "DJANGO_URL",
    "http://127.0.0.1:8000"
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

MQTT_HOST = "0.0.0.0"

MQTT_PORT = 1883

MQTT_CLIENT_HOST = "127.0.0.1"

MQTT_CLIENT_PORT = 1883


# =========================================================
# MQTT TOPICS
# =========================================================

STATUS_TOPIC = "pratham/plant01/status"

COMMAND_TOPIC = "pratham/plant01/command"

AI_REQUEST_TOPIC = "pratham/plant01/ai/request"


# =========================================================
# AMQTT BROKER CONFIGURATION
# =========================================================

BROKER_CONFIG = {

    "listeners": {

        "default": {

            "type": "tcp",

            "bind": (
                MQTT_HOST
                + ":"
                + str(MQTT_PORT)
            )
        }
    },

    "sys_interval": 10,

    "auth": {

        "allow-anonymous": True
    }
}


# =========================================================
# GLOBALS
# =========================================================

broker = None

mqtt_client = None


# =========================================================
# AI SETTINGS
# =========================================================

MAX_AI_WORDS = 10

MAX_OLED_LENGTH = 18

AI_COOLDOWN = 3

last_ai_request = 0


# =========================================================
# DJANGO HEARTBEAT URL
# =========================================================

DJANGO_HEARTBEAT_URL = (
    DJANGO_URL.rstrip("/")
    + "/api/devices/"
    + PLANT_ID
    + "/heartbeat/"
)


# =========================================================
# JSON HELPER
# =========================================================

def parse_json_message(payload):

    try:

        if isinstance(payload, bytes):

            payload = payload.decode(
                "utf-8",
                errors="ignore"
            )

        return json.loads(payload)

    except Exception as e:

        logger.warning(
            "Invalid JSON message: %s",
            e
        )

        return {
            "message": str(payload)
        }


# =========================================================
# OLED TEXT CLEANER
# =========================================================

def clean_ai_response(text):

    if not text:

        return "Hello Plant!"

    text = str(text)

    text = text.replace(
        "\n",
        " "
    )

    text = text.replace(
        "\r",
        " "
    )

    text = text.replace(
        '"',
        ""
    )

    text = text.strip()

    words = text.split()

    if len(words) > MAX_AI_WORDS:

        text = " ".join(
            words[:MAX_AI_WORDS]
        )

    if len(text) > MAX_OLED_LENGTH:

        text = (
            text[
                :MAX_OLED_LENGTH - 2
            ]
            + ".."
        )

    return text


# =========================================================
# GEMINI REST API
# =========================================================

def call_gemini_api(
    message_text,
    plant_data=None
):

    # -----------------------------------------------------
    # API KEY CHECK
    # -----------------------------------------------------

    if not GEMINI_API_KEY:

        logger.error(
            "GEMINI_API_KEY is not configured."
        )

        return "AI Offline"


    # -----------------------------------------------------
    # PLANT DATA
    # -----------------------------------------------------

    if plant_data is None:

        plant_data = {}


    # -----------------------------------------------------
    # SAFE SENSOR DATA
    # -----------------------------------------------------

    try:

        sensor_json = json.dumps(
            plant_data,
            ensure_ascii=False
        )

    except Exception:

        sensor_json = "{}"


    # =====================================================
    # PROMPT
    # =====================================================

    prompt = f"""
You are Pratham Plant AI.

You are the friendly AI companion
inside a smart IoT plant device
created by Pratham Gurukul.

Plant ID:
{PLANT_ID}

Incoming event:
{message_text}

Device sensor data:
{sensor_json}

Give a very short response suitable
for a tiny 128x64 OLED display.

Rules:
- Maximum 10 words.
- Preferably keep it under 18 characters.
- Simple English.
- Friendly.
- Slightly witty.
- No markdown.
- No emojis.
- No explanations.
- If watering is needed, mention water.
- If temperature is high, mention heat.
- If humidity is low, mention humidity.
- If soil is dry, mention water.
- If everything is normal, say something positive.
"""


    # =====================================================
    # REQUEST URL
    # =====================================================

    url = GEMINI_API_URL


    # =====================================================
    # REQUEST PAYLOAD
    # =====================================================

    payload = {

        "contents": [

            {

                "parts": [

                    {

                        "text": prompt

                    }

                ]

            }

        ]

    }


    # =====================================================
    # HEADERS
    # =====================================================

    headers = {

        "Content-Type": "application/json",

        "x-goog-api-key": GEMINI_API_KEY

    }


    # =====================================================
    # GEMINI REQUEST
    # =====================================================

    try:

        logger.info(
            "Sending request to Gemini..."
        )

        response = requests.post(

            url,

            headers=headers,

            json=payload,

            timeout=30

        )


        logger.info(
            "Gemini HTTP: %s",
            response.status_code
        )


        # =================================================
        # HTTP ERROR
        # =================================================

        if response.status_code != 200:

            logger.error(
                "Gemini HTTP error: %s",
                response.text[:1000]
            )

            if response.status_code == 400:

                return "AI Bad Request"

            if response.status_code == 401:

                return "AI Auth Error"

            if response.status_code == 403:

                return "AI Access Error"

            if response.status_code == 404:

                return "AI Model Error"

            if response.status_code == 429:

                return "AI Busy"

            return "AI Error"


        # =================================================
        # JSON RESPONSE
        # =================================================

        try:

            data = response.json()

        except Exception as e:

            logger.error(
                "Gemini JSON parse error: %s",
                e
            )

            return "AI JSON Error"


        # =================================================
        # CANDIDATES
        # =================================================

        candidates = data.get(
            "candidates",
            []
        )

        if not candidates:

            logger.error(
                "Gemini returned no candidates: %s",
                data
            )

            return "AI Unavailable"


        # =================================================
        # CONTENT
        # =================================================

        content = candidates[0].get(
            "content",
            {}
        )


        # =================================================
        # PARTS
        # =================================================

        parts = content.get(
            "parts",
            []
        )

        if not parts:

            logger.error(
                "Gemini returned no parts: %s",
                data
            )

            return "AI Unavailable"


        # =================================================
        # TEXT
        # =================================================

        ai_reply = ""

        for part in parts:

            if isinstance(part, dict):

                part_text = part.get(
                    "text",
                    ""
                )

                if part_text:

                    ai_reply += " " + str(
                        part_text
                    )


        ai_reply = ai_reply.strip()


        if not ai_reply:

            logger.error(
                "Gemini returned empty text."
            )

            return "AI Unavailable"


        # =================================================
        # CLEAN RESPONSE
        # =================================================

        ai_reply = clean_ai_response(
            ai_reply
        )


        logger.info(
            "Gemini Reply: %s",
            ai_reply
        )


        return ai_reply


    # =====================================================
    # TIMEOUT
    # =====================================================

    except requests.exceptions.Timeout:

        logger.error(
            "Gemini request timeout."
        )

        return "AI Timeout"


    # =====================================================
    # CONNECTION ERROR
    # =====================================================

    except requests.exceptions.ConnectionError as e:

        logger.error(
            "Gemini connection error: %s",
            e
        )

        return "AI Offline"


    # =====================================================
    # GENERAL ERROR
    # =====================================================

    except Exception as e:

        logger.exception(
            "Gemini API Error: %s",
            e
        )

        return "AI Error"


# =========================================================
# ASYNC GEMINI WRAPPER
# =========================================================

async def ai_brain_process(
    message_text,
    plant_data=None
):

    global last_ai_request


    now = time.time()


    # =====================================================
    # COOLDOWN
    # =====================================================

    if (
        now - last_ai_request
        < AI_COOLDOWN
    ):

        logger.info(
            "Gemini cooldown active."
        )

        return None


    last_ai_request = now


    # =====================================================
    # CALL GEMINI
    # =====================================================

    try:

        result = await asyncio.to_thread(

            call_gemini_api,

            message_text,

            plant_data

        )

        return result


    except Exception as e:

        logger.exception(
            "AI wrapper error: %s",
            e
        )

        return "AI Error"


# =========================================================
# EXPRESSION DETECTOR
# =========================================================

def detect_expression(text):

    if not text:

        return "happy"


    t = text.lower()


    # =====================================================
    # WARNING
    # =====================================================

    if any(

        word in t

        for word in [

            "water",
            "thirsty",
            "hot",
            "heat",
            "warning",
            "dry",
            "humidity",
            "error",
            "danger"

        ]

    ):

        return "surprised"


    # =====================================================
    # POSITIVE
    # =====================================================

    if any(

        word in t

        for word in [

            "great",
            "good",
            "healthy",
            "perfect",
            "happy",
            "fine",
            "awesome",
            "nice"

        ]

    ):

        return "excited"


    # =====================================================
    # NEGATIVE
    # =====================================================

    if any(

        word in t

        for word in [

            "sad",
            "problem",
            "bad"

        ]

    ):

        return "sad"


    return "happy"


# =========================================================
# SEND COMMAND TO ESP32
# =========================================================

async def send_command_to_esp32(
    text,
    expression="happy"
):

    global mqtt_client


    if mqtt_client is None:

        logger.error(
            "MQTT client not available."
        )

        return False


    try:

        payload = {

            "type": "ai",

            "plant_id": PLANT_ID,

            "text": clean_ai_response(
                text
            ),

            "expr": expression,

            "timestamp": int(
                time.time()
            )

        }


        payload_string = json.dumps(

            payload,

            ensure_ascii=False

        )


        logger.info(
            "Publishing AI command: %s",
            payload_string
        )


        await mqtt_client.publish(

            COMMAND_TOPIC,

            payload_string.encode(
                "utf-8"
            ),

            QOS_1

        )


        logger.info(
            "AI command sent to ESP32."
        )

        return True


    except Exception as e:

        logger.exception(
            "MQTT publish error: %s",
            e
        )

        return False


# =========================================================
# DJANGO HEARTBEAT
# =========================================================

def send_django_heartbeat():

    if not DEVICE_TOKEN:

        logger.warning(
            "DEVICE_TOKEN not configured."
        )

        return False


    try:

        headers = {

            "Content-Type":
                "application/json",

            "X-Device-Token":
                DEVICE_TOKEN

        }


        payload = {

            "device_token":
                DEVICE_TOKEN

        }


        logger.info(
            "Django heartbeat..."
        )


        response = requests.post(

            DJANGO_HEARTBEAT_URL,

            headers=headers,

            json=payload,

            timeout=10

        )


        logger.info(
            "Django HTTP: %s",
            response.status_code
        )


        if response.status_code == 200:

            logger.info(
                "Django heartbeat SUCCESS"
            )

            return True


        logger.error(
            "Django heartbeat FAILED: %s",
            response.text[:500]
        )

        return False


    except requests.exceptions.Timeout:

        logger.error(
            "Django heartbeat timeout."
        )

        return False


    except requests.exceptions.ConnectionError as e:

        logger.error(
            "Django connection error: %s",
            e
        )

        return False


    except Exception as e:

        logger.exception(
            "Django heartbeat error: %s",
            e
        )

        return False


# =========================================================
# DJANGO HEARTBEAT LOOP
# =========================================================

async def django_heartbeat_loop():

    while True:

        try:

            await asyncio.to_thread(

                send_django_heartbeat

            )


        except Exception as e:

            logger.exception(
                "Heartbeat loop error: %s",
                e
            )


        await asyncio.sleep(
            60
        )


# =========================================================
# PROCESS AI REQUEST FROM DJANGO
# =========================================================

async def process_ai_request(
    decoded_msg
):

    logger.info(
        "AI REQUEST RECEIVED: %s",
        decoded_msg
    )


    data = parse_json_message(
        decoded_msg
    )


    # =====================================================
    # MESSAGE
    # =====================================================

    user_message = str(

        data.get(
            "message",
            ""
        )

    ).strip()


    # =====================================================
    # PLANT ID
    # =====================================================

    request_plant_id = str(

        data.get(
            "plant_id",
            PLANT_ID
        )

    )


    # =====================================================
    # EMPTY MESSAGE
    # =====================================================

    if not user_message:

        logger.warning(
            "Empty AI request received."
        )

        return


    logger.info(
        "AI request from Django | Plant=%s | Message=%s",
        request_plant_id,
        user_message
    )


    # =====================================================
    # GEMINI
    # =====================================================

    ai_reply = await ai_brain_process(

        user_message,

        data

    )


    if not ai_reply:

        logger.info(
            "AI request skipped because cooldown is active."
        )

        return


    # =====================================================
    # EXPRESSION
    # =====================================================

    expression = detect_expression(
        ai_reply
    )


    # =====================================================
    # SEND TO ESP32
    # =====================================================

    await send_command_to_esp32(

        ai_reply,

        expression

    )


# =========================================================
# PROCESS ESP32 STATUS EVENT
# =========================================================

async def process_esp32_status(
    decoded_msg
):

    logger.info(
        "ESP32 STATUS: %s",
        decoded_msg
    )


    data = parse_json_message(
        decoded_msg
    )


    # =====================================================
    # EVENT
    # =====================================================

    event = data.get(
        "event",
        ""
    )


    # =====================================================
    # TOUCH
    # =====================================================

    touch_pressed = data.get(
        "touch_pressed",
        False
    )


    # =====================================================
    # MESSAGE
    # =====================================================

    message_text = str(

        data.get(
            "message",
            ""
        )

    ).strip()


    # =====================================================
    # SENSOR DATA
    # =====================================================

    sensor_keys = [

        "temperature",

        "humidity",

        "soil_moisture",

        "soil",

        "light",

        "light_level"

    ]


    has_sensor_data = any(

        key in data

        for key in sensor_keys

    )


    # =====================================================
    # AI TRIGGER
    # =====================================================

    ai_trigger = (

        touch_pressed

        or event == "touch"

        or event == "ask_ai"

        or bool(message_text)

        or has_sensor_data

    )


    if not ai_trigger:

        logger.info(
            "ESP32 event does not require AI."
        )

        return


    # =====================================================
    # AI INPUT
    # =====================================================

    if message_text:

        ai_message = message_text


    elif touch_pressed:

        ai_message = (
            "The plant was touched. "
            "Greet the user."
        )


    elif event == "touch":

        ai_message = (
            "The plant was touched. "
            "Respond naturally."
        )


    else:

        ai_message = (
            "Analyze the current plant "
            "sensor condition."
        )


    # =====================================================
    # GEMINI
    # =====================================================

    ai_reply = await ai_brain_process(

        ai_message,

        data

    )


    if not ai_reply:

        return


    # =====================================================
    # EXPRESSION
    # =====================================================

    expression = detect_expression(
        ai_reply
    )


    # =====================================================
    # ESP32
    # =====================================================

    await send_command_to_esp32(

        ai_reply,

        expression

    )


# =========================================================
# PROCESS MQTT EVENT
# =========================================================

async def process_esp32_event(

    topic,

    decoded_msg

):

    logger.info(
        "MQTT EVENT [%s]: %s",
        topic,
        decoded_msg
    )


    # =====================================================
    # DJANGO -> AI REQUEST
    # =====================================================

    if topic == AI_REQUEST_TOPIC:

        await process_ai_request(
            decoded_msg
        )

        return


    # =====================================================
    # ESP32 STATUS
    # =====================================================

    if topic == STATUS_TOPIC:

        await process_esp32_status(
            decoded_msg
        )

        return


    # =====================================================
    # UNKNOWN TOPIC
    # =====================================================

    logger.info(
        "Ignoring unknown MQTT topic: %s",
        topic
    )


# =========================================================
# AMQTT MESSAGE RECEIVER
# =========================================================

async def mqtt_receive_loop():

    global mqtt_client


    while True:

        try:

            logger.info(
                "Waiting for MQTT message..."
            )


            message = await mqtt_client.deliver_message()


            # =================================================
            # AMQTT MESSAGE
            # =================================================

            packet = message.publish_packet


            topic = (
                packet.variable_header.topic_name
            )


            payload = (
                packet.payload.data
            )


            decoded_msg = payload.decode(

                "utf-8",

                errors="ignore"

            )


            await process_esp32_event(

                topic,

                decoded_msg

            )


        except asyncio.CancelledError:

            raise


        except Exception as e:

            logger.exception(
                "MQTT receive error: %s",
                e
            )

            await asyncio.sleep(
                3
            )

            break


# =========================================================
# CONNECT AMQTT CLIENT
# =========================================================

async def connect_mqtt_client():

    global mqtt_client


    mqtt_client = MQTTClient()


    try:

        logger.info(
            "Connecting AMQTT client..."
        )


        await mqtt_client.connect(

            "mqtt://"
            + MQTT_CLIENT_HOST
            + ":"
            + str(MQTT_CLIENT_PORT)

        )


        logger.info(
            "AMQTT client connected."
        )


        # =================================================
        # SUBSCRIBE STATUS + AI REQUEST
        # =================================================

        await mqtt_client.subscribe([

            (
                STATUS_TOPIC,
                QOS_1
            ),

            (
                AI_REQUEST_TOPIC,
                QOS_1
            )

        ])


        logger.info(
            "Subscribed: %s",
            STATUS_TOPIC
        )


        logger.info(
            "Subscribed: %s",
            AI_REQUEST_TOPIC
        )


        return True


    except Exception as e:

        logger.exception(
            "AMQTT connection error: %s",
            e
        )


        try:

            if mqtt_client:

                await mqtt_client.disconnect()

        except Exception:

            pass


        mqtt_client = None

        return False


# =========================================================
# START BROKER
# =========================================================

async def start_broker():

    global broker


    logger.info(
        "Starting AMQTT broker..."
    )


    broker = Broker(
        BROKER_CONFIG
    )


    try:

        await broker.start()


    except Exception as e:

        logger.exception(
            "AMQTT broker start failed: %s",
            e
        )

        raise


    logger.info(
        "=========================================="
    )

    logger.info(
        "PRATHAM AMQTT BROKER STARTED"
    )

    logger.info(
        "MQTT HOST: 0.0.0.0"
    )

    logger.info(
        "MQTT PORT: 1883"
    )

    logger.info(
        "ESP32 MQTT ADDRESS: PC_IP:1883"
    )

    logger.info(
        "AI REQUEST TOPIC: %s",
        AI_REQUEST_TOPIC
    )

    logger.info(
        "COMMAND TOPIC: %s",
        COMMAND_TOPIC
    )

    logger.info(
        "=========================================="
    )


# =========================================================
# BROKER CONTROLLER
# =========================================================

async def broker_controller():

    global mqtt_client


    # =====================================================
    # START BROKER
    # =====================================================

    await start_broker()


    # =====================================================
    # DJANGO HEARTBEAT
    # =====================================================

    asyncio.create_task(

        django_heartbeat_loop()

    )


    # =====================================================
    # MQTT CLIENT RETRY LOOP
    # =====================================================

    while True:

        connected = await connect_mqtt_client()


        if not connected:

            logger.warning(
                "AMQTT client retry in 5 seconds..."
            )

            await asyncio.sleep(
                5
            )

            continue


        try:

            await mqtt_receive_loop()


        except asyncio.CancelledError:

            raise


        except Exception as e:

            logger.exception(
                "MQTT loop error: %s",
                e
            )


        # =================================================
        # DISCONNECT
        # =================================================

        try:

            if mqtt_client:

                await mqtt_client.disconnect()

        except Exception:

            pass


        mqtt_client = None


        logger.warning(
            "MQTT client disconnected."
        )


        await asyncio.sleep(
            5
        )


# =========================================================
# MAIN
# =========================================================

def main():

    logger.info(
        "=========================================="
    )

    logger.info(
        "PRATHAM PLANT AI BRAIN"
    )

    logger.info(
        "AMQTT + DJANGO + GEMINI REST + ESP32"
    )

    logger.info(
        "=========================================="
    )


    logger.info(
        "Plant ID: %s",
        PLANT_ID
    )

    logger.info(
        "Status Topic: %s",
        STATUS_TOPIC
    )

    logger.info(
        "AI Request Topic: %s",
        AI_REQUEST_TOPIC
    )

    logger.info(
        "Command Topic: %s",
        COMMAND_TOPIC
    )

    logger.info(
        "Django URL: %s",
        DJANGO_URL
    )

    logger.info(
        "Gemini Model: %s",
        GEMINI_MODEL
    )


    # =====================================================
    # GEMINI STATUS
    # =====================================================

    if GEMINI_API_KEY:

        logger.info(
            "Gemini API key configured."
        )

    else:

        logger.warning(
            "Gemini API key NOT configured."
        )


    # =====================================================
    # DJANGO STATUS
    # =====================================================

    if DEVICE_TOKEN:

        logger.info(
            "Django device token configured."
        )

    else:

        logger.warning(
            "Django DEVICE_TOKEN not configured."
        )


    # =====================================================
    # START
    # =====================================================

    try:

        asyncio.run(

            broker_controller()

        )


    except KeyboardInterrupt:

        logger.info(
            "Server stopped by user."
        )


    except Exception as e:

        logger.exception(
            "Fatal error: %s",
            e
        )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    main()
import os
import json
import django
import paho.mqtt.client as mqtt

# Django Environment Setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'prathamesp32_project.settings')
django.setup()

from core.models import SensorData

BROKER_HOST = "localhost"
BROKER_PORT = 1883
TOPIC = "esp32/sensors"

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"Connected to MQTT Broker successfully!")
        client.subscribe(TOPIC)
        print(f"Subscribed to topic: {TOPIC}")
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        
        SensorData.objects.create(
            device_id=payload.get('device_id', 'unknown_device'),
            temperature=payload.get('temperature', 0.0),
            humidity=payload.get('humidity', 0.0)
        )
        print(f"[DB LOGGED] Saved reading for {payload.get('device_id')}")
        
    except Exception as e:
        print(f"Error logging payload: {e}")

# Callback API Version 2 set kiya gaya hai
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

if __name__ == "__main__":
    print("Starting Database Logger...")
    client.connect(BROKER_HOST, BROKER_PORT, 60)
    client.loop_forever()
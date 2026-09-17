import time
import json
from datetime import datetime
from django.core.management.base import BaseCommand
import paho.mqtt.publish as publish

# Aapka views.py wala MQTT config
MQTT_BROKER = "192.168.1.8"
MQTT_PORT = 1883

class Command(BaseCommand):
    help = 'Checks reminders every minute and triggers MQTT command to ESP32'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS("Starting Reminder Background Checker..."))
        
        while True:
            try:
                now = datetime.now().strftime("%H:%M")
                print(f"[REMINDER CHECKER] Current Time: {now}")
                
                # Yahan aap apne model se reminders check karke bhej sakte hain
                # Jaise:
                # reminders = Reminder.objects.filter(time=now)
                # for rem in reminders:
                #     payload = {
                #         "type": "reminder",
                #         "text": rem.message,
                #         "expr": "excited",
                #         "track": 2
                #     }
                #     topic = f"pratham/plant/{rem.plant_id}/commands"
                #     publish.single(topic, json.dumps(payload), hostname=MQTT_BROKER, port=MQTT_PORT, qos=1)

            except Exception as e:
                print(f"[REMINDER ERROR]: {e}")
            
            time.sleep(60) # Har 1 minute baad check karega
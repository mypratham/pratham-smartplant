import asyncio
import logging
from amqtt.broker import Broker

logging.basicConfig(level=logging.INFO)

config = {
    'listeners': {
        'default': {
            'type': 'tcp',
            'bind': '0.0.0.0:1883',
        },
    },
    'sys_interval': 10,
    'auth': {
        'allow-anonymous': True,
    },
}

async def start_broker():
    broker = Broker(config)
    await broker.start()
    print("MQTT Broker is running on port 1883...")
    # Keep the broker running continuously
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    try:
        asyncio.run(start_broker())
    except (KeyboardInterrupt, SystemExit):
        print("Broker stopped.")
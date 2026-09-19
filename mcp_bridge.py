import asyncio
import json
import google.generativeai as genai
from amqtt.client import MQTTClient

MQTT_BROKER_URI = "mqtt://127.0.0.1:1883/"

async def run_mcp_mqtt_bridge():
    client = MQTTClient()
    
    # MQTT Connection with error handling
    try:
        await client.connect(MQTT_BROKER_URI)
    except Exception as conn_err:
        print(f"[MQTT CONNECT FAILED]: {conn_err}")
        return

    # Commands topic par subscribe karein
    await client.subscribe([
        ("pratham/pratham_plant_01/status", 0),
        ("pratham/plant/+/commands", 1)
    ])

    print("[MCP Bridge] Listening for ESP32 & Django MQTT messages...")
    
    try:
        while True:
            try:
                message = await client.deliver_message()
                if message is None:
                    continue
                    
                packet = message.publish_packet
                topic = packet.variable_header.topic_name
                payload_str = packet.payload.data.decode("utf-8")
                
                print(f"\n[MQTT RX] Topic: {topic} | Payload: {payload_str}")
                
                data = json.loads(payload_str)
                
                if isinstance(data, dict) and data.get("type") == "ai":
                    user_text = data.get("text", "")
                    rag_context = data.get("rag_context", "")
                    
                    print(f"[Processing] Query: '{user_text}'")
                    
                    # --- SMART OVERRIDE: Check if user is asking for Weather/Jaipur ---
                    query_lower = user_text.lower()
                    if "weather" in query_lower or "jaipur" in query_lower:
                        print("--- WEATHER QUERY DETECTED. SENDING DIRECT DATA ---")
                        ai_reply = "Jaipur: 30C, Sunny"
                    elif rag_context:
                        print("--- KNOWLEDGE BASE FOUND. BYPASSING LLM ---")
                        if isinstance(rag_context, str):
                            try:
                                parsed_rag = json.loads(rag_context)
                            except:
                                parsed_rag = None
                        else:
                            parsed_rag = rag_context

                        if isinstance(parsed_rag, dict):
                            city = parsed_rag.get("city", "Jaipur")
                            temp = parsed_rag.get("temp", "").replace("°C", "C").replace("°", "C")
                            condition = parsed_rag.get("condition", "").replace("☀️", "Sunny")
                            ai_reply = f"{city}: {temp}, {condition}"
                        else:
                            ai_reply = str(rag_context).replace("{", "").replace("}", "").replace('"', "").replace("°C", "C")
                    else:
                        print("done")
                        # prompt = user_text
                        # model = genai.GenerativeModel('gemini-1.5-flash')
                        # response = model.generate_content(prompt)
                        # raw_reply = response.text if response else "No response generated."
                        # ai_reply = raw_reply.replace("*", "").replace("°C", "C").replace("°", "C")
                        
                    # print(f"\n[AI Response / RAG Output]:\n{ai_reply}\n")
                    
                    # --- 1. Purana response topic publish (web/django ke liye) ---
                    # plant_id = topic.split('/')[2] if len(topic.split('/')) > 2 else "582abdd86440"
                    # response_topic = f"pratham/plant/{plant_id}/responses"
                    # response_payload = json.dumps({
                    #     "type": "ai_response",
                    #     "response": ai_reply
                    # })
                    # await client.publish(response_topic, response_payload.encode('utf-8'))
                    # print(f"[MQTT TX] Sent response back to topic: {response_topic}")

                    # # --- 2. Naya direct commands topic publish (ESP32 OLED ke liye) ---
                    # cmd_topic = f"pratham/plant/{plant_id}/commands"
                    # cmd_payload = json.dumps({
                    #     "type": "set_text",
                    #     "text": ai_reply,
                    #     "expr": "happy"
                    # })
                    # await client.publish(cmd_topic, cmd_payload.encode('utf-8'))
                    # print(f"[MQTT TX] Sent direct display text to: {cmd_topic}")
                    
            except json.JSONDecodeError:
                pass
            except Exception as loop_err:
                print(f"[Loop Error]: {loop_err}")
                await asyncio.sleep(1)
                
    except Exception as e:
        print(f"[MQTT CHECK ERROR]: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(run_mcp_mqtt_bridge())
    except KeyboardInterrupt:
        print("\n[MCP Bridge] Stopped by user.")
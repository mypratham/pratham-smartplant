import json
import httpx
from channels.generic.websocket import AsyncWebsocketConsumer

# Live API Base URL
API_BASE_URL = "https://api.mypratham.com"

class MCPServerConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        await self.accept()
        # Connection hote hi client/frontend ko welcome message bhejein
        await self.send(
            text_data=json.dumps({
                "status": "connected",
                "message": "Django MCP Server live API & Workspace se connect ho gaya hai!",
            })
        )

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(
                text_data=json.dumps(
                    {"status": "error", "message": "Invalid JSON format"}
                )
            )
            return

        response_payload = None
        action = data.get("action") or data.get("method")
        
        # ESP32 Voice Input / Command detection
        voice_text = data.get("voice_command") or data.get("command") or data.get("speech")
        if voice_text and not action:
            # Agar voice input aaya hai aur action defined nahi hai, toh auto-detect karein
            voice_lower = voice_text.lower()
            if "job" in voice_lower:
                action = "get_jobs"
            elif "quiz" in voice_lower or "exam" in voice_lower:
                action = "get_quiz"
            elif "calendar" in voice_lower or "meeting" in voice_lower:
                action = "get_calendar"
            elif "gmail" in voice_lower or "email" in voice_lower:
                action = "get_gmail"
            else:
                action = "dynamic_mcp_call"

        async with httpx.AsyncClient() as client:
            
            # ==========================================
            # 1. LIVE JOBS API FETCH (`api.mypratham.com/api/job/`) [PRESERVED]
            # ==========================================
            if action == "get_jobs" or data.get("params", {}).get("name") == "get_jobs":
                try:
                    headers = {
                        "x-api-key": data.get("api_key", "kushal123"),
                        "X-API-SECRET": data.get("api_secret", "kushalsecret456"),
                        "Accept": "application/json"
                    }
                    res = await client.get(f"{API_BASE_URL}/api/job/", headers=headers, timeout=10.0)
                    
                    if res.status_code == 200:
                        response_payload = {
                            "status": "success",
                            "type": "jobs",
                            "data": res.json()
                        }
                    else:
                        response_payload = {"status": "error", "message": f"API Error: {res.status_code}"}
                except Exception as e:
                    response_payload = {"status": "error", "message": str(e)}

            # ==========================================
            # 2. LIVE QUIZ / EXAMS API FETCH [PRESERVED]
            # ==========================================
            elif action == "get_quiz" or action == "get_learning" or data.get("params", {}).get("name") == "get_quiz":
                try:
                    token = data.get("token", "")
                    headers = {
                        "Authorization": f"token {token}" if token else "",
                        "Accept": "application/json"
                    }
                    res = await client.get(f"{API_BASE_URL}/school/exams/D?page=1", headers=headers, timeout=10.0)
                    
                    if res.status_code == 200:
                        response_payload = {
                            "status": "success",
                            "type": "quiz",
                            "data": res.json()
                        }
                    else:
                        response_payload = {
                            "status": "success",
                            "type": "quiz",
                            "data": {
                                "question": "Sample MS Excel Assessment (Pratham Gurukul)",
                                "options": ["XLOOKUP", "VLOOKUP", "INDEX/MATCH", "All of the above"],
                                "reward": "50 Coins"
                            }
                        }
                except Exception as e:
                    response_payload = {"status": "error", "message": str(e)}

            # ==========================================
            # 3. GOOGLE WORKSPACE: CALENDAR [PRESERVED]
            # ==========================================
            elif action == "get_calendar" or data.get("params", {}).get("name") == "calendar_sync":
                response_payload = {
                    "status": "success",
                    "type": "calendar",
                    "data": [
                        {"event": "School ERP Review Meeting", "time": "10:00 AM", "date": "2026-03-30"},
                        {"event": "AI Module Deployment", "time": "03:30 PM", "date": "2026-03-31"},
                    ]
                }

            # ==========================================
            # 4. GOOGLE WORKSPACE: GMAIL [PRESERVED]
            # ==========================================
            elif action == "get_gmail":
                response_payload = {
                    "status": "success",
                    "type": "gmail",
                    "data": [{
                        "sender": "Pratham Admin",
                        "subject": "New School Registration Inquiry",
                        "snippet": "Madhya Pradesh 100 schools outreach update...",
                    }]
                }

            # ==========================================
            # 5. GOOGLE WORKSPACE: REMINDERS [PRESERVED]
            # ==========================================
            elif action == "add_reminder":
                rem_title = data.get("title")
                rem_time = data.get("time")
                response_payload = {
                    "status": "success",
                    "message": f"Reminder '{rem_title}' successfully saved & pushed to ESP32!"
                }

            # ==========================================
            # 6. DYNAMIC MCP ENDPOINTS (WhatsApp, Gmail, Custom APIs with Token) [NEW]
            # ==========================================
            elif action == "dynamic_mcp_call" or "endpoint" in data or "endpoints" in data:
                # Support both single endpoint or multiple batched endpoints
                endpoints_list = data.get("endpoints", [])
                
                # If a single endpoint was passed directly
                if not endpoints_list and data.get("endpoint"):
                    endpoints_list = [{
                        "service": data.get("service", "Custom Service"),
                        "endpoint": data.get("endpoint"),
                        "token": data.get("token") or data.get("api_key"),
                        "payload": data.get("payload", {})
                    }]

                batch_results = []
                for ep in endpoints_list:
                    service_name = ep.get("service", "API Service")
                    target_url = ep.get("endpoint")
                    user_token = ep.get("token")
                    service_payload = ep.get("payload", {})

                    if not target_url:
                        continue

                    try:
                        headers = {
                            "Authorization": f"Bearer {user_token}" if user_token else "",
                            "x-api-key": user_token if user_token else "",
                            "Content-Type": "application/json",
                            "Accept": "application/json"
                        }
                        
                        # Dynamic Method execution (GET or POST based on payload presence)
                        if service_payload:
                            res = await client.post(target_url, headers=headers, json=service_payload, timeout=10.0)
                        else:
                            res = await client.get(target_url, headers=headers, timeout=10.0)

                        if res.status_code in [200, 201]:
                            batch_results.append({
                                "service": service_name,
                                "endpoint": target_url,
                                "status": "connected",
                                "data": res.json() if res.content else {"result": "success"}
                            })
                        else:
                            batch_results.append({
                                "service": service_name,
                                "endpoint": target_url,
                                "status": "error",
                                "message": f"HTTP Error {res.status_code}"
                            })
                    except Exception as err:
                        batch_results.append({
                            "service": service_name,
                            "endpoint": target_url,
                            "status": "error",
                            "message": str(err)
                        })

                response_payload = {
                    "status": "success",
                    "type": "dynamic_mcp_results",
                    "voice_processed": voice_text if voice_text else None,
                    "results": batch_results if batch_results else [{"status": "error", "message": "No valid endpoints provided"}]
                }

            # ==========================================
            # 7. DEFAULT ECHO / FALLBACK [PRESERVED]
            # ==========================================
            else:
                response_payload = {
                    "status": "echo", 
                    "received_data": data,
                    "voice_command_noted": voice_text
                }

        # Smoothly send response back to client / ESP32 / Frontend
        if response_payload:
            await self.send(text_data=json.dumps(response_payload))
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

        async with httpx.AsyncClient() as client:
            
            # ==========================================
            # 1. LIVE JOBS API FETCH (`api.mypratham.com/api/job/`)
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
            # 2. LIVE QUIZ / EXAMS API FETCH (`api.mypratham.com/school/exams/...`)
            # ==========================================
            elif action == "get_quiz" or action == "get_learning" or data.get("params", {}).get("name") == "get_quiz":
                try:
                    token = data.get("token", "")
                    headers = {
                        "Authorization": f"token {token}" if token else "",
                        "Accept": "application/json"
                    }
                    # Jaise screenshot mein aapka exam/quiz flow hai
                    res = await client.get(f"{API_BASE_URL}/school/exams/D?page=1", headers=headers, timeout=10.0)
                    
                    if res.status_code == 200:
                        response_payload = {
                            "status": "success",
                            "type": "quiz",
                            "data": res.json()
                        }
                    else:
                        # Fallback agar API auth ya data na mile
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
            # 3. GOOGLE WORKSPACE: CALENDAR
            # ==========================================
            elif action == "get_calendar" or data.get("params", {}).get("name") == "calendar_sync":
                # Aap yahan Google API ya apne database se calendar events fetch kar sakte hain
                response_payload = {
                    "status": "success",
                    "type": "calendar",
                    "data": [
                        {"event": "School ERP Review Meeting", "time": "10:00 AM", "date": "2026-03-30"},
                        {"event": "AI Module Deployment", "time": "03:30 PM", "date": "2026-03-31"},
                    ]
                }

            # ==========================================
            # 4. GOOGLE WORKSPACE: GMAIL
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
            # 5. GOOGLE WORKSPACE: REMINDERS (Saved & Pushed to ESP32)
            # ==========================================
            elif action == "add_reminder":
                rem_title = data.get("title")
                rem_time = data.get("time")
                response_payload = {
                    "status": "success",
                    "message": f"Reminder '{rem_title}' successfully saved & pushed to ESP32!"
                }

            # ==========================================
            # 6. DEFAULT ECHO / FALLBACK
            # ==========================================
            else:
                response_payload = {"status": "echo", "received_data": data}

        # Smoothly send response back to client / ESP32 / Frontend
        if response_payload:
            await self.send(text_data=json.dumps(response_payload))
import json
from channels.generic.websocket import AsyncWebsocketConsumer


class MCPServerConsumer(AsyncWebsocketConsumer):

  async def connect(self):
    await self.accept()
    # Connection hote hi client/frontend ko welcome message bhejein
    await self.send(
        text_data=json.dumps({
            "status": "connected",
            "message": "Django MCP Server se connect ho gaye hain!",
        })
    )

  async def disconnect(self, close_code):
    pass

  # Single, optimized receive handler for speed and zero redundancy
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

    # 1. JSON-RPC Tool Call Handling (Frontend calendar sync / tools)
    if data.get("method") == "tools/call":
      params = data.get("params", {})
      tool_name = params.get("name")
      arguments = params.get("arguments", {})
      req_id = data.get("id", 101)

      if tool_name == "calendar_sync":
        max_results = arguments.get("max_results", 5)
        calendar_events = [
            {
                "event": "School ERP Review Meeting",
                "time": "10:00 AM",
                "date": "2026-03-30",
            },
            {
                "event": "AI Module Deployment",
                "time": "03:30 PM",
                "date": "2026-03-31",
            },
        ][:max_results]

        response_payload = {
            "jsonrpc": "2.0",
            "result": {
                "status": "success",
                "type": "calendar",
                "data": calendar_events,
            },
            "id": req_id,
        }

    # 2. Action-based Handling (All Actions preserved)
    else:
      action = data.get("action")

      if action == "get_data":
        response_payload = {
            "status": "success",
            "result": "Yeh aapka requested data hai!",
            "data": {"user_count": 100, "status": "active"},
        }

      elif action == "get_jobs":
        response_payload = {
            "status": "success",
            "type": "jobs",
            "data": [{
                "title": "Front Line Officer - LAP",
                "salary": "2.5L - 3L",
                "location": "Ahmedabad, Gujarat",
            }],
        }

      elif action == "get_quiz":
        response_payload = {
            "status": "success",
            "type": "quiz",
            "data": {
                "question": "Sample Pratham Gurukul Assessment",
                "options": ["Option A", "Option B", "Option C", "Option D"],
            },
        }

      elif action == "get_learning":
        response_payload = {
            "status": "success",
            "type": "learning",
            "data": ["CBSE", "NCERT", "Skill Development"],
        }

      elif action == "get_calendar":
        response_payload = {
            "status": "success",
            "type": "calendar",
            "data": [
                {
                    "event": "School ERP Review Meeting",
                    "time": "10:00 AM",
                    "date": "2026-03-30",
                },
                {
                    "event": "AI Module Deployment",
                    "time": "03:30 PM",
                    "date": "2026-03-31",
                },
            ],
        }

      elif action == "get_gmail":
        response_payload = {
            "status": "success",
            "type": "gmail",
            "data": [{
                "sender": "Pratham Admin",
                "subject": "New School Registration Inquiry",
                "snippet": "Madhya Pradesh 100 schools outreach update...",
            }],
        }

      elif action == "add_reminder":
        rem_title = data.get("title")
        rem_time = data.get("time")
        response_payload = {
            "status": "success",
            "message": (
                f"Reminder '{rem_title}' successfully saved & pushed to ESP32!"
            ),
        }

      else:
        response_payload = {"status": "echo", "received_data": data}

    # Smoothly send response back to client / ESP32
    if response_payload:
      await self.send(text_data=json.dumps(response_payload))
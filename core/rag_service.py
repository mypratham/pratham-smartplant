from django.db.models import Q
from functools import reduce
import operator
import json
from .models import DocumentChunk, Document

# =========================================================
# GLOBAL CONVERSATION & STATE TRACKER FOR SINGLE-TURN / SLEEP
# =========================================================
plant_conversation_state = {}

def get_plant_state(plant_id):
    if plant_id not in plant_conversation_state:
        plant_conversation_state[plant_id] = {"sleeping": False, "awaiting_followup": False}
    return plant_conversation_state[plant_id]

# =========================================================
# IMPROVED & FLEXIBLE RAG SEARCH LOGIC
# =========================================================
def get_rag_context(query):
    try:
        if not query:
            return ""
            
        query_lower = query.lower().strip()
        
        # 1. Direct Document Name Match
        matching_docs = []
        for doc in Document.objects.all():
            if doc.name.lower() in query_lower or query_lower in doc.name.lower():
                matching_docs.append(doc)
                
        if matching_docs:
            chunks = DocumentChunk.objects.filter(document__in=matching_docs)[:3]
            if chunks:
                return "\n\n".join([f"[Source Document: {c.document.name}]\n{c.chunk_text}" for c in chunks])

        # 2. Relaxed Word Filter (Length > 2 rakhein taaki chhote important words bhi aayein)
        query_words = [word.strip() for word in query_lower.split() if len(word) > 2]
        
        if not query_words:
            # Agar sare words chhote hain, toh poori query hi use kar lo
            query_words = [query_lower]
        
        q_filters = reduce(operator.or_, [Q(chunk_text__icontains=word) for word in query_words])
        matched_chunks = DocumentChunk.objects.filter(q_filters).distinct()[:15]
        
        scored_chunks = []
        for chunk in matched_chunks:
            chunk_lower = chunk.chunk_text.lower()
            # Count matching words
            score = sum(1 for word in query_words if word in chunk_lower)
            
            # FIXED: Score >= 1 kar diya hai taaki 1 bhi word match ho toh context mil jaye
            if score >= 1:
                formatted_text = f"[Source Document: {chunk.document.name}]\n{chunk.chunk_text}"
                scored_chunks.append((score, formatted_text))
                
        if not scored_chunks:
            return "" 
            
        # Score ke hisaab se sort karke top chunks return karein
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        top_context = "\n\n".join([item[1] for item in scored_chunks[:3]])
        
        return top_context
        
    except Exception as e:
        print(f"[RAG ERROR] Failed to fetch context: {e}")
        return ""

# =========================================================
# SINGLE-TURN & SLEEP/WAKE CONTROLLER
# =========================================================
def handle_incoming_audio_stream(plant_id, user_text, mqtt_client):
    state = get_plant_state(plant_id)
    
    print(f"[USER TRANSCRIBED VOICE]: '{user_text}'")
    
    if not user_text or "no_speech" in user_text.lower() or len(user_text.strip()) < 2:
        print("[FILTER] No actual speech detected. Halting execution.")
        return

    user_text_lower = user_text.lower().strip()

    if state["sleeping"]:
        wake_words = ["hi", "hello", "pratham", "hey", "wake"]
        if any(w in user_text_lower for w in wake_words):
            state["sleeping"] = False
            state["awaiting_followup"] = False
            
            wake_payload = json.dumps({"type": "sleep_mode", "state": False})
            mqtt_client.publish(f"pratham/plant/{plant_id}/commands", wake_payload)
            
            reply = "Main jaag gaya hoon! Bataiye, kis topic par janna chahte hain?"
            send_ai_response_to_esp32(mqtt_client, plant_id, reply, "happy")
        else:
            print(f"[SLEEP MODE] Plant {plant_id} is sleeping. Ignoring audio.")
        return

    if state["awaiting_followup"]:
        state["awaiting_followup"] = False
        if any(word in user_text_lower for word in ['no', 'nahi', 'nah', 'nope', 'nahin', 'na']):
            state["sleeping"] = True
            sleep_payload = json.dumps({"type": "sleep_mode", "state": True})
            mqtt_client.publish(f"pratham/plant/{plant_id}/commands", sleep_payload)
            
            reply = "Theek hai, main sleep mode mein ja raha hoon. Dobara baat karne ke liye 'Hello' kahein!"
            send_ai_response_to_esp32(mqtt_client, plant_id, reply, "sleep")
            return

    # Normal RAG Knowledge Base Search Execution
    rag_context = get_rag_context(user_text)
    
    if rag_context:
        ai_reply = rag_context
    else:
        ai_reply = f"Aapne '{user_text}' kaha. Iske baare mein mere knowledge base mein data nahi hai."

    full_reply = f"{ai_reply}\n\nKya aap aur kuch janna chahte hain? (Yes/No)"
    state["awaiting_followup"] = True 

    send_ai_response_to_esp32(mqtt_client, plant_id, full_reply, "excited")

def send_ai_response_to_esp32(mqtt_client, plant_id, text_response, expr):
    payload = json.dumps({
        "type": "ai",
        "text": text_response,
        "expr": expr
    })
    mqtt_client.publish(f"pratham/plant/{plant_id}/commands", payload)
    print(f"[AI REPLY SENT]: {text_response[:40]}...")
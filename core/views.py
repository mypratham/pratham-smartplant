import json
import os
import re
import uuid
import wave
from difflib import SequenceMatcher

import requests
import paho.mqtt.publish as publish
from pypdf import PdfReader
from docx import Document as DocxDocument
from pydub import AudioSegment
from gtts import gTTS
import whisper
import google.generativeai as genai
import openai
from openai import OpenAI

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required

# Models Import
from .models import Device, User, AIAgent, KnowledgeBase, Document, DocumentChunk, Reminder, PlantChatHistory
from .rag_service import get_rag_context

# ==========================================
# 1. FFMPEG & PYDUB SETUP
# ==========================================
ffmpeg_bin_path = r"C:\ffmpeg-2026-09-14-git-6efe500d2e-essentials_build\bin"
if ffmpeg_bin_path not in os.environ.get("PATH", ""):
    os.environ["PATH"] += os.pathsep + ffmpeg_bin_path

AudioSegment.converter = os.path.join(ffmpeg_bin_path, "ffmpeg.exe")
AudioSegment.ffprobe   = os.path.join(ffmpeg_bin_path, "ffprobe.exe")

# ==========================================
# 2. CONFIGURATIONS & CONSTANTS
# ==========================================
MQTT_BROKER = getattr(settings, "MQTT_BROKER", "192.168.1.9")
MQTT_PORT = getattr(settings, "MQTT_PORT", 1883)

PRATHAM_SYSTEM_INSTRUCTION = (
    "Aap 'Pratham' hain, ek smart intelligent assistant aur smart pratham helper. "
    "Aapko user ke har sawal ka jawab Hindi (Hinglish ya शुद्ध हिंदी जैसा user pooche) mein "
    "bohot hi saaf, madadgar aur thoda friendly tarike se dena hai. "
    "Agar koi GK (General Knowledge) ya quiz chale, toh user ke jawab ko evaluate karke agla sawal puchein. "
    "OLED screen ke liye jawab hamesha chhota, seedha aur crisp hona chahiye."
)

RAG_HINDI_ALIASES = {
    "इंडिया": "india",
    "भारत": "india",
    "जीके": "gk",
    "जि के": "gk",
    "सामान्य ज्ञान": "gk",
    "सामान्य": "general",
    "ज्ञान": "knowledge",
    "क्विज": "quiz",
    "क्विज़": "quiz",
    "प्रश्न": "question",
    "सवाल": "question",
    "राजस्थान": "rajasthan",
    "पौधा": "plant",
    "पौधे": "plant",
    "पानी": "water",
    "तुलसी": "tulsi",
    "तापमान": "temperature",
}

# ==========================================
# 3. GLOBAL MODEL INITIALIZATION
# ==========================================
try:
    LOCAL_WHISPER_MODEL = whisper.load_model("base")
    print("[SUCCESS] Local Whisper Model loaded successfully!")
except Exception as e:
    LOCAL_WHISPER_MODEL = None
    print(f"[ERROR] Failed to load Local Whisper Model: {e}")

# ==========================================
# 4. HELPER FUNCTIONS
# ==========================================
def is_admin(user):
    """Helper function to verify if the user has Admin privileges."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return True
    profile = getattr(user, 'profile', None)
    if profile and getattr(profile, 'role', '') == 'admin':
        return True
    return False


def get_openai_client():
    """Safely fetch and initialize OpenAI client."""
    api_key = getattr(settings, "OPENAI_API_KEY", None) or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("[WARNING]: OPENAI_API_KEY missing in settings or environment!")
        return None
    return OpenAI(api_key=api_key)


def _clean_stt_query(query):
    """Whisper STT Garbage & Noise Cleaner"""
    q = (query or "").lower().strip()

    if len(q) < 3 or q in ["ga u", "gau", "a u", "um", "uh"]:
        return ""

    replacements = [
        (r'\b(jai puri|jaipuri|jay pur|jaypuri|jai pur)\b', 'jaipur'),
        (r'\b(baattao|batao|bataao|batae)\b', 'batao'),
        (r'\b(ndigk|ndgk|indagk|indiagk|india jike|in dear geeks|dear geeks|indiani)\b', 'india gk'),
        (r'\b(mpgkb|mp gk b|mbg|mpg|mp jike|noibrato|dhoso|dhosow)\b', 'mp gk 200'),
        (r'\b(faps|fets|fakt|fackts|faixt|gkfx)\b', 'facts'),
        (r'\b(pestiry|pastery|pastry)\b', 'history'),
    ]

    for pattern, repl in replacements:
        q = re.sub(pattern, repl, q)

    return q


def call_fallback_ai(query):
    """KB match fail hone par OpenAI GPT model call karega without NameError."""
    if not query or len(query) < 2:
        return "Kripya thoda saaf bolein."

    try:
        client = get_openai_client()
        if not client:
            return "Kshama kijiye, OpenAI API Key system mein configure nahi hai."

        print(f"[FALLBACK AI TRIGGERED]: Querying OpenAI for '{query}'...")

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are an AI assistant for a smart device. Answer the user query in simple, short, natural Hindi/Hinglish (1-2 sentences max)."
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            max_tokens=120,
            temperature=0.7,
        )
        answer = response.choices[0].message.content.strip()
        print(f"[FALLBACK AI SUCCESS]: Generated Answer -> {answer}")
        return answer

    except Exception as e:
        print(f"[FALLBACK AI ERROR]: {e}")
        return "Kshama kijiye, mujhe is baare mein abhi jankari nahi mili."


def _rag_normalize(value):
    if value is None:
        return ""
    value = str(value)
    value = re.sub(r'[^\x20-\x7E\u0900-\u097F]', '', value)
    value = value.replace("_", " ").replace("-", " ").replace("/", " ")
    value = value.casefold()
    return re.sub(r"\s+", " ", value).strip()


def normalize_text(text):
    clean = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", clean).strip()


def is_fuzzy_match(query, target, threshold=0.70):
    q_norm = normalize_text(query)
    t_norm = normalize_text(target)

    if not q_norm or not t_norm:
        return False

    q_compact = q_norm.replace(" ", "")
    t_compact = t_norm.replace(" ", "")

    if q_compact == t_compact:
        return True

    ratio = SequenceMatcher(None, q_compact, t_compact).ratio()
    return ratio >= threshold


def _rag_query_terms(query):
    normalized = _rag_normalize(query)
    if not normalized:
        return []

    terms = []
    for word in re.findall(r"[\w\u0900-\u097F]+", normalized, flags=re.UNICODE):
        if len(word) >= 2 and word not in terms:
            terms.append(word)

    stop_words = {
        "hai", "hain", "ho", "kya", "ka", "ke", "ki", "ko", "me", "mein",
        "mujhe", "batao", "bata", "please", "the", "is", "a", "an", "of",
        "what", "tell", "about", "can", "you", "do", "how", "much", "karo",
        "chahiye", "mujhko", "ye", "yah", "vo", "woh", "where", "he", "she",
        "का", "के", "की", "है", "हैं", "में", "को", "क्या", "बताओ", "मुझे",
    }
    return [t for t in terms if t not in stop_words]


def find_kb_matches(query, limit=5):
    terms = _rag_query_terms(query)
    if not terms:
        return []

    try:
        chunks = DocumentChunk.objects.select_related(
            "document", "document__knowledge_base"
        ).all()
    except Exception as exc:
        print(f"[RAG QUERY ERROR]: {exc}")
        return []

    scored = []
    normalized_query = _rag_normalize(query)

    for chunk in chunks:
        try:
            raw_text = getattr(chunk, "chunk_text", "") or ""
            if not raw_text.strip():
                continue

            chunk_text = _rag_normalize(raw_text)
            document = getattr(chunk, "document", None)
            doc_name = _rag_normalize(getattr(document, "name", ""))
            kb = getattr(document, "knowledge_base", None)
            kb_name = _rag_normalize(getattr(kb, "name", ""))

            searchable = f"{chunk_text} {doc_name} {kb_name}".strip()
            if not searchable:
                continue

            score = 0
            matched = set()

            if normalized_query and normalized_query in searchable:
                score += 100

            for term in terms:
                term_score = 0
                if term in chunk_text:
                    term_score += 30
                    matched.add(term)
                if term in doc_name:
                    term_score += 25
                    matched.add(term)
                if term in kb_name:
                    term_score += 20
                    matched.add(term)
                score += term_score

            if matched:
                score += len(matched) * 15
                scored.append((score, chunk))

        except Exception:
            continue

    scored.sort(key=lambda item: (-item[0], getattr(item[1], "chunk_index", 0)))

    results = []
    seen = set()
    for score, chunk in scored:
        chunk_id = getattr(chunk, "id", None)
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        results.append({
            "score": score,
            "chunk": chunk,
            "text": getattr(chunk, "chunk_text", "") or "",
            "document": getattr(getattr(chunk, "document", None), "name", ""),
            "knowledge_base": getattr(getattr(getattr(chunk, "document", None), "knowledge_base", None), "name", ""),
            "chunk_index": getattr(chunk, "chunk_index", 0),
        })
        if len(results) >= limit:
            break

    return results


def get_kb_context_direct(query, limit=5):
    raw_query = (query or "").strip()

    if len(raw_query) < 2:
        return "Kripya thoda saaf bolein.", []

    clean_query = _clean_stt_query(raw_query)
    query_words = clean_query.split()

    # LEVEL 1: KB Match
    if len(query_words) <= 2:
        kb_list = KnowledgeBase.objects.filter(status__iexact='enabled')
        for kb in kb_list:
            if is_fuzzy_match(clean_query, kb.name, threshold=0.70):
                docs = kb.documents.all()
                if docs.exists():
                    doc_names = [
                        d.name.replace('_', ' ').replace('.txt', '').replace('.xlsx', '') 
                        for d in docs
                    ]
                    options_str = " ya ".join(doc_names)
                    custom_prompt_text = (
                        f"{kb.name} mein aap kya janna chahte hain? "
                        f"Aap inse related pooch sakte hain: {options_str}."
                    )
                    fake_match = [{'text': custom_prompt_text, 'score': 100, 'document': kb.name, 'chunk_index': 0, 'is_direct_prompt': True}]
                    return custom_prompt_text, fake_match

    # LEVEL 2: Document Match
    if len(query_words) <= 3:
        all_docs = Document.objects.select_related('knowledge_base').all()
        for doc in all_docs:
            doc_clean_name = doc.name.lower().replace('_', ' ').replace('.txt', '').replace('.xlsx', '')
            if is_fuzzy_match(clean_query, doc_clean_name, threshold=0.65):
                doc_display_name = doc.name.replace('_', ' ').replace('.txt', '').replace('.xlsx', '')
                custom_prompt_text = f"Aap {doc_display_name} ke baare mein kya poochhna chahte hain?"
                fake_match = [{'text': custom_prompt_text, 'score': 100, 'document': doc.name, 'chunk_index': 0, 'is_direct_prompt': True}]
                return custom_prompt_text, fake_match

    # LEVEL 3: KB Chunk Search
    matches = find_kb_matches(clean_query, limit=limit)
    valid_matches = [m for m in matches if m.get("score", 0) >= 20]

    if valid_matches:
        context = "\n\n".join(
            f"[{m.get('document', 'doc')} | Chunk {m.get('chunk_index', 0)}]\n{m.get('text', '')}"
            for m in valid_matches
        )
        return context, valid_matches

    # LEVEL 4: FALLBACK TO OPENAI AI
    ai_answer = call_fallback_ai(clean_query)
    fake_match = [{'text': ai_answer, 'score': 50, 'document': 'OpenAI Fallback', 'chunk_index': 0, 'is_direct_prompt': True}]
    return ai_answer, fake_match


def build_kb_answer(query, matches, max_chars=512):
    if not matches:
        return ""

    if len(matches) == 1 and matches[0].get("is_direct_prompt"):
        return matches[0].get("text", "")

    terms = _rag_query_terms(query)
    if not terms:
        return ""

    candidates = []

    for match in matches:
        text = " ".join(str(match.get("text", "")).split())
        if not text:
            continue

        parts = re.split(r"(?<=[.!?।])\s+|\n+", text)
        for part in parts:
            part = part.strip(" -•\t")
            if not part:
                continue

            p_norm = _rag_normalize(part)
            hit_count = sum(1 for term in terms if term in p_norm)

            if hit_count > 0:
                sentence_score = hit_count * 20 + min(len(part), 180) / 1000
                candidates.append((sentence_score, part))

    if not candidates:
        return ""

    candidates.sort(key=lambda x: -x[0])
    answer = candidates[0][1]

    if len(answer) > max_chars:
        answer = answer[:max_chars].rsplit(" ", 1)[0].strip() + "…"

    return answer


def get_safe_ai_text(response, default="Hello"):
    try:
        text = getattr(response, "text", "") or ""
        return text.strip() or default
    except Exception:
        return default


def parse_ai_json(text, default_text="Hello", default_expr="happy"):
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```JSON", "").replace("```", "").strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return {"text": cleaned or default_text, "expr": default_expr}


def generate_plant_tts(request, plant_id, text, filename_prefix="plant"):
    audio_url = ""
    try:
        if not text:
            return ""

        tts = gTTS(text=text, lang="hi", slow=False)
        filename = f"{filename_prefix}_{plant_id}_speech.mp3"
        media_root = getattr(settings, "MEDIA_ROOT", os.path.join(settings.BASE_DIR, "media"))
        os.makedirs(media_root, exist_ok=True)
        audio_path = os.path.join(media_root, filename)
        tts.save(audio_path)

        media_url = getattr(settings, "MEDIA_URL", "/media/")
        audio_url = request.build_absolute_uri(f"{media_url}{filename}")
    except Exception as exc:
        print(f"[TTS ERROR]: {exc}")
    return audio_url


def save_chat_history_and_device_state(device, user_text, ai_reply):
    user_text_clean = str(user_text).strip() if user_text else "No user input"
    ai_reply_clean = str(ai_reply).strip() if ai_reply else "No response"

    try:
        history = PlantChatHistory.objects.create(
            device=device,
            user_text=user_text_clean,
            ai_response=ai_reply_clean
        )
        print(f"[CHAT HISTORY SAVED]: ID {history.id}")
    except Exception as exc:
        print(f"[CHAT HISTORY SAVE ERROR]: {exc}")

    try:
        fields_to_update = []
        if hasattr(device, "custom_text"):
            device.custom_text = ai_reply_clean
            fields_to_update.append("custom_text")
            
        if hasattr(device, "current_expression"):
            device.current_expression = "happy"
            fields_to_update.append("current_expression")

        if fields_to_update:
            device.save(update_fields=fields_to_update)
            print(f"[DEVICE STATE SAVED]: Updated {fields_to_update}")
            
    except Exception as exc:
        print(f"[DEVICE STATE SAVE ERROR]: {exc}")


def get_document_chunks_count(d):
    try:
        if hasattr(d, 'chunks'):
            return d.chunks.count()
        elif hasattr(d, 'documentchunk_set'):
            return d.documentchunk_set.count()
        else:
            return DocumentChunk.objects.filter(document=d).count()
    except Exception:
        return DocumentChunk.objects.filter(document=d).count()


def save_pcm_as_wav(pcm_file_path, wav_file_path, sample_rate=16000):
    with open(pcm_file_path, 'rb') as pcm_file:
        pcm_data = pcm_file.read()

    with wave.open(wav_file_path, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)


def fetch_realtime_weather(city="Jaipur"):
    """Free weather API helper (wttr.in)"""
    try:
        url = f"https://wttr.in/{city}?format=j1"
        res = requests.get(url, timeout=3).json()
        curr = res['current_condition'][0]
        temp = curr['temp_C']
        desc = curr['weatherDesc'][0]['value']
        rain_chance = res['weather'][0]['hourly'][0]['chanceofrain']
        
        return f"{city} mein abhi taapmaan {temp}°C hai. Mausam: {desc}. Baarish ki sambhavna {rain_chance}% hai."
    except Exception as e:
        print(f"[WEATHER API ERROR]: {e}")
        return f"Kshama karein, {city} ke mausam ki jankari milne mein samasya aayi."

# ==========================================
# 5. VIEWS & API ENDPOINTS
# ==========================================
@login_required
def admin_dashboard(request):
    if getattr(request.user, "role", None) != getattr(User.Role, "ADMIN", "admin"):
        return JsonResponse({"error": "Access Denied"}, status=403)

    my_devices = Device.objects.filter(owner_admin=request.user)
    context = {
        "admin_name": request.user.username,
        "devices": my_devices,
        "active_device_count": my_devices.filter(is_online=True).count(),
    }
    return render(request, "dashboard.html", context)


def dashboard(request):
    return render(request, "index.html")

# ==========================================
# ADMIN AUTHENTICATION APIs
# ==========================================
import json
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def admin_login_api(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            username = data.get("username", "").strip()
            password = data.get("password", "").strip()

            if not username or not password:
                return JsonResponse({"status": "error", "error": "Username and password required"}, status=400)

            # Django User Authentication
            user = authenticate(request, username=username, password=password)

            if user is not None:
                login(request, user)
                return JsonResponse({
                    "status": "success",
                    "message": "Login successful",
                    "token": "admin_session_active"
                })
            else:
                return JsonResponse({"status": "error", "error": "Invalid username or password"}, status=400)

        except Exception as e:
            return JsonResponse({"status": "error", "error": str(e)}, status=500)

    return JsonResponse({"error": "Method not allowed"}, status=405)


@csrf_exempt
def admin_register_api(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            username = data.get("email", "").strip() or data.get("name", "").strip()
            password = data.get("password", "").strip()

            if not username or not password:
                return JsonResponse({"status": "error", "error": "Email/Username and Password required"}, status=400)

            if User.objects.filter(username=username).exists():
                return JsonResponse({"status": "error", "error": "User already exists!"}, status=400)

            # Create Superuser/Admin
            user = User.objects.create_user(username=username, email=username, password=password)
            user.is_staff = True  # Staff access
            user.save()

            return JsonResponse({"status": "success", "message": "Admin account created successfully!"})

        except Exception as e:
            return JsonResponse({"status": "error", "error": str(e)}, status=500)

    return JsonResponse({"error": "Method not allowed"}, status=405)


@csrf_exempt
def device_heartbeat(request, plant_id):
    if request.method == 'GET':
        device = Device.objects.filter(plant_id=plant_id).first()
        if device:
            device.is_online = True
            device.save(update_fields=['is_online'])
            return JsonResponse({
                "status": "ok",
                "action": "none",
                "plant_id": device.plant_id,
                "device_token": device.device_token,
                "is_online": True
            }, status=200)
        
        return JsonResponse({
            "status": "waiting_for_pairing",
            "action": "none",
            "message": "Waiting for user pairing"
        }, status=200)

    elif request.method == 'POST':
        try:
            data = json.loads(request.body or "{}")
            pairing_code = data.get('pairing_code')
            device_token = data.get('device_token')

            if pairing_code:
                device_by_code = Device.objects.filter(mac_address=pairing_code).first()
                if device_by_code:
                    device_by_code.is_online = True
                    device_by_code.save(update_fields=['is_online'])
                    return JsonResponse({
                        "status": "ok",
                        "action": "update",
                        "plant_id": device_by_code.plant_id,
                        "device_token": device_by_code.device_token,
                        "is_online": True
                    }, status=200)

            device = Device.objects.filter(plant_id=plant_id, device_token=device_token).first()
            if device:
                device.is_online = True
                device.save(update_fields=['is_online'])
                return JsonResponse({
                    "status": "ok",
                    "action": "none",
                    "plant_id": device.plant_id,
                    "device_token": device.device_token,
                    "is_online": True
                }, status=200)

            if pairing_code and not device_token:
                return JsonResponse({
                    "status": "waiting_for_pairing",
                    "action": "none",
                    "message": "Waiting for user to enter code in Web App"
                }, status=200)

            return JsonResponse({
                "status": "error",
                "action": "reset_device",
                "message": "Device deleted from server."
            }, status=404)

        except Exception as e:
            return JsonResponse({"status": "error", "error": str(e)}, status=400)

    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)


@csrf_exempt
def device_pair(request):
    if request.method != 'POST':
        return JsonResponse({"success": False, "error": "Invalid request method"}, status=405)
    
    try:
        data = json.loads(request.body or "{}")
        pairing_code = data.get('mac_address') or data.get('pairing_code') or data.get('code')
        
        if not pairing_code:
            return JsonResponse({"success": False, "error": "Pairing code missing"}, status=400)

        device = Device.objects.filter(mac_address=pairing_code).first()

        if not device:
            new_plant_id = f"plant_{pairing_code.lower()}"
            new_token = str(uuid.uuid4())
            device = Device.objects.create(
                mac_address=pairing_code,
                plant_id=new_plant_id,
                device_token=new_token,
                is_paired=True,
                is_online=True
            )
        else:
            device.is_paired = True
            device.is_online = True
            device.save(update_fields=['is_paired', 'is_online'])

        return JsonResponse({
            "success": True,
            "plant_id": device.plant_id,
            "device_token": device.device_token,
            "is_paired": device.is_paired
        })
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@csrf_exempt
def check_pairing(request):
    mac_address = request.GET.get('mac') or request.GET.get('code')
    if not mac_address:
        return JsonResponse({"is_paired": False, "error": "MAC/Code missing"}, status=400)
    
    try:
        device = Device.objects.get(mac_address=mac_address)
        return JsonResponse({
            "is_paired": device.is_paired,
            "plant_id": device.plant_id,
            "device_token": device.device_token
        })
    except Device.DoesNotExist:
        return JsonResponse({"is_paired": False}, status=404)


@csrf_exempt
def device_command(request, plant_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid Method"}, status=405)

    try:
        data = json.loads(request.body or "{}")

        if data.get("type") == "ai":
            user_text = (data.get("text") or data.get("message") or "").strip()

            if user_text:
                kb_context, kb_matches = get_kb_context_direct(user_text, limit=5)

                if kb_matches:
                    kb_answer = build_kb_answer(user_text, kb_matches)
                    data["rag_context"] = kb_answer or kb_context[:500]
                    data["kb_source"] = kb_matches[0]["document"]
                else:
                    try:
                        client = get_openai_client()
                        if not client:
                            raise RuntimeError("OPENAI_API_KEY is not configured.")

                        system_instruction = (
                            "Aap 'Pratham' hain, ek smart assistant hain. "
                            "Jawab hamesha chhota, seedha aur crisp Hindi/Hinglish mein dein jo OLED screen par fit ho sake."
                        )

                        chat_response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[
                                {"role": "system", "content": system_instruction},
                                {"role": "user", "content": user_text},
                            ],
                            max_tokens=40,
                        )
                        
                        ai_reply = chat_response.choices[0].message.content.strip()
                        data["rag_context"] = ai_reply

                    except Exception as ai_err:
                        data["rag_context"] = f"AI Error: {str(ai_err)}"

        topic = f"pratham/plant/{plant_id}/commands"
        payload = json.dumps(data, ensure_ascii=False)

        publish.single(
            topic,
            payload,
            hostname=MQTT_BROKER,
            port=MQTT_PORT,
            qos=1
        )

        return JsonResponse({
            "status": "success",
            "message": "Command published to MQTT",
            "data": data
        })

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


def plant_ai_config_view(request, plant_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)
        
    try:
        data = json.loads(request.body)
        model_name = data.get("model")
        api_token = data.get("api_token")
        agent_name = data.get("agent_name", "My Plant Agent")
        
        if not model_name or not api_token:
            return JsonResponse({"status": "error", "message": "Model and token are required"}, status=400)
        
        device, created = Device.objects.get_or_create(plant_id=plant_id, defaults={"device_token": "default_token"})
        agent, _ = AIAgent.objects.update_or_create(
            user=None, 
            defaults={"name": agent_name, "ai_model_name": model_name, "api_token": api_token}
        )
        device.agent = agent
        device.save()
        return JsonResponse({"status": "success", "message": "Model configured successfully!"}, status=200)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@csrf_exempt
def admin_manage_kb_api(request):
    if not is_admin(request.user):
        return JsonResponse({"status": "error", "message": "Admin privileges required"}, status=403)

    if request.method == "GET":
        kbs = KnowledgeBase.objects.all().prefetch_related('documents')
        kb_data = []
        for kb in kbs:
            kb_data.append({
                "id": kb.id,
                "name": kb.name,
                "description": kb.description,
                "status": getattr(kb, 'status', 'Enabled'),
                "documents_count": kb.documents.count(),
                "created_at": kb.created_at.strftime("%Y-%m-%d %H:%M:%S")
            })
        return JsonResponse({"status": "success", "knowledge_bases": kb_data})

    elif request.method == "POST":
        try:
            body = json.loads(request.body or "{}")
            action = body.get("action", "create")

            if action == "create":
                name = body.get("name")
                description = body.get("description", "")
                if not name:
                    return JsonResponse({"status": "error", "message": "Knowledge Base name required"}, status=400)
                
                kb = KnowledgeBase.objects.create(name=name, description=description)
                return JsonResponse({"status": "success", "message": "Knowledge Base created", "kb_id": kb.id}, status=201)

            elif action == "assign_agent":
                plant_id = body.get("plant_id")
                agent_id = body.get("agent_id")

                device = Device.objects.get(plant_id=plant_id)
                agent = AIAgent.objects.get(id=agent_id)
                device.agent = agent
                device.save()

                return JsonResponse({"status": "success", "message": f"Agent {agent.name} assigned to {plant_id}"})

        except Device.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Device not found"}, status=404)
        except AIAgent.DoesNotExist:
            return JsonResponse({"status": "error", "message": "AI Agent not found"}, status=404)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)


@csrf_exempt
def knowledge_base_api(request):
    def get_kb_list_json():
        kbs = KnowledgeBase.objects.all().prefetch_related('documents__chunks')
        data = []
        for kb in kbs:
            docs = []
            for d in kb.documents.all():
                c_count = get_document_chunks_count(d)
                docs.append({
                    "id": d.id,
                    "name": d.name,
                    "size": getattr(d, 'file_size', '0 KB'),
                    "status": getattr(d, 'status', 'Parsed'),
                    "chunks": c_count,
                    "chunks_count": c_count,
                    "date": d.created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(d, 'created_at') and d.created_at else ""
                })
            
            data.append({
                "id": kb.id,
                "name": kb.name,
                "desc": kb.description,
                "status": getattr(kb, 'status', 'Enabled'),
                "docsCount": len(docs),
                "createdAt": kb.created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(kb, 'created_at') and kb.created_at else "",
                "documents": docs
            })
        return JsonResponse({
            "status": "success", 
            "data": data, 
            "knowledge_bases": data, 
            "results": data, 
            "items": data
        })

    if request.method == "GET":
        return get_kb_list_json()

    elif request.method == "POST":
        try:
            if request.FILES or request.POST.get("action") == "upload_doc":
                kb_id = request.POST.get("kb_id")
                kb = None
                try:
                    if kb_id and str(kb_id).isdigit():
                        kb = KnowledgeBase.objects.filter(id=kb_id).first()
                    if not kb and kb_id:
                        kb = KnowledgeBase.objects.filter(name__iexact=str(kb_id)).first()
                except Exception:
                    kb = None

                if not kb:
                    kb = KnowledgeBase.objects.first()
                    if not kb:
                        kb = KnowledgeBase.objects.create(name="General Knowledge Base", description="Auto-created KB")
                
                uploaded_file = request.FILES.get("file")
                name = request.POST.get("name") or request.POST.get("title")
                content = request.POST.get("content", "")

                if uploaded_file:
                    if not name:
                        name = uploaded_file.name
                    
                    file_extension = os.path.splitext(name)[1].lower()
                    try:
                        if file_extension == '.pdf':
                            reader = PdfReader(uploaded_file)
                            extracted_text = [page.extract_text() for page in reader.pages if page.extract_text()]
                            content = "\n".join(extracted_text)
                            
                        elif file_extension in ['.docx', '.doc']:
                            doc_file = DocxDocument(uploaded_file)
                            extracted_text = [p.text for p in doc_file.paragraphs if p.text.strip()]
                            content = "\n".join(extracted_text)
                            
                        else:
                            file_bytes = uploaded_file.read()
                            try:
                                content = file_bytes.decode('utf-8')
                            except UnicodeDecodeError:
                                content = file_bytes.decode('latin-1', errors='ignore')
                    except Exception as e:
                        content = f"Error reading file content: {str(e)}"

                if not content.strip():
                    return JsonResponse({"status": "error", "message": "File content is empty or could not be read"}, status=400)

                size_kb = f"{len(content.encode('utf-8')) / 1024:.2f} KB"
                
                doc = Document.objects.create(
                    knowledge_base=kb,
                    name=name or "Untitled Document",
                    content=content,
                    file_size=size_kb,
                    status="Parsed"
                )

                DocumentChunk.objects.filter(document=doc).delete()
                
                chunk_size = 300
                chunks_count = 0
                for i in range(0, len(content), chunk_size):
                    chunk_text = content[i:i+chunk_size]
                    if chunk_text.strip():
                        DocumentChunk.objects.create(
                            document=doc,
                            chunk_text=chunk_text,
                            chunk_index=chunks_count + 1
                        )
                        chunks_count += 1

                return JsonResponse({
                    "status": "success", 
                    "doc_id": doc.id, 
                    "chunks_count": chunks_count,
                    "message": "Document uploaded and auto-chunked successfully into Knowledge Base!"
                })

            if not request.body:
                return JsonResponse({"status": "success", "message": "Ignored empty request"})
                
            body = json.loads(request.body)
            action = body.get("action")

            if not action:
                if "content" in body or "kb_id" in body:
                    action = "upload_doc"
                elif "name" in body or "title" in body or "kb_name" in body:
                    action = "create_kb"
                else:
                    action = "list_kb"

            if action == "delete_kb":
                kb_id = body.get("kb_id")
                try:
                    kb = KnowledgeBase.objects.get(id=kb_id)
                    kb.delete()
                    return JsonResponse({"status": "success", "message": "Knowledge Base deleted successfully!"})
                except KnowledgeBase.DoesNotExist:
                    return JsonResponse({"status": "error", "message": "Knowledge Base not found"}, status=404)

            elif action in ["create_kb", "create_knowledge_base", "new_kb"]:
                name = body.get("name") or body.get("title") or body.get("kb_name")
                desc = body.get("desc") or body.get("description", "")
                if not name:
                    return JsonResponse({"status": "error", "message": "Knowledge Base name is required"}, status=400)
                kb = KnowledgeBase.objects.create(name=name, description=desc)
                return JsonResponse({"status": "success", "id": kb.id, "message": "Knowledge Base created successfully!"})

            elif action == "list_docs":
                kb_id = body.get("kb_id")
                try:
                    kb = KnowledgeBase.objects.get(id=kb_id)
                    docs = []
                    for d in kb.documents.all():
                        c_count = get_document_chunks_count(d)
                        docs.append({
                            "id": d.id,
                            "name": d.name,
                            "size": getattr(d, 'file_size', '0 KB'),
                            "status": getattr(d, 'status', 'Parsed'),
                            "chunks": c_count,
                            "chunks_count": c_count,
                            "date": d.created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(d, 'created_at') and d.created_at else ""
                        })
                    return JsonResponse({"status": "success", "documents": docs, "data": docs, "items": docs})
                except KnowledgeBase.DoesNotExist:
                    return JsonResponse({"status": "error", "message": "Knowledge Base not found"}, status=404)

            elif action in ["delete_document", "del_doc", "delete_doc"]:
                doc_id = body.get("doc_id") or body.get("document_id")
                if not doc_id:
                    return JsonResponse({"status": "error", "message": "Document ID is required for deletion"}, status=400)
                try:
                    doc = Document.objects.get(id=doc_id)
                    doc.delete()
                    return JsonResponse({"status": "success", "message": "Document deleted successfully!"})
                except Document.DoesNotExist:
                    return JsonResponse({"status": "error", "message": "Document not found"}, status=404)

            else:
                return get_kb_list_json()

        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid JSON format"}, status=400)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

    return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)


@csrf_exempt
def rag_search_api(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)

    try:
        body = json.loads(request.body or "{}")
        query = (body.get("query") or body.get("text") or "").strip()

        if not query:
            return JsonResponse({"status": "error", "message": "Query is required"}, status=400)

        matches = find_kb_matches(query, limit=5)

        results = [{
            "document": match["document"],
            "knowledge_base": match["knowledge_base"],
            "chunk_index": match["chunk_index"],
            "score": match["score"],
            "text": match["text"]
        } for match in matches]

        return JsonResponse({
            "status": "success",
            "query": query,
            "matches_count": len(results),
            "context_chunks": results
        })

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


def view_document_chunks(request, doc_id):
    try:
        doc = Document.objects.get(id=doc_id)
        chunks = doc.chunks.all().order_by('chunk_index') if hasattr(doc, 'chunks') else doc.documentchunk_set.all().order_by('chunk_index')
        
        context = {
            'document': doc,
            'chunks': chunks,
            'total_chunks': chunks.count()
        }
        return render(request, 'chunks.html', context)
    except Document.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Document not found"}, status=404)


@csrf_exempt
def update_chunk_api(request, chunk_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)
        
    try:
        body = json.loads(request.body)
        new_text = body.get("chunk_text")
        if not new_text:
            return JsonResponse({"status": "error", "message": "Chunk text cannot be empty"}, status=400)
        chunk = DocumentChunk.objects.get(id=chunk_id)
        chunk.chunk_text = new_text
        chunk.save()
        return JsonResponse({"status": "success", "message": "Chunk updated successfully!"})
    except DocumentChunk.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Chunk not found"}, status=404)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def delete_chunk_api(request, chunk_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)
        
    try:
        chunk = DocumentChunk.objects.get(id=chunk_id)
        chunk.delete()
        return JsonResponse({"status": "success", "message": "Chunk deleted successfully!"})
    except DocumentChunk.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Chunk not found"}, status=404)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def unified_plant_ai_chat_view(request, plant_id):
    if request.method == "GET":
        return JsonResponse({
            "status": "success",
            "plant_id": plant_id,
            "responses": []
        }, status=200)

    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)

    try:
        device = Device.objects.get(plant_id=plant_id)

        body = json.loads(request.body or "{}")
        user_message = (body.get("message") or body.get("text") or "").strip()

        if not user_message:
            return JsonResponse({"status": "error", "message": "Message is required"}, status=400)

        kb_context, kb_matches = get_kb_context_direct(user_message, limit=5)

        ai_text = ""
        ai_expr = "happy"
        source = "ai"

        if kb_matches:
            ai_text = build_kb_answer(user_message, kb_matches)
            if not ai_text:
                ai_text = "Knowledge Base mein data mila."
            source = "knowledge_base"
            
        else:
            agent = getattr(device, 'agent', None)
            
            # Agent missing validation with user-friendly fallback
            if not agent or not agent.api_token:
                ai_text = "Mujhe jawab dene ke liye AI Agent ki API key nahi mili. Kripya Configure MCP me API key set karein."
                ai_expr = "sad"
                source = "system"
            else:
                recent_history = PlantChatHistory.objects.filter(
                    device=device
                ).order_by("-created_at")[:5]

                system_prompt = (
                    PRATHAM_SYSTEM_INSTRUCTION
                    + " Reply strictly in JSON format with keys 'text' and 'expr'."
                )

                messages = [{"role": "system", "content": system_prompt}]

                for h in reversed(list(recent_history)):
                    messages.append({"role": "user", "content": h.user_text})
                    messages.append({"role": "assistant", "content": h.ai_response})

                messages.append({"role": "user", "content": user_message})

                genai.configure(api_key=agent.api_token)

                # Updated default model to gemini-2.5-flash
                model_name = agent.ai_model_name if (agent.ai_model_name and "gemini" in agent.ai_model_name) else "gemini-2.5-flash"
                
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_prompt
                )

                history_text = ""
                for msg in messages[1:-1]:
                    role = "User" if msg["role"] == "user" else "Assistant"
                    history_text += f"{role}: {msg['content']}\n"

                final_prompt = (
                    f"{history_text}\nCurrent User: {user_message}\n\n"
                    "Return ONLY valid JSON like "
                    '{"text":"short answer","expr":"happy"}'
                )

                try:
                    res = model.generate_content(final_prompt)
                    ai_data = parse_ai_json(
                        get_safe_ai_text(res),
                        default_text="AI response unavailable.",
                        default_expr="happy"
                    )

                    ai_text = str(ai_data.get("text") or "Hello").strip()
                    ai_expr = str(ai_data.get("expr") or "happy").strip()
                except Exception as ai_err:
                    print(f"[GEMINI GENERATION ERROR]: {ai_err}")
                    ai_text = "Mujhe samajh nahi aaya, kripya dobara kahein."
                    ai_expr = "sad"

                source = "ai"

        if ai_text:
            save_chat_history_and_device_state(device, user_message, ai_text)

        audio_url = generate_plant_tts(request, plant_id, ai_text, filename_prefix="plant")

        payload = {
            "type": "ai",
            "text": ai_text,
            "expr": ai_expr,
            "audio_url": audio_url,
            "source": source
        }

        try:
            publish.single(
                f"pratham/plant/{plant_id}/commands",
                json.dumps(payload, ensure_ascii=False),
                hostname=MQTT_BROKER,
                port=MQTT_PORT,
                qos=1
            )
        except Exception as mqtt_err:
            print(f"[MQTT PUBLISH ERROR]: {mqtt_err}")

        # Added reply and response keys for direct frontend compatibility
        return JsonResponse({
            "status": "success",
            "reply": ai_text,
            "response": ai_text,
            "expr": ai_expr,
            "ai_command": payload,
            "source": source,
            "kb_match": bool(kb_matches)
        }, status=200)

    except Device.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Device not found"}, status=404)
    except Exception as e:
        print(f"[UNIFIED VIEW CRASH]: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def get_reminders_api(request, plant_id):
    if request.method != "GET":
        return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)
        
    try:
        device = Device.objects.get(plant_id=plant_id)
        reminders = list(Reminder.objects.filter(device=device, is_active=True).values('id', 'time', 'message'))
        return JsonResponse({"status": "success", "reminders": reminders}, status=200)
    except Device.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Device not found"}, status=404)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def set_reminder_api(request, plant_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)
        
    try:
        device = Device.objects.get(plant_id=plant_id)
        
        auth_token = request.headers.get("Authorization") or request.GET.get("token")
        if auth_token and device.device_token and auth_token != device.device_token:
            return JsonResponse({"status": "error", "message": "Unauthorized device token"}, status=403)
            
        body = json.loads(request.body)
        time_str = body.get("time") or body.get("reminder_time")
        message = body.get("message") or body.get("text")
        
        if not time_str or not message:
            return JsonResponse({"status": "error", "message": "Time and message are required"}, status=400)
        
        reminder = Reminder.objects.create(
            device=device,
            time=time_str,
            message=message,
            is_active=True
        )
        
        announcement_text = f"Reminder: {message}"
        speech_audio_url = ""
        try:
            media_root = getattr(settings, 'MEDIA_ROOT', os.path.join(settings.BASE_DIR, 'media'))
            os.makedirs(media_root, exist_ok=True)
            temp_mp3_filename = f"plant_{plant_id}_reminder_temp.mp3"
            temp_mp3_path = os.path.join(media_root, temp_mp3_filename)
            
            tts = gTTS(text=announcement_text, lang='hi', slow=False)
            tts.save(temp_mp3_path)
            
            speech_filename = f"plant_{plant_id}_reminder_speech.wav"
            speech_path = os.path.join(media_root, speech_filename)
            
            sound = AudioSegment.from_mp3(temp_mp3_path)
            sound = sound.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            sound = sound.normalize()
            sound.export(speech_path, format="wav")
            
            if os.path.exists(temp_mp3_path):
                os.remove(temp_mp3_path)
                
            media_url = getattr(settings, 'MEDIA_URL', '/media/')
            speech_audio_url = request.build_absolute_uri(f"{media_url}{speech_filename}")
        except Exception as tts_err:
            print(f"[REMINDER TTS ERROR]: {str(tts_err)}")

        all_reminders = list(Reminder.objects.filter(device=device, is_active=True).values('time', 'message'))
        
        payload = {
            "type": "reminder_alert", 
            "text": announcement_text,
            "expr": "excited",
            "audio_url": speech_audio_url,
            "data": all_reminders
        }
        publish.single(f"pratham/plant/{plant_id}/commands", json.dumps(payload), hostname=MQTT_BROKER, port=MQTT_PORT, qos=1)
        
        return JsonResponse({"status": "success", "message": "Reminder created and announced successfully!", "reminder_id": reminder.id}, status=201)
        
    except Device.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Device not found"}, status=404)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@csrf_exempt
def update_delete_reminder_api(request, plant_id, reminder_id):
    try:
        device = Device.objects.get(plant_id=plant_id)
        reminder = Reminder.objects.get(id=reminder_id, device=device)
    except (Device.DoesNotExist, Reminder.DoesNotExist):
        return JsonResponse({"status": "error", "message": "Device or Reminder not found"}, status=404)

    if request.method == "DELETE":
        reminder.delete()
        all_reminders = list(Reminder.objects.filter(device=device, is_active=True).values('time', 'message'))
        publish.single(f"pratham/plant/{plant_id}/commands", json.dumps({"type": "reminders", "data": all_reminders}), hostname=MQTT_BROKER, port=MQTT_PORT, qos=1)
        return JsonResponse({"status": "success", "message": "Reminder deleted successfully!"})

    elif request.method in ["PUT", "POST"]:
        try:
            body = json.loads(request.body)
            reminder.time = body.get("reminder_time", body.get("time", reminder.time))
            reminder.message = body.get("text", body.get("message", reminder.message))
            if "is_active" in body:
                reminder.is_active = body.get("is_active")
            reminder.save()
            
            all_reminders = list(Reminder.objects.filter(device=device, is_active=True).values('time', 'message'))
            publish.single(f"pratham/plant/{plant_id}/commands", json.dumps({"type": "reminders", "data": all_reminders}), hostname=MQTT_BROKER, port=MQTT_PORT, qos=1)
            return JsonResponse({"status": "success", "message": "Reminder updated successfully!"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

    return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)


def pratham_proxy_api(request, endpoint):
    target_url = f"https://api.mypratham.com/{endpoint}"
    try:
        response = requests.get(target_url, timeout=5)
        if response.status_code == 200:
            return JsonResponse(response.json(), safe=False)
        else:
            return JsonResponse({"status": "error", "message": "Failed to fetch from external API"}, status=response.status_code)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@csrf_exempt
def audio_upload_view(request, plant_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)
        
    try:
        device = Device.objects.get(plant_id=plant_id)

        # 1. RECEIVE RAW AUDIO DATA
        audio_data = request.body
        if not audio_data:
            return JsonResponse({'status': 'error', 'message': 'Audio data is empty'}, status=400)

        media_root = getattr(settings, 'MEDIA_ROOT', None) or os.path.join(settings.BASE_DIR, 'media')
        os.makedirs(media_root, exist_ok=True)

        pcm_filename = f'plant_{plant_id}_upload.pcm'
        pcm_path = os.path.join(media_root, pcm_filename)
        audio_filename = f'plant_{plant_id}_upload.wav'
        audio_path = os.path.join(media_root, audio_filename)

        with open(pcm_path, 'wb+') as destination:
            destination.write(audio_data)

        save_pcm_as_wav(pcm_path, audio_path, sample_rate=16000)

        # 2. SPEECH-TO-TEXT (STT)
        user_text = ""
        if LOCAL_WHISPER_MODEL is not None:
            try:
                stt_result = LOCAL_WHISPER_MODEL.transcribe(
                    audio_path,
                    language='hi', 
                    fp16=False
                )
                user_text = stt_result.get('text', '').strip()
                print(f"[LOCAL WHISPER SUCCESS]: {user_text}")
            except Exception as local_stt_err:
                print(f"[ERROR] Local Whisper Error: {local_stt_err}")

        # Cloud STT Fallback
        if not user_text:
            client = get_openai_client()
            if client:
                try:
                    with open(audio_path, 'rb') as audio_file:
                        transcript = client.audio.transcriptions.create(
                            model='whisper-1', 
                            file=audio_file,
                            language='hi'
                        )
                        user_text = transcript.text.strip()
                except Exception as oai_err:
                    print(f"[ERROR] OpenAI STT Fallback Error: {oai_err}")

        # 3. TEXT CLEANUP & NORMALIZATION
        corrected_text = user_text
        if user_text:
            misheard_patterns = [
                r'बाय\s*पृत्थम', r'बाय\s*प्रथम', r'माई\s*पर्थम', 
                r'माई\s*प्रथम', r'माइ\s*प्रथम', r'माइ\s*पर्थम'
            ]
            for pattern in misheard_patterns:
                corrected_text = re.sub(pattern, 'MyPratham', corrected_text, flags=re.IGNORECASE)

            word_fixes = {
                r'\bpratam\b': 'Pratham',
                r'\bpratham\b': 'Pratham',
                r'\bjike\b': 'GK',
                r'\bjypore\b': 'Jaipur',
                r'\bjeypore\b': 'Jaipur',
                r'\bjepur\b': 'Jaipur',
                r'\bmadhya\s*paradeesh\b': 'Madhya Pradesh',
            }
            for pattern, replacement in word_fixes.items():
                corrected_text = re.sub(pattern, replacement, corrected_text, flags=re.IGNORECASE)

        print(f'STT Text: {user_text} | Corrected: {corrected_text}')

        ai_reply = ""
        source = ""

        # ROUTING LOGIC: IDENTITY -> HIT 1 (KB) -> HIT 2 (AI) -> HIT 3 (WEATHER)
        if corrected_text:
            text_lower = corrected_text.lower().strip()

            # STEP 0: IDENTITY CHECK
            identity_keywords = ['your name', 'who are you', 'tum kaun ho', 'tumhara naam', 'what is your name']
            if any(kw in text_lower for kw in identity_keywords):
                ai_reply = "Mera naam Pratham hai. Main aapka AI assistant hoon."
                source = "bot_identity"

            # HIT 1: KNOWLEDGE BASE
            if not ai_reply and len(text_lower) >= 3:
                assigned_agent = getattr(device, 'agent', None)
                if assigned_agent:
                    kb_list = assigned_agent.knowledge_bases.filter(status="Enabled")
                    matching_chunks = DocumentChunk.objects.filter(
                        document__knowledge_base__in=kb_list,
                        chunk_text__icontains=corrected_text
                    )
                    if matching_chunks.exists():
                        ai_reply = matching_chunks.first().chunk_text[:150]
                        source = "admin_knowledge_base"

                if not ai_reply:
                    kb_context, kb_matches = get_kb_context_direct(corrected_text, limit=5)
                    if kb_matches:
                        kb_ans = build_kb_answer(corrected_text, kb_matches)
                        if kb_ans and kb_ans.strip():
                            ai_reply = kb_ans
                            source = "knowledge_base"
                            print(f"[HIT 1 SUCCESS - KB MATCH]: {ai_reply}")

            # HIT 2: FAST AI CALL
            weather_keywords = ['weather', 'mausam', 'mosam', 'barish', 'baarish', 'temperature', 'taapmaan', 'rain', 'मौसम', 'बारिश', 'तापमान', 'forcasting']
            is_weather_query = any(kw in text_lower for kw in weather_keywords)

            if not ai_reply and not is_weather_query:
                client = get_openai_client()
                if client:
                    try:
                        system_instruction = (
                            "Aap 'Pratham' hain. User ke sawal ka short, crisp aur helpful Hindi/Hinglish reply dein (max 20-30 words)."
                        )
                        chat_response = client.chat.completions.create(
                            model='gpt-4o-mini',
                            messages=[
                                {'role': 'system', 'content': system_instruction},
                                {'role': 'user', 'content': corrected_text},
                            ],
                            max_tokens=45,
                            temperature=0.3
                        )
                        ai_reply = chat_response.choices[0].message.content.strip()
                        source = "ai_agent"
                        print(f"[HIT 2 SUCCESS - AI CALL]: {ai_reply}")
                    except Exception as gpt_err:
                        print(f"[AI CALL ERROR]: {gpt_err}")

            # HIT 3: WEATHER FLOW
            if not ai_reply and is_weather_query:
                known_cities = ['jaipur', 'delhi', 'mumbai', 'kolkata', 'chennai', 'bangalore', 'ahmedabad', 'pune', 'indore', 'bhopal', 'lucknow']
                target_city = None

                for city in known_cities:
                    if city in text_lower:
                        target_city = city.capitalize()
                        break

                if target_city:
                    ai_reply = fetch_realtime_weather(city=target_city)
                    source = "weather_api"
                    print(f"[HIT 3 SUCCESS - WEATHER API for {target_city}]: {ai_reply}")
                else:
                    ai_reply = "Aap kis shehar, nagar ya jagah ka tapmaan aur mausam janna chahte hain?"
                    source = "weather_location_prompt"

        if not ai_reply:
            ai_reply = "Aapki aawaz saaf nahi aayi. Kripya fir se kahein."
            source = "no_input_fallback"

        # 4. UPDATE DEVICE STATE & CHAT HISTORY
        if hasattr(device, 'custom_text'):
            device.custom_text = ai_reply
        if hasattr(device, 'current_expression'):
            device.current_expression = 'happy'
        device.save()

        try:
            PlantChatHistory.objects.create(
                device=device,
                user_text=corrected_text or user_text or "No speech detected",
                ai_response=ai_reply
            )
        except Exception as history_err:
            print(f"[HISTORY SAVE ERROR]: {history_err}")

        # 5. GENERATE TTS AUDIO
        speech_audio_url = ""
        try:
            temp_mp3_filename = f"plant_{plant_id}_temp.mp3"
            temp_mp3_path = os.path.join(media_root, temp_mp3_filename)
            
            tts = gTTS(text=ai_reply, lang='hi', slow=False)
            tts.save(temp_mp3_path)
            
            speech_filename = f"plant_{plant_id}_reply_speech.wav"
            speech_path = os.path.join(media_root, speech_filename)
            
            sound = AudioSegment.from_mp3(temp_mp3_path)
            sound = sound.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            sound = sound.normalize()
            sound = sound + 14
            sound.export(speech_path, format="wav")
            
            if os.path.exists(temp_mp3_path):
                os.remove(temp_mp3_path)
                
            media_url = getattr(settings, 'MEDIA_URL', '/media/')
            speech_audio_url = request.build_absolute_uri(f"{media_url}{speech_filename}")
            
        except Exception as tts_err:
            print(f"[TTS GENERATION ERROR]: {tts_err}")

        # 6. MQTT PUBLISH
        try:
            payload = {
                "type": "ai",
                "text": ai_reply,
                "expr": "happy",
                "audio_url": speech_audio_url,
                "source": source
            }

            publish.single(
                f"pratham/plant/{plant_id}/commands",
                json.dumps(payload, ensure_ascii=False),
                hostname=MQTT_BROKER,
                port=MQTT_PORT,
                qos=1
            )
        except Exception as mqtt_err:
            print(f"[MQTT PUBLISH ERROR]: {mqtt_err}")

        return JsonResponse({
            'status': 'success',
            'source': source,
            'user_text': user_text,
            'corrected_text': corrected_text,
            'ai_response': ai_reply,
            'speech_audio_url': speech_audio_url,
        }, status=200)

    except Device.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Device not found'}, status=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
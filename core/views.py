import json
import os
import requests
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.db import models
from django.db.models import Q
import paho.mqtt.publish as publish
import google.generativeai as genai
from openai import OpenAI
from gtts import gTTS
from django.conf import settings
from .rag_service import get_rag_context
from pypdf import PdfReader
from docx import Document as DocxDocument
import wave

# Models import (Yahan PlantChatHistory bhi add kiya gaya hai)
from .models import Device, AIAgent, KnowledgeBase, Document, DocumentChunk, Reminder, PlantChatHistory

from pydub import AudioSegment
# 👇 FFmpeg ke bin folder ko system PATH mein dynamically add kar rahe hain taaki pydub ko koi error na aaye
ffmpeg_bin_path = r"C:\ffmpeg-2026-09-14-git-6efe500d2e-essentials_build\bin"
if ffm_path := ffmpeg_bin_path:
    if ffm_path not in os.environ["PATH"]:
        os.environ["PATH"] += os.pathsep + ffm_path

# MQTT Config
MQTT_BROKER = "192.168.1.8"
MQTT_PORT = 1883

# ==========================================
# CENTRALIZED UNIFIED SYSTEM INSTRUCTION
# ==========================================
PRATHAM_SYSTEM_INSTRUCTION = (
    "Aap 'Pratham' hain, ek smart intelligent assistant aur smart pratham helper. "
    "Aapko user ke har sawal ka jawab Hindi (Hinglish ya शुद्ध हिंदी जैसा user pooche) mein "
    "bohot hi saaf, madadgar aur thoda friendly tarike se dena hai. "
    "Agar koi GK (General Knowledge) ya quiz chale, toh user ke jawab ko evaluate karke agla sawal puchein. "
    "OLED screen ke liye jawab hamesha chhota, seedha aur crisp hona chahiye."
)



# ==========================================
# KNOWLEDGE BASE / RAG HELPERS
# ==========================================
# IMPORTANT:
# The KB must be checked BEFORE any AI provider is called.
# We do local retrieval here instead of depending only on rag_service.py.
# This also handles Hindi speech such as "इंडिया जीके" against a document
# named "India_GK_Facts.txt".

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

def _rag_normalize(value):
    """Normalize Hindi/English text for reliable KB matching."""
    if value is None:
        return ""
    import re
    value = str(value)
    value = value.replace("_", " ").replace("-", " ").replace("/", " ")
    value = value.casefold()
    value = value.replace("’", "'").replace("–", " ").replace("—", " ")
    # Remove punctuation but keep Unicode letters/digits/spaces.
    value = re.sub(r"[^\w\s\u0900-\u097F]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _rag_query_terms(query):
    """Return useful English/Hindi-normalized search terms."""
    import re
    normalized = _rag_normalize(query)
    if not normalized:
        return []

    terms = []
    # First add aliases for multi-word/specific Hindi phrases.
    for source, target in sorted(RAG_HINDI_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if source in normalized:
            terms.append(target)

    # Then add original words of reasonable length.
    for word in re.findall(r"[\w\u0900-\u097F]+", normalized, flags=re.UNICODE):
        if len(word) >= 2 and word not in terms:
            terms.append(word)

    # Common conversational words should not decide a KB match.
    stop_words = {
        "hai", "hain", "ho", "kya", "ka", "ke", "ki", "ko", "me", "mein",
        "mujhe", "batao", "bata", "please", "the", "is", "a", "an", "of",
        "what", "tell", "about", "can", "you", "do", "how", "much", "karo",
        "chahiye", "karo", "kya", "mujhko", "mujhe", "ye", "yah", "vo", "woh",
        "का", "के", "की", "है", "हैं", "में", "को", "क्या", "बताओ", "मुझे",
    }
    return [t for t in terms if t not in stop_words]


def find_kb_matches(query, limit=5):
    """
    Deterministic KB retrieval with optimized weights.
    Chunk content matching is prioritized higher than document titles.
    """
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
            chunk_text = _rag_normalize(getattr(chunk, "chunk_text", ""))
            document = getattr(chunk, "document", None)
            doc_name = _rag_normalize(getattr(document, "name", ""))
            kb = getattr(document, "knowledge_base", None)
            kb_name = _rag_normalize(getattr(kb, "name", ""))

            searchable = f"{chunk_text} {doc_name} {kb_name}".strip()
            if not searchable:
                continue

            score = 0
            matched = set()

            # Exact full-query match inside chunk content gets highest priority
            if normalized_query and normalized_query in chunk_text:
                score += 150
            elif normalized_query and normalized_query in searchable:
                score += 80

            # Score terms separately with balanced weights (Chunk content prioritized)
            for term in terms:
                term_score = 0
                if term in chunk_text:
                    term_score += 40  # Chunk text match weight increased for accuracy
                    matched.add(term)
                if term in doc_name:
                    term_score += 15  # Doc name weight balanced
                    matched.add(term)
                if term in kb_name:
                    term_score += 15  # KB name weight balanced
                    matched.add(term)
                score += term_score

            # Require at least one meaningful match.
            if matched:
                score += len(matched) * 10
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
    """Return top KB context and match metadata."""
    matches = find_kb_matches(query, limit=limit)
    if not matches:
        return "", []
    context = "\n\n".join(
        f"[{m['document']} | Chunk {m['chunk_index']}]\n{m['text']}"
        for m in matches
    )
    return context, matches


def build_kb_answer(query, matches, max_chars=180):
    """
    Build a short answer directly from retrieved KB content.
    No Gemini/OpenAI call is made when KB retrieval succeeds.
    """
    if not matches:
        return ""

    import re
    terms = _rag_query_terms(query)
    candidates = []

    for match in matches:
        text = " ".join(str(match.get("text", "")).split())
        if not text:
            continue

        # Split on common sentence boundaries.
        parts = re.split(r"(?<=[.!?।])\s+|\n+", text)
        for part in parts:
            part = part.strip(" -•\t")
            if not part:
                continue

            p_norm = _rag_normalize(part)
            hit_count = sum(1 for term in terms if term in p_norm)
            sentence_score = hit_count * 20 + min(len(part), 180) / 1000
            candidates.append((sentence_score, part))

    if candidates:
        candidates.sort(key=lambda x: -x[0])
        answer = candidates[0][1]
    else:
        answer = " ".join(str(matches[0]["text"]).split())

    if len(answer) > max_chars:
        answer = answer[:max_chars].rsplit(" ", 1)[0].strip()
        if not answer:
            answer = answer[:max_chars].strip()
        answer += "…"

    return answer


def get_safe_ai_text(response, default="Hello"):
    """Safely extract model text."""
    try:
        text = getattr(response, "text", "") or ""
        return text.strip() or default
    except Exception:
        return default


def parse_ai_json(text, default_text="Hello", default_expr="happy"):
    """Parse JSON returned by an AI model without crashing on markdown fences."""
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
    """Generate MP3 TTS and return absolute media URL."""
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
    """Keep existing chat-history/device-state logic in one safe helper."""
    try:
        PlantChatHistory.objects.create(
            device=device,
            user_text=user_text,
            ai_response=ai_reply
        )
    except Exception as exc:
        print(f"[CHAT HISTORY SAVE ERROR]: {exc}")

    try:
        if hasattr(device, "custom_text"):
            device.custom_text = ai_reply
        if hasattr(device, "current_expression"):
            device.current_expression = "happy"
        device.save()
    except Exception as exc:
        print(f"[DEVICE STATE SAVE ERROR]: {exc}")


def get_document_chunks_count(d):
    """Safe method to count document chunks without returning 0 if chunks exist"""
    try:
        if hasattr(d, 'chunks'):
            return d.chunks.count()
        elif hasattr(d, 'documentchunk_set'):
            return d.documentchunk_set.count()
        else:
            return DocumentChunk.objects.filter(document=d).count()
    except Exception:
        return DocumentChunk.objects.filter(document=d).count()


def dashboard(request):
    return render(request, "index.html")


@csrf_exempt
def device_heartbeat(request, plant_id):
    Device.objects.filter(plant_id=plant_id).update(is_online=True)
    return JsonResponse(
        {"status": "ok", "plant_id": plant_id, "is_online": True}
    )


@csrf_exempt
def device_command(request, plant_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid Method"}, status=405)

    try:
        data = json.loads(request.body or "{}")

        if data.get("type") == "ai":
            user_text = (data.get("text") or data.get("message") or "").strip()

            if user_text:
                # 🛑 Greeting ya 3 characters se chote words ke liye KB search skip karein
                skip_kb = len(user_text) <= 3 or user_text.lower() in ["hi", "hello", "hey", "hii", "hlo"]
                kb_context, kb_matches = ("", []) if skip_kb else get_kb_context_direct(user_text, limit=5)

                if kb_matches:
                    kb_answer = build_kb_answer(user_text, kb_matches)
                    data["rag_context"] = kb_answer or kb_context[:500]
                    data["kb_source"] = kb_matches[0]["document"]

                    print(
                        f"[PRIORITY 1 HIT 🧠] Query: {user_text!r} -> "
                        f"{kb_matches[0]['document']} | "
                        f"KB answer generated locally. AI provider NOT called."
                    )
                else:
                    print(
                        f"[PRIORITY 1 MISS] Query: {user_text!r} -> "
                        f"Knowledge Base match nahi mila ya skip hua. Gemini fallback."
                    )

                    try:
                        device = Device.objects.filter(plant_id=plant_id).first()
                        token = None

                        if device and device.agent and device.agent.api_token:
                            token = device.agent.api_token
                        else:
                            token = "AQ.Ab8RN6KcABxL6w4dkbqbZcR-u8b42tYTOKyqDD7XgwvnewOllA"

                        if token:
                            genai.configure(api_key=token)

                            model_name = (
                                getattr(getattr(device, "agent", None), "ai_model_name", None)
                                or "gemini-3.5-flash"
                            )

                            model = genai.GenerativeModel(
                                model_name=model_name,
                                system_instruction=PRATHAM_SYSTEM_INSTRUCTION
                            )

                            prompt = (
                                f"User ne pucha hai: '{user_text}'. "
                                "Iska ek chhota, seedha aur useful jawab do jo OLED screen par fit ho sake."
                            )

                            res = model.generate_content(prompt)
                            data["rag_context"] = get_safe_ai_text(res, "Hello! Main Pratham hoon, aapki kya madad karoon?")
                        else:
                            data["rag_context"] = "Hello! Main Pratham hoon."

                    except Exception as ai_err:
                        print(f"[DEVICE COMMAND GEMINI ERROR]: {str(ai_err)}")
                        data["rag_context"] = "Hello! Aapne yaad kiya, boliye kya sunna chahenge?"

        topic = f"pratham/plant/{plant_id}/commands"
        payload = json.dumps(data, ensure_ascii=False)

        try:
            publish.single(
                topic,
                payload,
                hostname=MQTT_BROKER,
                port=MQTT_PORT,
                qos=2
            )
        except Exception as mqtt_err:
            print(f"[MQTT PUBLISH ERROR]: {mqtt_err}")
            # Agar MQTT fail bhi ho jaye, tab bhi app crash na ho, 
            # aap chahein toh ise hata sakte hain agar MQTT zaroori hai.

        return JsonResponse({
            "status": "success",
            "message": "Command published to MQTT",
            "data": data
        })

    except Exception as e:
        # 👇 Yeh print batayega ki 400 error exactly kyu aa raha hai
        print(f"[CRITICAL DEVICE COMMAND 400 ERROR]: {str(e)}")
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
                    "size": d.file_size,
                    "status": d.status,
                    "chunks": c_count,
                    "chunks_count": c_count,
                    "date": d.created_at.strftime("%Y-%m-%d %H:%M:%S")
                })
            
            data.append({
                "id": kb.id,
                "name": kb.name,
                "desc": kb.description,
                "status": kb.status,
                "docsCount": len(docs),
                "createdAt": kb.created_at.strftime("%Y-%m-%d %H:%M:%S"),
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
                            extracted_text = []
                            for page in reader.pages:
                                page_text = page.extract_text()
                                if page_text:
                                    extracted_text.append(page_text)
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
                            "size": d.file_size,
                            "status": d.status,
                            "chunks": c_count,
                            "chunks_count": c_count,
                            "date": d.created_at.strftime("%Y-%m-%d %H:%M:%S")
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
        return JsonResponse({
            "status": "error",
            "message": "Invalid method"
        }, status=405)

    try:
        body = json.loads(request.body or "{}")
        query = (body.get("query") or body.get("text") or "").strip()

        if not query:
            return JsonResponse({
                "status": "error",
                "message": "Query is required"
            }, status=400)

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
        print(f"[RAG SEARCH ERROR]: {e}")
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=400)


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
            return JsonResponse({
                "status": "error",
                "message": "Message is required"
            }, status=400)

        # 🛑 FIXED: Greeting / Short messages ke liye KB search skip karein
        skip_kb = len(user_message) <= 3 or user_message.lower() in ["hi", "hello", "hey", "hii", "hlo"]
        kb_context, kb_matches = ("", []) if skip_kb else get_kb_context_direct(user_message, limit=5)

        ai_text = ""
        ai_expr = "happy"
        source = "ai"

        if kb_matches:
            ai_text = build_kb_answer(user_message, kb_matches)

            if not ai_text:
                ai_text = "Knowledge Base mein data mila."

            source = "knowledge_base"

            print(
                f"[PRIORITY 1 HIT 🧠] Chat: {user_message!r} -> "
                f"{kb_matches[0]['document']} | AI provider NOT called."
            )
            print(f"[KB ANSWER]: {ai_text}")

        else:
            print(
                f"[PRIORITY 1 MISS] Chat: {user_message!r} -> "
                "Knowledge Base mein match nahi mila ya skip kiya gaya."
            )

            agent = device.agent
            if not agent or not agent.api_token:
                return JsonResponse({
                    "status": "error",
                    "message": "No AI Agent configured and no Knowledge Base match found."
                }, status=400)

            recent_history = PlantChatHistory.objects.filter(
                device=device
            ).order_by("-created_at")[:5]

            system_prompt = (
                PRATHAM_SYSTEM_INSTRUCTION
                + " Reply strictly in JSON format with keys 'text' and 'expr'."
            )

            messages = [{
                "role": "system",
                "content": system_prompt
            }]

            for h in reversed(list(recent_history)):
                messages.append({
                    "role": "user",
                    "content": h.user_text
                })
                messages.append({
                    "role": "assistant",
                    "content": h.ai_response
                })

            messages.append({
                "role": "user",
                "content": user_message
            })

            genai.configure(api_key=agent.api_token)

            model_name = agent.ai_model_name or "gemini-3.5-flash"
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

            res = model.generate_content(final_prompt)
            ai_data = parse_ai_json(
                get_safe_ai_text(res),
                default_text="AI response unavailable.",
                default_expr="happy"
            )

            ai_text = str(ai_data.get("text") or "Hello").strip()
            ai_expr = str(ai_data.get("expr") or "happy").strip()

            source = "ai"
            print(f"[PRIORITY 3 AI] AI Response: {ai_text}")

        save_chat_history_and_device_state(
            device,
            user_message,
            ai_text
        )

        audio_url = generate_plant_tts(
            request,
            plant_id,
            ai_text,
            filename_prefix="plant"
        )

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
                qos=1,
                timeout=4  # 👈 Timeout ko 2 se badhakar 4 seconds karein
            )
        except Exception as mqtt_err:
            print(f"[CHAT MQTT PUBLISH ERROR]: {mqtt_err}")
            # Agar MQTT fail bhi ho jaye, toh bhi HTTP success return karein taaki frontend par chat na ruke

        return JsonResponse({
            "status": "success",
            "ai_command": payload,
            "source": source,
            "kb_match": bool(kb_matches)
        }, status=200)

    except Device.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "message": "Device not found"
        }, status=404)

    except Exception as e:
        print(f"[UNIFIED AI CHAT ERROR]: {e}")
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)


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
    if request.method != "POST":
        return JsonResponse({
            "status": "error",
            "message": "Invalid method"
        }, status=405)

    try:
        device = Device.objects.get(plant_id=plant_id)

        audio_data = request.body

        if not audio_data:
            return JsonResponse({
                "status": "error",
                "message": "Audio data is empty"
            }, status=400)

        media_root = getattr(
            settings,
            "MEDIA_ROOT",
            None
        ) or os.path.join(settings.BASE_DIR, "media")

        os.makedirs(media_root, exist_ok=True)

        pcm_filename = f"plant_{plant_id}_upload.pcm"
        pcm_path = os.path.join(media_root, pcm_filename)

        audio_filename = f"plant_{plant_id}_upload.wav"
        audio_path = os.path.join(media_root, audio_filename)

        with open(pcm_path, "wb") as destination:
            destination.write(audio_data)

        save_pcm_as_wav(
            pcm_path,
            audio_path,
            sample_rate=16000
        )

        user_text = "Audio received"
        ai_reply = "Hello from AI!"
        ai_expr = "happy"
        is_from_cache = False
        source = "ai"

        try:
            openai_key = getattr(settings, "OPENAI_API_KEY", "")
            if not openai_key:
                raise RuntimeError("OPENAI_API_KEY is not configured.")

            client = OpenAI(api_key=openai_key)

            with open(audio_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="hi"
                )

            user_text = (transcript.text or "").strip()

            print(f"[STT User Text]: {user_text!r}")

            if not user_text:
                raise ValueError("STT returned empty text.")

            kb_context, kb_matches = get_kb_context_direct(
                user_text,
                limit=5
            )

            if kb_matches:
                ai_reply = build_kb_answer(
                    user_text,
                    kb_matches,
                    max_chars=180
                ) or "Knowledge Base mein data mila."

                source = "knowledge_base"

                print(
                    f"[PRIORITY 1 HIT 🧠] Knowledge Base match: "
                    f"{kb_matches[0]['document']} | "
                    f"Chunk: {kb_matches[0]['chunk_index']}"
                )
                print(
                    "[RAG] KB answer returned directly. "
                    "OpenAI Chat Completion NOT called."
                )
                print(f"[AI Response (KB / Processed)]: {ai_reply}")

            else:
                print(
                    "[PRIORITY 1 MISS] Knowledge Base mein match nahi mila, "
                    "context memory aur OpenAI par move kar rahe hain."
                )

                recent_history = PlantChatHistory.objects.filter(
                    device=device
                ).order_by("-created_at")[:5]

                system_instruction = (
                    PRATHAM_SYSTEM_INSTRUCTION
                    + " Keep your responses short and suitable for an OLED screen."
                )

                messages = [{
                    "role": "system",
                    "content": system_instruction
                }]

                for h in reversed(list(recent_history)):
                    messages.append({
                        "role": "user",
                        "content": h.user_text
                    })
                    messages.append({
                        "role": "assistant",
                        "content": h.ai_response
                    })

                messages.append({
                    "role": "user",
                    "content": user_text
                })

                chat_response = client.chat.completions.create(
                    model=getattr(settings, "OPENAI_CHAT_MODEL", "gpt-3.5-turbo"),
                    messages=messages,
                    max_tokens=60,
                )

                ai_reply = (
                    chat_response.choices[0].message.content or "Hello"
                ).strip()

                source = "openai"

                print(f"[AI Response (Real-time / Processed)]: {ai_reply}")

            save_chat_history_and_device_state(
                device,
                user_text,
                ai_reply
            )

        except Exception as ai_err:
            print(f"[AI Integration Error]: {ai_err}")

            if not ai_reply or ai_reply == "Hello from AI!":
                ai_reply = "AI response unavailable."

        speech_audio_url = ""

        try:
            temp_mp3_filename = f"plant_{plant_id}_temp.mp3"
            temp_mp3_path = os.path.join(
                media_root,
                temp_mp3_filename
            )

            tts = gTTS(
                text=ai_reply,
                lang="hi",
                slow=False
            )
            tts.save(temp_mp3_path)

            speech_filename = f"plant_{plant_id}_reply_speech.wav"
            speech_path = os.path.join(
                media_root,
                speech_filename
            )

            sound = AudioSegment.from_mp3(temp_mp3_path)
            sound = sound.set_frame_rate(16000)
            sound = sound.set_channels(1)
            sound = sound.set_sample_width(2)
            sound = sound.normalize()
            sound = sound + 9
            sound.export(speech_path, format="wav")

            if os.path.exists(temp_mp3_path):
                os.remove(temp_mp3_path)

            media_url = getattr(
                settings,
                "MEDIA_URL",
                "/media/"
            )

            speech_audio_url = request.build_absolute_uri(
                f"{media_url}{speech_filename}"
            )

        except Exception as tts_err:
            print(f"[AUDIO UPLOAD TTS ERROR]: {str(tts_err)}")

        media_url = getattr(
            settings,
            "MEDIA_URL",
            "/media/"
        )

        audio_url = request.build_absolute_uri(
            f"{media_url}{audio_filename}"
        )

        return JsonResponse({
            "status": "success",
            "message": "Audio uploaded, STT, RAG/AI processing completed.",
            "user_text": user_text,
            "ai_response": ai_reply,
            "audio_url": audio_url,
            "speech_audio_url": speech_audio_url,
            "from_cache": is_from_cache,
            "source": source,
            "kb_match": source == "knowledge_base"
        }, status=200)

    except Device.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "message": "Device not found"
        }, status=404)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)


def save_pcm_as_wav(pcm_file_path, wav_file_path, sample_rate=16000):
    with open(pcm_file_path, 'rb') as pcm_file:
        pcm_data = pcm_file.read()

    with wave.open(wav_file_path, 'wb') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
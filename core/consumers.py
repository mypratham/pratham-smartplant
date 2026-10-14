import os
import logging
import json
import wave
import asyncio
import io
import time
import threading
from collections import deque

import httpx
import numpy as np
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer
import core.apps as core_apps





# gTTS and pydub for TTS Audio Generation
try:
    from gtts import gTTS
    from pydub import AudioSegment
    HAS_TTS = True
except ImportError:
    HAS_TTS = False

# =========================================================
# 1. Windows MSYS2 libopus-0.dll Path Preload Setup
# =========================================================
OPUS_DLL_DIR = r"C:\msys64\mingw64\bin"
if os.path.exists(OPUS_DLL_DIR):
    os.environ["PATH"] = OPUS_DLL_DIR + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(OPUS_DLL_DIR)
        except Exception:
            pass

try:
    import opuslib
    HAS_OPUS = True
except Exception as e:
    HAS_OPUS = False

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


def _load_dotenv_into_environ():
    """.env ki values os.environ mein (jo pehle se set nahi). Isse VAD / Whisper
    jaisi saari settings .env se badli ja sakti hain. Django settings ko yahan
    nahi chhoote (import ke waqt woh ready nahi hoti)."""
    here = os.path.dirname(os.path.abspath(__file__))
    roots = [os.getcwd(), here, os.path.dirname(here)]
    dirs = list(roots)
    for root in roots:
        try:
            for entry in os.listdir(root):
                sub = os.path.join(root, entry)
                if os.path.isfile(os.path.join(sub, "settings.py")):
                    dirs.append(sub)
        except OSError:
            pass
    loaded = []
    for d in dict.fromkeys(dirs):
        path = os.path.join(d, ".env")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    m = re.match(r'os\.getenv\(\s*["\'][^"\']*["\']\s*,\s*["\']([^"\']*)["\']\s*\)', val)
                    if m:
                        val = m.group(1)
                    val = val.strip('"').strip("'")
                    if key and val and key not in os.environ:
                        os.environ[key] = val
                        loaded.append(key)
        except OSError:
            pass
    return loaded


import re
_DOTENV_LOADED = _load_dotenv_into_environ()


def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# Local Whisper Model Import (if available in project)
# Whisper model ko is process mein ek baar load karein.
WHISPER_MODEL = None
WHISPER_LOAD_ERROR = None

# faster-whisper: wahi Whisper model, CTranslate2 int8 par CPU mein 3-4x tez.
# .env: STT_ENGINE=faster   (pip install faster-whisper)
FAST_WHISPER_MODEL = None
# groq/openai ke saath bhi faster-whisper backup ke liye (normal Whisper bahut RAM leta hai)
if os.getenv("STT_ENGINE", "").strip().lower() in ("faster", "groq", "openai"):
    try:
        from faster_whisper import WhisperModel as _FastWhisperModel

        FAST_WHISPER_MODEL = _FastWhisperModel(
            os.getenv("WHISPER_MODEL_NAME", "base"),
            device="cpu",
            compute_type="int8",
            cpu_threads=max(1, (os.cpu_count() or 2) - 1),
        )
        logging.getLogger(__name__).info(
            "faster-whisper loaded: %s (int8)", os.getenv("WHISPER_MODEL_NAME", "base")
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "faster-whisper load failed (pip install faster-whisper); normal Whisper chalega"
        )


def _run_fast_whisper(audio, prompt=None, language=None):
    language = language or os.getenv("WHISPER_LANGUAGE", "").strip() or None
    with WHISPER_LOCK:
        segments, _info = FAST_WHISPER_MODEL.transcribe(
            audio,
            language=language,
            beam_size=1,            # greedy: sabse tez
            initial_prompt=prompt,
            vad_filter=False,
            condition_on_previous_text=False,
            # Default mein 6 baar dobara decode (temperature fallback) hota tha:
            # ek 0.9 sec clip par 10 sec lag gaye. Ab max 2 koshish.
            temperature=(0.0, 0.4),
            without_timestamps=True,
            max_new_tokens=80,      # chhoti voice command; lambi hallucination nahi
            no_repeat_ngram_size=3,  # "बपपपपपप..." jaisa loop na bane
        )
        segs = list(segments)
        probs = [getattr(s, "avg_logprob", 0.0) for s in segs]
        _run_fast_whisper.last_logprob = min(probs) if probs else -9.0
        return _collapse_repeats(" ".join(seg.text.strip() for seg in segs).strip())


_run_fast_whisper.last_logprob = 0.0


def stt_looks_bad(text, logprob):
    """Local model ka nateeja kamzor lag raha hai? (Groq se dobara sunne ke liye)"""
    t = (text or "").strip()
    if not t:
        return False
    try:
        limit = float(_pratham_setting("STT_HYBRID_LOGPROB") or -0.6)
    except ValueError:
        limit = -0.6
    if logprob is not None and logprob < limit:
        return True
    if re.search(r"(.)\1{3,}", t) or re.search(r"(\w{2,4})\1{2,}", t):   # "niyayayay"
        return True
    if re.search(r"[\u0600-\u06FF]", t):   # galti se Urdu/Arabic lipi
        return True
    return False


def _collapse_repeats(text):
    """Whisper kabhi ek akshar/shabd baar-baar likhta hai ("बपपपपप", "ok ok ok ok").
    3 se zyada repeat ko kaat dein."""
    if not text:
        return text
    text = re.sub(r"(.)\1{3,}", r"\1", text)                 # पपपप -> प
    text = re.sub(r"\b(\w+)(?:\s+\1\b){3,}", r"\1", text)    # word word word word -> word
    return text.replace("\ufffd", "").strip()

# Ek model, ek time par ek hi transcription.
# Pehle har inactivity par alag thread mein Whisper parallel chal raha tha:
# CPU par sab threads aapas mein ladte the aur backlog ban jata tha (lag ki main wajah).
WHISPER_LOCK = threading.Lock()

# "hi", "en" ya khali (auto-detect). Chhote clips par auto-detect galat aur slow hota hai,
# isliye .env mein WHISPER_LANGUAGE set karna behtar hai.
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "").strip() or None

try:
    import whisper

    # Whisper saare CPU cores le leta hai; ek core event loop (WebSocket) ke liye chhodein.
    try:
        import torch

        torch.set_num_threads(
            _env_int("WHISPER_THREADS", max(1, (os.cpu_count() or 2) - 1))
        )
    except Exception:
        pass

    def _early_env(name, default):
        """Model load ke waqt .env bhi padhein. Yahan Django settings abhi
        configure nahi hoti, isliye settings ko haath nahi lagate."""
        value = os.getenv(name)
        if value:
            return value.strip()
        here = os.path.dirname(os.path.abspath(__file__))
        roots = [os.getcwd(), here, os.path.dirname(here)]
        dirs = list(roots)
        for root in roots:   # settings.py wala folder (jaise prathamesp32_project)
            try:
                for entry in os.listdir(root):
                    sub = os.path.join(root, entry)
                    if os.path.isfile(os.path.join(sub, "settings.py")):
                        dirs.append(sub)
            except OSError:
                pass
        for d in dirs:
            path = os.path.join(d, ".env")
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    for line in fh:
                        line = line.strip()
                        if line.startswith("#") or "=" not in line:
                            continue
                        key, val = line.split("=", 1)
                        if key.strip() == name:
                            return val.strip().strip('"').strip("'") or default
            except OSError:
                pass
        return default

    _whisper_name = _early_env("WHISPER_MODEL_NAME", "base")
    if FAST_WHISPER_MODEL is None:
        WHISPER_MODEL = whisper.load_model(
            _whisper_name,
            device="cpu",
        )
        logger.info("Whisper model loaded successfully: %s", _whisper_name)
    else:
        logger.info("faster-whisper chal raha hai; normal Whisper load nahi kiya (RAM bachi)")

except Exception as exc:
    WHISPER_LOAD_ERROR = str(exc)
    logger.exception("Whisper model load failed")


def _run_whisper(model, audio, prompt=None):
    """Thread ke andar chalta hai. Global lock se ek time par ek hi job."""
    language = WHISPER_LANGUAGE or (_pratham_setting("WHISPER_LANGUAGE") or None)
    with WHISPER_LOCK:
        # Whisper ki default decoding settings (pehle wale working code jaisi).
        # temperature=0.0 wala change hata diya: weak/quiet audio par woh
        # transcript ko empty kar sakta tha. Speed ka fix (ek-ek job, lock) bana hua hai.
        return model.transcribe(
            audio,
            fp16=False,
            language=language,
            initial_prompt=prompt,
        )


import re

# Har device ki pichhli baatcheet (reconnect ke baad bhi yaad rahe)
CHAT_HISTORY = {}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[।!?\.\n])\s+")


def split_into_sentences(text, min_chars=25):
    """Jawab ko vakyon mein todein. Bahut chhote tukde agle ke saath jod dein,
    taaki har gTTS request ka overhead kam rahe."""
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text or "") if p.strip()]
    sentences = []
    buffer = ""
    for part in parts:
        buffer = f"{buffer} {part}".strip() if buffer else part
        if len(buffer) >= min_chars:
            sentences.append(buffer)
            buffer = ""
    if buffer:
        if sentences:
            sentences[-1] = f"{sentences[-1]} {buffer}"
        else:
            sentences.append(buffer)
    return sentences


def ascii_for_display(text, limit=90):
    """TFT font sirf ASCII dikha sakta hai: baaki characters hata dein.
    Lines (\n) bachi rehti hain, taaki list (jobs/quiz) line-by-line dikhe."""
    cleaned = "".join(ch for ch in (text or "") if ord(ch) < 128)
    lines = [" ".join(line.split()) for line in cleaned.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned[:limit]


def parse_ai_reply(raw_content, display_limit=90):
    """Model ka JSON {"speech": ..., "display": ...} padhein.
    JSON na mile to poora text bolne ke liye use karein."""
    try:
        data = json.loads(raw_content)
        speech = str(data.get("speech", "")).strip()
        display = ascii_for_display(str(data.get("display", "")), display_limit)
        if speech:
            return speech, display
    except (ValueError, TypeError, AttributeError):
        pass
    return raw_content, ascii_for_display(raw_content, display_limit)


# ---------------------------------------------------------------
# MyPratham portal data (jobs / quiz / learning) voice se
# ---------------------------------------------------------------
# Order zaroori hai: specific pehle ("exam result" -> results, "job application" -> applications)
PRATHAM_INTENT_WORDS = {
    "applications": (
        "my applications", "meri applications", "applied jobs", "job application",
        "job applications", "applied", "एप्लीकेशन", "आवेदन", "aavedan", "avedan",
    ),
    "results": (
        "result", "results", "रिजल्ट", "परिणाम", "parinam", "marks", "score",
        "स्कोर", "नंबर", "मार्क्स", "kitne number",
    ),
    "challenges": ("challenge", "challenges", "चैलेंज", "चुनौती"),
    "profile": (
        "my profile", "mera profile", "profile", "प्रोफाइल", "प्रोफ़ाइल",
        "mera naam", "मेरा नाम", "my account",
    ),
    "jobs": (
        "job", "jobs", "naukri", "naukari", "नौकरी", "नौकरियां", "जॉब", "जॉब्स",
        "vacancy", "vacancies", "वैकेंसी", "rozgar", "रोजगार", "career",
    ),
    "quiz": (
        "quiz", "quizzes", "क्विज़", "क्विज", "exam", "exams", "एग्जाम",
        "परीक्षा", "pariksha", "mock test", "टेस्ट",
    ),
    "learning": (
        "learning", "course", "courses", "कोर्स", "padhai", "पढ़ाई", "पढाई",
        "lesson", "lessons", "सीखना", "seekhna", "study material", "लर्निंग",
        "subject", "subjects", "विषय", "chapter", "chapters", "चैप्टर", "अध्याय",
    ),
}

PRATHAM_INTENT_LABELS = {
    "jobs": "Jobs",
    "applications": "Meri job applications",
    "quiz": "Quiz / Exams",
    "results": "Exam results",
    "challenges": "Challenges",
    "learning": "Learning courses",
    "profile": "User profile",
}


def detect_pratham_intent(transcript):
    """User ne jobs / quiz / learning maanga? Return intent naam ya None."""
    text = (transcript or "").lower()
    text = re.sub(r"[.,!?।\"']", " ", text)
    for intent, words in PRATHAM_INTENT_WORDS.items():
        if _contains_any(text, words):
            return intent
    return None


def _compact_for_ai(obj, depth=0):
    """API response ko chhota karein (AI ko bhejne ke liye): lambi lists,
    lambe text aur gehri nesting kaat dein. Schema jaane bina kaam karta hai."""
    if depth > 3:
        return None
    if isinstance(obj, dict):
        out = {}
        for key, value in list(obj.items())[:25]:
            item = _compact_for_ai(value, depth + 1)
            if item not in (None, "", [], {}):
                out[key] = item
        return out
    if isinstance(obj, list):
        return [_compact_for_ai(v, depth + 1) for v in obj[:8]]
    if isinstance(obj, str):
        return obj if len(obj) <= 120 else obj[:117] + "..."
    return obj


_DOTENV_CACHE = None


def _read_dotenv():
    """Project ki .env khud padhein (agar settings.py ne load_dotenv nahi kiya ho).
    'NAAM=value' aur galti se likha 'NAAM = os.getenv("NAAM", "value")' dono samjhe jaate hain."""
    global _DOTENV_CACHE
    if _DOTENV_CACHE is not None:
        return _DOTENV_CACHE
    values = {}
    dirs = []
    base_dir = getattr(settings, "BASE_DIR", None)
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (base_dir, os.getcwd(), here, os.path.dirname(here),
              os.path.dirname(os.path.dirname(here))):
        if d and str(d) not in dirs:
            dirs.append(str(d))
    if base_dir:
        dirs.append(os.path.dirname(str(base_dir)))
    # settings.py wala folder (jaise ESP32_Django\ESP32_Django\.env)
    try:
        import importlib
        mod_name = os.environ.get("DJANGO_SETTINGS_MODULE", "")
        if mod_name:
            mod = importlib.import_module(mod_name)
            sdir = os.path.dirname(os.path.abspath(mod.__file__))
            for d in (sdir, os.path.dirname(sdir)):
                if d not in dirs:
                    dirs.append(d)
    except Exception:
        pass
    candidates = []
    for d in dirs:
        for fname in (".env", ".env.txt", "env", ".env.local"):
            p = os.path.normpath(os.path.join(d, fname))
            if p not in candidates:
                candidates.append(p)
    found = [p for p in candidates if os.path.isfile(p)]
    if not found:
        logger.warning("Pratham config: .env file nahi mili. Yahan dhoondha: %s", dirs)
    for path in found:
        try:
            with open(path, encoding="utf-8-sig") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key, val = key.strip(), val.strip()
                    m = re.match(r'os\.getenv\(\s*["\'][^"\']*["\']\s*,\s*["\']([^"\']*)["\']\s*\)', val)
                    if m:
                        val = m.group(1)
                    values.setdefault(key, val.strip('"').strip("'"))
            logger.info("Pratham config: .env padhi: %s (%d keys)", path, len(values))
        except Exception:
            logger.exception(".env read failed: %s", path)
    _DOTENV_CACHE = values
    return values


_PRATHAM_SOURCE_LOGGED = set()


def _decouple_value(name):
    """settings.py agar python-decouple (config(...)) use karta hai to wahi .env se padhein."""
    try:
        from decouple import config as decouple_config
        return decouple_config(name, default="")
    except Exception:
        return ""


def _pratham_setting(name, default=""):
    """settings.py ya .env se value; '<placeholder>' wali value ignore."""
    sources = (
        ("settings.py", getattr(settings, name, "")),
        ("environment", os.getenv(name, "")),
        (".env file", _read_dotenv().get(name, "")),
        ("decouple", _decouple_value(name)),
        ("default", default),
    )
    def _unwrap(v):
        # Aksar log example ki tarah <value> likh dete hain: < > hata dein
        v = str(v or "").strip().strip('"').strip("'").strip()
        if v.startswith("<") and v.endswith(">"):
            v = v[1:-1].strip()
        return v

    source, value = "none", ""
    for src_name, src_value in sources:
        src_value = _unwrap(src_value)
        if src_value and "<" not in src_value and ">" not in src_value:
            source, value = src_name, src_value
            break
    if name not in _PRATHAM_SOURCE_LOGGED:
        _PRATHAM_SOURCE_LOGGED.add(name)
        logger.info("Pratham config: %s from %s (length %d)", name, source, len(str(value)))
    value = str(value).strip().strip('"').strip("'")
    return "" if "<" in value else value


# intent -> (env override naam, default path, auth: "key" | "token" | "both")
PRATHAM_ENDPOINTS = {
    "jobs": ("PRATHAM_JOBS_URL", "/api/job/", "key"),
    "applications": ("PRATHAM_APPLICATIONS_URL", "/api/job/my-applications", "both"),
    "quiz": ("PRATHAM_EXAM_URL", "/school/exams/D/?page=1", "token"),
    "results": ("PRATHAM_RESULTS_URL", "/school/results/", "token"),
    "challenges": ("PRATHAM_CHALLENGES_URL", "/school/challenges", "token"),
    "learning": ("PRATHAM_LEARNING_URL", "/school/student-courses/", "token"),
    "profile": ("PRATHAM_PROFILE_URL", "/authapp/api/auth/profile/", "token"),
}


async def fetch_pratham_data(intent):
    """MyPratham API se live data. Return (ok, compact_data_or_error_text)."""
    api_key = _pratham_setting("PRATHAM_API_KEY", "kushal123")
    api_secret = _pratham_setting("PRATHAM_API_SECRET", "kushalsecret456")
    user_token = _pratham_setting("PRATHAM_USER_TOKEN")

    env_name, path, auth = PRATHAM_ENDPOINTS.get(intent, PRATHAM_ENDPOINTS["jobs"])
    url = _pratham_setting(env_name) or f"{API_BASE_URL}{path}"
    if not url.startswith("http"):
        url = f"{API_BASE_URL}/{url.lstrip('/')}"

    headers = {"Accept": "application/json"}
    if auth in ("key", "both"):
        headers["x-api-key"] = api_key
        headers["X-API-SECRET"] = api_secret
    if auth in ("token", "both"):
        if not user_token:
            # Dashboard token sirf browser (localStorage) mein rakhta hai; server ko .env chahiye
            logger.warning("%s: PRATHAM_USER_TOKEN .env / settings.py mein set nahi hai", intent)
            return False, "Iske liye MyPratham login token server par set nahi hai."
        headers["Authorization"] = f"token {user_token}"

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            res = await client.get(url, headers=headers)
        if res.status_code != 200:
            logger.warning("Pratham API %s failed: HTTP %s url=%s body=%s",
                           intent, res.status_code, url, res.text[:200])
            if res.status_code in (401, 403):
                return False, "MyPratham token galat ya expire ho gaya hai; dashboard se dobara login karke naya token .env mein daalein."
            return False, f"MyPratham server ne HTTP {res.status_code} diya."
        logger.info("Pratham API %s OK: url=%s bytes=%d", intent, url, len(res.content))
        data = _compact_for_ai(res.json())
        text = json.dumps(data, ensure_ascii=False)
        return True, text[:3500]
    except Exception as err:
        logger.exception("Pratham API %s error", intent)
        return False, f"MyPratham server se connect nahi ho paya ({type(err).__name__})."


# ---------------------------------------------------------------
# Voice quiz: MyPratham exam ke sawal ek-ek karke bolein, jawab sunein, score
# ---------------------------------------------------------------
import difflib
import html as _html

QUIZ_MAX_QUESTIONS = _env_int("QUIZ_MAX_QUESTIONS", 5)
QUIZ_START_WORDS = (
    "start", "shuru", "suru", "शुरू", "शुरु", "chalu", "चालू", "begin", "play",
    "khelo", "खेलो", "khelna", "खेलना", "karao", "कराओ", "karwao", "करवाओ",
    "attempt", "शुरुआत", "shuruat",
)
QUIZ_STOP_WORDS = (
    "stop", "band", "bandh", "बंद", "बन्द", "बनद", "बांध", "quit", "exit", "khatam",
    "खत्म", "ख़त्म", "खतम", "cancel", "रोको", "रोक", "roko", "rok", "बस", "bas",
    "स्टॉप", "स्टोप",
)
QUIZ_REPEAT_WORDS = ("repeat", "dobara", "दोबारा", "phir se", "फिर से", "fir se", "again")
QUIZ_SKIP_WORDS = ("skip", "agla", "अगला", "next", "pass", "छोड़", "chhod", "chod")

_OPTION_LETTERS = "ABCDEF"
# Whisper "A/B/C/D" ko kai tarah likhta hai
_LETTER_WORDS = {
    0: ("a", "ए", "ऐ", "ay", "option a", "pehla", "pahla", "पहला", "first", "1", "one", "ek", "एक"),
    1: ("b", "बी", "bee", "be", "option b", "doosra", "dusra", "दूसरा", "second", "2", "two", "do", "दो"),
    2: ("c", "सी", "see", "si", "option c", "teesra", "tisra", "तीसरा", "third", "3", "three", "teen", "तीन"),
    3: ("d", "डी", "dee", "di", "option d", "chautha", "chotha", "चौथा", "fourth", "4", "four", "char", "चार"),
    4: ("e", "ई", "option e", "paanchva", "पांचवा", "fifth", "5", "five", "paanch", "पांच"),
}
_DEV_LETTER_START = {"ए": 0, "ऐ": 0, "ब": 1, "स": 2, "ड": 3}

_ORDINAL_PICK = {
    0: ("pehla", "pahla", "पहला", "पहले", "first", "1", "ek", "एक", "one", "number one"),
    1: ("doosra", "dusra", "दूसरा", "दूसरे", "second", "2", "do", "दो", "two", "number two"),
    2: ("teesra", "tisra", "तीसरा", "तीसरे", "third", "3", "teen", "तीन", "three"),
    3: ("chautha", "चौथा", "fourth", "4", "char", "चार", "four"),
    4: ("paanchva", "पांचवा", "fifth", "5", "paanch", "पांच", "five"),
}

_ID_KEYS = ("id", "exam_id", "examId", "pk", "_id", "uuid", "exam")
_NAME_KEYS = ("title", "name", "exam_name", "examName", "exam_title", "subject", "heading")
_Q_TEXT_KEYS = ("question", "question_text", "questionText", "question_name", "ques", "title", "text", "name")
_OPT_LIST_KEYS = ("options", "choices", "answers", "option_list", "optionList", "question_options")
_OPT_TEXT_KEYS = ("option", "text", "title", "value", "option_text", "optionText", "answer", "name", "label")
_CORRECT_FLAG_KEYS = ("is_correct", "isCorrect", "correct", "is_answer", "is_right", "right")
_ANSWER_KEYS = ("answer", "correct_answer", "correctAnswer", "correct_option", "correctOption",
                "right_answer", "ans", "correct", "solution_option", "answer_key")


def _clean_text(value):
    text = _html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def _find_dict_list(obj, depth=0):
    """JSON ke andar sabse pehli 'list of dicts' (results / data / exams ...)."""
    if depth > 4:
        return []
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj[:3]):
        return obj
    if isinstance(obj, dict):
        for key in ("results", "data", "exams", "questions", "items", "list", "records"):
            found = _find_dict_list(obj.get(key), depth + 1)
            if found:
                return found
        for value in obj.values():
            found = _find_dict_list(value, depth + 1)
            if found:
                return found
    return []


def _first_key(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def parse_exam_list(data):
    exams = []
    for item in _find_dict_list(data):
        exam_id = _first_key(item, _ID_KEYS)
        if isinstance(exam_id, dict):
            exam_id = _first_key(exam_id, ("id", "pk"))
        name = _clean_text(_first_key(item, _NAME_KEYS) or "")
        if exam_id is not None and name:
            exams.append({"id": exam_id, "name": name, "raw": item})
    return exams


def _norm(text):
    text = (text or "").lower().translate(_DEVANAGARI_DIGITS)
    text = re.sub(r"[.,!?।\"'()\-:]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_GENERIC_EXAM_WORDS = {
    "exam", "exams", "quiz", "test", "mock", "paper", "the", "and", "wala", "wali",
    "start", "shuru", "karo", "years", "year", "set", "part",
}


def pick_exam(transcript, exams):
    """Transcript se exam chunein: naam match ya 'pehla/doosra'. None = samajh nahi aaya."""
    if not exams:
        return None
    text = _norm(transcript)
    best, best_score = None, 0.0
    words = set(text.split())
    for exam in exams:
        name = _norm(exam["name"])
        name_words = [w for w in name.split() if len(w) > 1]
        overlap = sum(1 for w in name_words if w in words)
        score = overlap / max(1, len(name_words))
        # Ek khaas shabd bhi kaafi hai ("NEET", "Excel"); "exam/quiz/test" jaise nahi
        if any(w in words for w in name_words if len(w) >= 3 and w not in _GENERIC_EXAM_WORDS):
            score = max(score, 0.5)
        score = max(score, difflib.SequenceMatcher(None, name, text).ratio() * 0.6)
        if score > best_score:
            best, best_score = exam, score
    if best is not None and best_score >= 0.34:
        return best
    for idx, ordinal_words in _ORDINAL_PICK.items():
        if idx < len(exams) and _contains_any(text, ordinal_words):
            return exams[idx]
    if len(exams) == 1:
        return exams[0]
    return None


def _option_text(opt):
    if isinstance(opt, dict):
        return _clean_text(_first_key(opt, _OPT_TEXT_KEYS) or "")
    return _clean_text(opt)


def _resolve_correct(answer, options, raw_options=None):
    """'B' / 2 / 'option2' / option text / option id -> 0-based index ya None."""
    if answer is None:
        return None
    if isinstance(answer, dict):
        answer = _first_key(answer, ("id", "option", "text", "value")) or ""
    if isinstance(answer, bool):
        return None
    if raw_options:
        for i, opt in enumerate(raw_options):
            if isinstance(opt, dict) and str(opt.get("id")) == str(answer):
                return i
    if isinstance(answer, int) or (isinstance(answer, str) and answer.strip().isdigit()):
        n = int(answer)
        if 1 <= n <= len(options):
            return n - 1
        if n == 0:
            return 0
    ans = _clean_text(answer)
    m = re.fullmatch(r"(?:option[_ ]?|opt[_ ]?)?([a-fA-F1-6])", ans.strip(), re.I)
    if m:
        ch = m.group(1).upper()
        return int(ch) - 1 if ch.isdigit() else _OPTION_LETTERS.index(ch)
    low = ans.lower()
    for i, opt in enumerate(options):
        if opt and opt.lower() == low:
            return i
    return None


def parse_questions(data):
    """MyPratham questions JSON -> [{"q", "options", "correct"}]. Schema jaane bina."""
    out = []
    for item in _find_dict_list(data):
        q_text = _clean_text(_first_key(item, _Q_TEXT_KEYS) or "")
        raw_opts = _first_key(item, _OPT_LIST_KEYS)
        options, correct = [], None
        if isinstance(raw_opts, list) and raw_opts:
            options = [_option_text(o) for o in raw_opts]
            for i, o in enumerate(raw_opts):
                if isinstance(o, dict) and any(o.get(k) is True or str(o.get(k)).lower() in ("1", "true")
                                               for k in _CORRECT_FLAG_KEYS if k in o):
                    correct = i
                    break
        else:
            # option1..option4 / option_a..option_d / a..d
            for i, letter in enumerate("abcdef"):
                val = None
                for key in (f"option{i+1}", f"option_{i+1}", f"option_{letter}", f"option{letter.upper()}",
                            f"opt{i+1}", f"opt_{letter}", f"choice{i+1}", letter, letter.upper()):
                    if item.get(key) not in (None, ""):
                        val = item[key]
                        break
                if val is None:
                    break
                options.append(_clean_text(val))
            raw_opts = None
        options = [o for o in options if o]
        if correct is None:
            correct = _resolve_correct(_first_key(item, _ANSWER_KEYS), options, raw_opts)
        if q_text and len(options) >= 2:
            option_ids = []
            if isinstance(raw_opts, list):
                option_ids = [o.get("id") if isinstance(o, dict) else None for o in raw_opts][:6]
            out.append({"q": q_text, "options": options[:6], "correct": correct,
                        "id": _first_key(item, ("id", "question_id", "questionId", "pk")),
                        "option_ids": option_ids})
    return out


async def normalize_questions_with_ai(data, api_key, limit):
    """Agar JSON samajh na aaye to OpenAI se sawal/options/jawab nikalwayein."""
    if not api_key:
        return []
    try:
        sample = json.dumps(_compact_for_ai(data), ensure_ascii=False)[:6000]
        async with httpx.AsyncClient(timeout=20) as client:
            response = await llm_post(
                    client,
                    json_body={
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": (
                            "Convert this exam API JSON into multiple-choice questions. Return JSON "
                            "{\"questions\": [{\"q\": text, \"options\": [texts], \"correct\": 0-based index or null}]}. "
                            f"Max {limit} questions. Do not invent questions or answers; use null if the correct answer is not in the data."
                        )},
                        {"role": "user", "content": sample},
                    ],
                },
            )
            response.raise_for_status()
            parsed = json.loads(response.json()["choices"][0]["message"]["content"])
        out = []
        for q in parsed.get("questions", [])[:limit]:
            opts = [_clean_text(o) for o in q.get("options", []) if _clean_text(o)]
            corr = q.get("correct")
            if not isinstance(corr, int) or not (0 <= corr < len(opts)):
                corr = None
            if q.get("q") and len(opts) >= 2:
                out.append({"q": _clean_text(q["q"]), "options": opts[:6], "correct": corr})
        return out
    except Exception:
        logger.exception("Quiz: AI normalize failed")
        return []


async def pratham_get_json(url_or_path):
    """MyPratham GET (user token ke saath). Return (ok, json_or_error_text)."""
    user_token = _pratham_setting("PRATHAM_USER_TOKEN")
    if not user_token:
        return False, "MyPratham token set nahi hai"
    url = url_or_path if url_or_path.startswith("http") else f"{API_BASE_URL}/{url_or_path.lstrip('/')}"
    headers = {"Accept": "application/json", "Authorization": f"token {user_token}"}
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            res = await client.get(url, headers=headers)
            if res.status_code == 404 and not url.endswith("/") and "?" not in url:
                res = await client.get(url + "/", headers=headers)
        if res.status_code != 200:
            logger.warning("Pratham GET failed: HTTP %s url=%s body=%s", res.status_code, url, res.text[:200])
            return False, f"HTTP {res.status_code}"
        logger.info("Pratham GET OK: url=%s bytes=%d", url, len(res.content))
        return True, res.json()
    except Exception as err:
        logger.exception("Pratham GET error: %s", url)
        return False, type(err).__name__


def parse_quiz_answer(transcript, options):
    """User ka jawab -> option index (0-based) ya None."""
    # Saaf bola gaya akshar ("B", "Option C.") sabse pehle: option ke text se
    # galat milaan ("बाएं" -> A) na ho
    letters = {m.upper() for m in re.findall(r"(?<![A-Za-z])([A-Fa-f])(?![A-Za-z])", transcript or "")
               if m.isupper() or re.search(r"(?i)option\s*" + m, transcript or "")}
    letters = {l for l in letters if _OPTION_LETTERS.index(l) < len(options)} if options else letters
    if len(letters) == 1 and options:
        return _OPTION_LETTERS.index(letters.pop())
    text = _norm(transcript)
    text = re.sub(r"\b(option|opshan|ऑप्शन|विकल्प|answer|jawab|जवाब|mera|मेरा|hai|है|wala|वाला)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    text = _collapse_repeats(text)
    # Pura jawab ek akshar ("B", "बी") ho
    for idx, words in _LETTER_WORDS.items():
        if idx < len(options) and text in words:
            return idx
    # Bigda hua chhota Hindi jawab ("बप", "बि", "सि", "डि"): pehle akshar se
    if len(text) <= 4 and text[:1] in _DEV_LETTER_START:
        idx = _DEV_LETTER_START[text[:1]]
        if idx < len(options):
            return idx
    # Option ka text bola ho
    best, best_score = None, 0.0
    for i, opt in enumerate(options):
        o = _norm(opt)
        if not o:
            continue
        if o in text or (len(text) > 3 and text in o):
            return i
        score = difflib.SequenceMatcher(None, o, text).ratio()
        if score > best_score:
            best, best_score = i, score
    if best is not None and best_score >= 0.6:
        return best
    # "option b", "b hai", "doosra"
    for idx, words in _LETTER_WORDS.items():
        if idx < len(options) and _contains_any(text, [w for w in words if len(w) > 1 or w.isdigit()]):
            return idx
    tokens = text.split()
    for idx in range(len(options)):
        if _OPTION_LETTERS[idx].lower() in tokens:
            return idx
    return None


_EXAM_LIST_CACHE = {}


async def ai_pick_choice(transcript, choices, purpose="option"):
    """Whisper ne naam bigaad diya ('XL wolla' = 'MS Excel')? AI se poochhein.
    Return index ya None."""
    api_key = llm_api_key()
    if not api_key or not transcript or not choices:
        return None
    listing = "\n".join(f"{i}: {c}" for i, c in enumerate(choices))
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await llm_post(
                    client,
                    json_body={
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "max_tokens": 20,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": (
                            f"A Hindi/English voice user picked one {purpose} from the list. The speech-to-text "
                            "may be badly misspelled or in Devanagari (e.g. 'XL wolla' = 'Excel wala', "
                            "'बी' = B, 'एमएस एक्सेल' = MS Excel). Return JSON {\"index\": number} of the "
                            "chosen item, or {\"index\": -1} if the user clearly did not pick any."
                        )},
                        {"role": "user", "content": f"List:\n{listing}\n\nUser said: {transcript}"},
                    ],
                },
            )
            response.raise_for_status()
            idx = json.loads(response.json()["choices"][0]["message"]["content"]).get("index")
        if isinstance(idx, int) and 0 <= idx < len(choices):
            logger.info("AI pick: %r -> %d (%s)", transcript, idx, choices[idx])
            return idx
    except Exception:
        logger.exception("AI pick failed")
    return None


async def romanize_quiz_for_display(questions):
    """TFT sirf English letters dikha sakta hai. Hindi sawal/options ko Roman
    (Hinglish) mein badal kar q['q_disp'] / q['opts_disp'] mein rakhein."""
    def is_ascii(t):
        return all(ord(ch) < 128 for ch in t)

    def disp(text, limit):
        a = ascii_for_display(text, limit)
        return a if len(re.sub(r"[^A-Za-z0-9]", "", a)) >= 2 else ""

    for q in questions:
        q["q_disp"] = disp(q["q"], 150)
        q["opts_disp"] = [disp(o, 38) for o in q["options"]]
    need = [i for i, q in enumerate(questions)
            if not is_ascii(q["q"]) or not all(is_ascii(o) for o in q["options"])]
    api_key = llm_api_key()
    if not need or not api_key:
        return
    payload = [{"q": questions[i]["q"], "options": questions[i]["options"]} for i in need]
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await llm_post(
                    client,
                    json_body={
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": (
                            "Transliterate each quiz question and its options from Hindi (Devanagari) into "
                            "Roman Hinglish using only ASCII letters, digits and basic punctuation. "
                            "Keep the meaning and order; do not translate English words; keep it short. "
                            "Return JSON {\"items\": [{\"q\": str, \"options\": [str]}]} in the same order."
                        )},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                },
            )
            response.raise_for_status()
            items = json.loads(response.json()["choices"][0]["message"]["content"]).get("items", [])
        for i, item in zip(need, items):
            q = questions[i]
            if item.get("q"):
                q["q_disp"] = ascii_for_display(item["q"], 150)
            opts = item.get("options") or []
            if len(opts) == len(q["options"]):
                q["opts_disp"] = [ascii_for_display(o, 38) for o in opts]
        logger.info("Quiz: %d sawal TFT ke liye Roman mein badle", len(need))
    except Exception:
        logger.exception("Quiz romanize failed (TFT par sirf English hissa dikhega)")


def is_quiz_start(transcript):
    text = (transcript or "").lower()
    if not _contains_any(text, QUIZ_START_WORDS):
        return False
    has_quiz = _contains_any(text, PRATHAM_INTENT_WORDS["quiz"]) or "test" in text
    if has_quiz:
        return True
    # "Excel start karo": quiz shabd nahi, lekin naam kisi exam ka hai
    words = set(_norm(text).split())
    for _ts, data in list(_EXAM_LIST_CACHE.values()):
        for exam in parse_exam_list(data):
            name_words = [w for w in _norm(exam["name"]).split()
                          if len(w) >= 3 and w not in _GENERIC_EXAM_WORDS]
            if any(w in words for w in name_words):
                return True
    return False


# ---------------------------------------------------------------
# AI provider: Groq (free tier) ya OpenAI.  .env:
#   AI_PROVIDER=groq          GROQ_API_KEY=gsk_...
#   GROQ_MODEL=llama-3.3-70b-versatile (default)
#   GROQ_FALLBACK_MODEL=llama-3.1-8b-instant (limit khatam / error par)
# Ek fail ho (limit, error) to agla provider apne aap try hota hai.
# ---------------------------------------------------------------
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_STT_URL = "https://api.openai.com/v1/audio/transcriptions"
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def _openai_key():
    return getattr(settings, "OPENAI_API_KEY", "") or _pratham_setting("OPENAI_API_KEY")


def _groq_key():
    return getattr(settings, "GROQ_API_KEY", "") or _pratham_setting("GROQ_API_KEY")


# Groq account par kaun se models khule hain (GET /models se, ek baar)
_GROQ_MODELS = None
_GROQ_PREFERENCE = (
    "llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b",
    "llama-3.1-8b-instant", "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct", "qwen/qwen3-32b",
)
_GROQ_SKIP_WORDS = ("whisper", "guard", "tts", "playai", "orpheus", "distil", "compound", "prompt")


async def _ensure_groq_models(client):
    """Account ke chat models ki list laayein aur best 2 chunein."""
    global _GROQ_MODELS
    if _GROQ_MODELS is not None:
        return
    key = _groq_key()
    if not key:
        _GROQ_MODELS = []
        return
    try:
        res = await client.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        if res.status_code != 200:
            logger.warning("Groq models list failed: HTTP %s %s", res.status_code, res.text[:200])
            _GROQ_MODELS = []
            return
        available = [
            m.get("id", "") for m in res.json().get("data", [])
            if m.get("active", True) is not False
        ]
        chat = [m for m in available if m and not any(w in m.lower() for w in _GROQ_SKIP_WORDS)]
        ordered = [m for m in _GROQ_PREFERENCE if m in chat] + sorted(m for m in chat if m not in _GROQ_PREFERENCE)
        _GROQ_MODELS = ordered[:3]
        logger.info("Groq models available: %s -> using %s", sorted(available), _GROQ_MODELS)
    except Exception:
        logger.exception("Groq models list error")
        _GROQ_MODELS = []


def _llm_providers():
    provider = (_pratham_setting("AI_PROVIDER") or "openai").lower()
    groq_key = _groq_key()
    openai_key = _openai_key()
    groq_models = []
    for m in (_pratham_setting("GROQ_MODEL"), _pratham_setting("GROQ_FALLBACK_MODEL")):
        if m and m not in groq_models:
            groq_models.append(m)
    for m in (_GROQ_MODELS or ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]):
        if m not in groq_models:
            groq_models.append(m)
    groq = [("groq", GROQ_CHAT_URL, groq_key, m) for m in groq_models[:4]]
    openai = [("openai", OPENAI_CHAT_URL, openai_key, _pratham_setting("OPENAI_MODEL") or "gpt-4o-mini")]
    chain = groq + openai if provider == "groq" else openai + groq
    return [p for p in chain if p[2]]


def llm_api_key():
    """Koi bhi AI provider configured hai? (truthy string)"""
    return "configured" if _llm_providers() else ""


# ---------------------------------------------------------------
# AI quota / usage: frontend (dashboard) par dikhane ke liye
#   GET /api/ai-quota/?device=plant_422196   (core/ai_quota_view.py)
# .env (optional): AI_DAILY_TOKEN_LIMIT=200000   AI_DAILY_REQUEST_LIMIT=1000
# ---------------------------------------------------------------
import contextvars
CURRENT_DEVICE = contextvars.ContextVar("pratham_current_device", default=None)
AI_QUOTA = {}          # Groq/OpenAI headers se aakhri jaankari
_AI_USAGE_LOCK = threading.Lock()


def _ai_usage_path():
    media_dir = getattr(settings, "MEDIA_ROOT", None) or os.path.join(os.getcwd(), "media")
    os.makedirs(str(media_dir), exist_ok=True)
    return os.path.join(str(media_dir), "ai_usage.json")


def _ai_usage_load():
    try:
        with open(_ai_usage_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def record_ai_usage(device_id, tokens, provider, model, headers):
    """Har AI call ke baad: device-wise aaj ke tokens + provider ka baaki quota."""
    today = datetime.now(REMINDER_TZ).strftime("%Y-%m-%d")
    AI_QUOTA.update({
        "provider": provider,
        "model": model,
        "remaining_requests": headers.get("x-ratelimit-remaining-requests"),
        "limit_requests": headers.get("x-ratelimit-limit-requests"),
        "remaining_tokens_minute": headers.get("x-ratelimit-remaining-tokens"),
        "limit_tokens_minute": headers.get("x-ratelimit-limit-tokens"),
        "reset_requests": headers.get("x-ratelimit-reset-requests"),
        "updated_at": datetime.now(REMINDER_TZ).isoformat(timespec="seconds"),
    })
    with _AI_USAGE_LOCK:
        data = _ai_usage_load()
        if data.get("date") != today:
            data = {"date": today, "total_tokens": 0, "total_requests": 0, "devices": {}}
        data["total_tokens"] += int(tokens or 0)
        data["total_requests"] += 1
        key = device_id or "other"
        dev = data["devices"].setdefault(key, {"tokens": 0, "requests": 0})
        dev["tokens"] += int(tokens or 0)
        dev["requests"] += 1
        data["quota"] = dict(AI_QUOTA)
        try:
            with open(_ai_usage_path(), "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
        except OSError:
            logger.warning("ai_usage.json save nahi hua")


def ai_quota_snapshot(device_id=None):
    """Dashboard ke liye JSON."""
    today = datetime.now(REMINDER_TZ).strftime("%Y-%m-%d")
    data = _ai_usage_load()
    if data.get("date") != today:
        data = {"date": today, "total_tokens": 0, "total_requests": 0, "devices": {}}
    quota = AI_QUOTA or data.get("quota") or {}

    def _int(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
    day_tokens_limit = _int(_pratham_setting("AI_DAILY_TOKEN_LIMIT")) or 200000
    day_req_limit = _int(quota.get("limit_requests")) or _int(_pratham_setting("AI_DAILY_REQUEST_LIMIT")) or 1000
    remaining_req = _int(quota.get("remaining_requests"))
    if remaining_req is None:
        remaining_req = max(0, day_req_limit - data["total_requests"])
    out = {
        "date": today,
        "provider": quota.get("provider"),
        "model": quota.get("model"),
        "updated_at": quota.get("updated_at"),
        "day": {
            "tokens_used": data["total_tokens"],
            "tokens_limit": day_tokens_limit,
            "tokens_left": max(0, day_tokens_limit - data["total_tokens"]),
            "requests_left": remaining_req,
            "requests_limit": day_req_limit,
        },
        "minute": {
            "tokens_left": _int(quota.get("remaining_tokens_minute")),
            "tokens_limit": _int(quota.get("limit_tokens_minute")),
        },
    }
    if device_id:
        dev = data["devices"].get(device_id, {"tokens": 0, "requests": 0})
        out["device"] = {"id": device_id, "tokens_today": dev["tokens"], "requests_today": dev["requests"]}
    return out


async def llm_post(client, json_body):
    """Chat completion: AI_PROVIDER pehle, fail ho to agla. httpx Response return."""
    last_response = None
    await _ensure_groq_models(client)
    providers = _llm_providers()
    if not providers:
        raise RuntimeError("Koi AI key set nahi (GROQ_API_KEY / OPENAI_API_KEY)")
    for idx, (name, url, key, model) in enumerate(providers):
        body = dict(json_body)
        body["model"] = model
        if "gpt-oss" in model:
            # Reasoning model: sochne ke tokens bhi max_tokens mein gine jaate hain
            body["max_tokens"] = max(int(body.get("max_tokens") or 0), 1200)
            body["reasoning_effort"] = "low"
        elif "qwen3" in model:
            body["reasoning_effort"] = "none"   # <think> text JSON ko na tode
        try:
            res = await client.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
            )
        except Exception as err:
            logger.warning("AI %s/%s error: %s; agla try", name, model, type(err).__name__)
            continue
        if res.status_code == 200:
            if idx > 0:
                logger.info("AI fallback used: %s/%s", name, model)
            h = res.headers
            try:
                used = (res.json().get("usage") or {}).get("total_tokens", 0)
            except Exception:
                used = 0
            try:
                await asyncio.to_thread(record_ai_usage, CURRENT_DEVICE.get(), used, name, model, dict(h))
            except Exception:
                logger.debug("AI usage record failed", exc_info=True)
            if h.get("x-ratelimit-remaining-requests") is not None:
                logger.info("AI quota %s/%s: aaj ki requests baaki %s/%s, is minute tokens baaki %s/%s",
                            name, model,
                            h.get("x-ratelimit-remaining-requests"), h.get("x-ratelimit-limit-requests"),
                            h.get("x-ratelimit-remaining-tokens"), h.get("x-ratelimit-limit-tokens"))
            return res
        logger.warning("AI %s/%s failed: HTTP %s %s", name, model, res.status_code, res.text[:200])
        last_response = res
    if last_response is not None:
        return last_response
    raise RuntimeError("Sab AI providers fail")


# ---------------------------------------------------------------
# Speech-to-text: OpenAI (fast + accurate) ya local Whisper
# .env: STT_ENGINE=openai  (default: local)
# ---------------------------------------------------------------
STT_VOCAB_PROMPT = (
    "Hindi aur English baatcheet. MyPratham, quiz, exam, test, MS Excel, GK Rajasthan, NEET, "
    "jobs, naukri, reminder, result, course, learning, volume, mute, option A, option B, "
    "option C, option D, shuru karo, band karo, agla, dobara."
)


def _pcm_float_to_wav_bytes(pcm_np, sample_rate=16000):
    pcm16 = (np.clip(pcm_np, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm16)
    return buf.getvalue()


async def openai_transcribe(pcm_np, prompt=None, engine="openai", language=None, timeout=20):
    """Cloud speech-to-text (Groq Whisper Large V3 ya OpenAI).
    Return text, ya None (fail par local Whisper chalega)."""
    if engine == "groq":
        api_key, url = _groq_key(), GROQ_STT_URL
        models = [_pratham_setting("STT_GROQ_MODEL") or "whisper-large-v3", "whisper-large-v3-turbo"]
        prompt_limit = 400   # Groq: prompt max ~224 tokens
    else:
        api_key, url = _openai_key(), OPENAI_STT_URL
        models = [_pratham_setting("STT_OPENAI_MODEL") or "gpt-4o-mini-transcribe", "whisper-1"]
        prompt_limit = 800
    if not api_key:
        logger.warning("STT %s: API key set nahi", engine)
        return None
    language = language or _pratham_setting("WHISPER_LANGUAGE") or WHISPER_LANGUAGE
    wav_bytes = _pcm_float_to_wav_bytes(pcm_np)
    for model_name in dict.fromkeys(models):
        data = {"model": model_name, "response_format": "json"}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt[:prompt_limit]
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    data=data,
                    files={"file": ("speech.wav", wav_bytes, "audio/wav")},
                )
            if res.status_code == 200:
                return (res.json().get("text") or "").strip()
            logger.warning("STT %s/%s failed: HTTP %s %s", engine, model_name, res.status_code, res.text[:200])
        except Exception:
            logger.exception("STT %s/%s error", engine, model_name)
    return None


_HINDI_WEEKDAYS = ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"]
_HINDI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त",
                 "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
_TIME_WORDS = ("time", "टाइम", "samay", "समय", "baje", "बजे", "बज", "kitne baj", "कितने बज", "o'clock", "clock")
_DATE_WORDS = ("date", "डेट", "tareekh", "tarikh", "तारीख", "तारीख़", "din", "दिन", "day", "आज कौन", "aaj kaun")
_ASK_WORDS = ("kya", "क्या", "kitne", "कितने", "kaun", "कौन", "what", "batao", "बताओ", "बताइए", "hai", "है", "today", "aaj", "आज", "abhi", "अभी")


def current_time_context():
    now = datetime.now(REMINDER_TZ)
    return (
        "Abhi ka asli samay (India, IST): "
        f"{now.strftime('%A, %d %B %Y, %I:%M %p')}. "
        "Samay ya tareekh poochhe jaane par sirf yahi use karein, andaza na lagayein."
    )


def answer_time_query(transcript):
    """Time / date ka sawal ho to (speech, display), warna None."""
    text = (transcript or "").lower()
    if detect_reminder_intent(text):
        return None   # "3 baje ka reminder" time ka sawal nahi
    asks = _contains_any(text, _ASK_WORDS) or "?" in text
    wants_time = _contains_any(text, _TIME_WORDS) or "कितने बजे" in text
    wants_date = _contains_any(text, _DATE_WORDS)
    if not asks or not (wants_time or wants_date):
        return None
    # "din" akela bahut aam shabd hai: "aaj ka din kaisa" jaisi baat time query nahi
    if wants_date and not wants_time and not _contains_any(
            text, ("date", "डेट", "tareekh", "tarikh", "तारीख", "तारीख़", "kaun sa din", "कौन सा दिन", "which day", "what day")):
        return None
    now = datetime.now(REMINDER_TZ)
    h, m = now.hour, now.minute
    part = "सुबह" if 4 <= h < 12 else "दोपहर" if 12 <= h < 16 else "शाम" if 16 <= h < 20 else "रात"
    h12 = h % 12 or 12
    clock = f"{h12} बजे" if m == 0 else f"{h12} बजकर {m} मिनट"
    date_words = f"{_HINDI_WEEKDAYS[now.weekday()]}, {now.day} {_HINDI_MONTHS[now.month - 1]} {now.year}"
    if wants_time and wants_date:
        speech = f"अभी {part} के {clock} हुए हैं। आज {date_words} है।"
    elif wants_time:
        speech = f"अभी {part} के {clock} हुए हैं।"
    else:
        speech = f"आज {date_words} है।"
    display = f"{now.strftime('%I:%M %p').lstrip('0')}\n{now.strftime('%a, %d %b %Y')}"
    return speech, display


# ---------------------------------------------------------------
# Meeting mode
# ---------------------------------------------------------------
MEETING_MAX_SECONDS = _env_int("MEETING_MAX_SECONDS", 3600)   # 1 ghanta max
ACTIVE_MEETINGS = {}   # device_id -> meeting dict (reconnect par bhi chalta rahe)
LAST_MEETINGS = {}     # device_id -> pichhli meeting ki .txt file

_MEETING_WORDS = ("meeting", "mitting", "miting", "meting", "metting", "meetings",
                  "मीटिंग", "मिटिंग", "मीटींग", "मिटींग",
                  "recording", "रिकॉर्डिंग", "रिकॉर्ड", "record")
_MEETING_ON_WORDS = ("on", "ऑन", "start", "स्टार्ट", "shuru", "शुरू", "chalu", "चालू", "karo", "करो", "kar do", "begin")
_MEETING_OFF_WORDS = ("off", "ऑफ", "band", "बंद", "बन्द", "stop", "स्टॉप", "khatam", "खत्म", "ख़त्म", "end", "save", "सेव", "roko", "रोको")
_MEETING_SUMMARY_WORDS = ("summary", "सारांश", "समरी", "notes", "नोट्स", "pichhli", "पिछली", "last")


def is_meeting_start(text):
    t = (text or "").lower()
    return (_contains_any(t, _MEETING_WORDS) and _contains_any(t, _MEETING_ON_WORDS)
            and not _contains_any(t, _MEETING_OFF_WORDS)
            and not _contains_any(t, _MEETING_SUMMARY_WORDS))


def is_meeting_stop(text):
    t = (text or "").lower()
    return _contains_any(t, _MEETING_WORDS) and _contains_any(t, _MEETING_OFF_WORDS)


async def ai_meeting_intent(text, in_meeting=False):
    """Whisper ne bigaad diya ("Mitting should pour" = meeting shuru karo)?
    Meeting jaisa shabd ho to AI se poochhein. Return start|stop|summary|none."""
    t = (text or "").lower()
    if not _contains_any(t, _MEETING_WORDS) and not re.search(r"\bm[eiu]+t+[ie]*n", t) \
            and not re.search(r"(मीट|मिट|मुट)", t):
        return "none"
    if not llm_api_key():
        return "none"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await llm_post(client, json_body={
                "model": "gpt-4o-mini",
                "temperature": 0,
                "max_tokens": 20,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": (
                        ("A meeting is being RECORDED right now; a short command that sounds even roughly "
                         "like 'meeting band karo / meeting stop / khatam karo / recording band' means STOP. "
                         if in_meeting else "") +
                        "A Hindi/English voice command, badly transcribed. Does the user want to "
                        "START recording a meeting (meeting shuru karo / meeting mode on), STOP it "
                        "(meeting band karo), hear the last meeting SUMMARY, or none of these "
                        "(e.g. asking when a meeting is)? Return JSON {\"intent\": \"start\"|\"stop\"|\"summary\"|\"none\"}."
                    )},
                    {"role": "user", "content": text},
                ],
            })
            response.raise_for_status()
            intent = json.loads(response.json()["choices"][0]["message"]["content"]).get("intent", "none")
        logger.info("Meeting intent (AI): %r -> %s", text, intent)
        return intent if intent in ("start", "stop", "summary") else "none"
    except Exception:
        logger.exception("Meeting intent AI failed")
        return "none"


def is_meeting_summary(text):
    t = (text or "").lower()
    return _contains_any(t, ("meeting", "मीटिंग", "मिटिंग")) and _contains_any(t, _MEETING_SUMMARY_WORDS)


# ---------------------------------------------------------------
# MoM (minutes of meeting) bhejna: Email (SMTP) + WhatsApp (CallMeBot)
# .env:
#   MOM_EMAIL_TO=a@x.com,b@y.com      MOM_SMTP_USER=you@gmail.com
#   MOM_SMTP_PASSWORD=<gmail app password>   (MOM_SMTP_HOST/PORT optional)
#   MOM_WHATSAPP_PHONE=+91XXXXXXXXXX  MOM_WHATSAPP_APIKEY=<callmebot key>
#   MOM_AUTO_SEND=1   (meeting band hote hi bhejein)
# ---------------------------------------------------------------
import smtplib
from email.message import EmailMessage


import html as _html


# ---------------- Meeting: poori recording ka behtar transcript ----------------
# .env (sab optional):
#   MEETING_STT_ENGINE=groq|openai|local   (default: GROQ_API_KEY ho to groq, warna local)
#   MEETING_LANGUAGE=hi        (hi = Hindi/Hinglish; auto = khud pehchane)
#   MEETING_WHISPER_MODEL=small  (local ke liye: base / small / medium)
#   MEETING_STT_PROMPT=Pratham Services, Collections Co., ...  (naam/shabd jo aksar aate hain)
#   MOM_LANGUAGE=english | hinglish
#   MOM_ATTACH_AUDIO=1   (WAV bhi email mein, 20 MB tak)
MEETING_FAST_MODEL = None
MEETING_FAST_MODEL_NAME = None


def _meeting_fast_model():
    global MEETING_FAST_MODEL, MEETING_FAST_MODEL_NAME
    name = _pratham_setting("MEETING_WHISPER_MODEL") or "small"
    if MEETING_FAST_MODEL is not None and MEETING_FAST_MODEL_NAME == name:
        return MEETING_FAST_MODEL
    try:
        from faster_whisper import WhisperModel as _MeetingWhisper
        logger.info("Meeting: faster-whisper '%s' load ho raha hai (pehli baar thoda time lagega)", name)
        MEETING_FAST_MODEL = _MeetingWhisper(name, device="cpu", compute_type="int8",
                                             cpu_threads=max(1, (os.cpu_count() or 2) - 1))
        MEETING_FAST_MODEL_NAME = name
        return MEETING_FAST_MODEL
    except Exception:
        logger.exception("Meeting model '%s' load nahi hua; chalu model use hoga", name)
        MEETING_FAST_MODEL_NAME = "base"
        return FAST_WHISPER_MODEL


def _read_wav_float(path):
    with wave.open(path, "rb") as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        raw = w.readframes(n)
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    return audio, sr


def _meeting_prompt():
    extra = (_pratham_setting("MEETING_STT_PROMPT") or "").strip()
    return ("Office meeting, Hindi aur English mix. " + extra).strip()


def _transcribe_meeting_local(audio, language):
    model = _meeting_fast_model()
    if model is None:
        return ""
    with WHISPER_LOCK:
        segments, _info = model.transcribe(
            audio,
            language=language,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=True,
            initial_prompt=_meeting_prompt(),
            no_repeat_ngram_size=3,
            temperature=(0.0, 0.2, 0.4),
        )
        lines = [_collapse_repeats(seg.text.strip()) for seg in segments if seg.text.strip()]
    return "\n".join(l for l in lines if l)


async def transcribe_meeting_wav(path):
    """Poori meeting WAV ko dobara (behtar model se) transcribe karein.
    Return (text, engine_label). Fail par ("", None)."""
    try:
        audio, sr = await asyncio.to_thread(_read_wav_float, path)
    except Exception:
        logger.exception("Meeting WAV padh nahi paye: %s", path)
        return "", None
    if audio.size < sr:
        return "", None
    peak = float(np.max(np.abs(audio))) or 1.0
    if peak < 0.5:
        audio = np.clip(audio * min(0.9 / peak, 8.0), -1.0, 1.0)
    language = (_pratham_setting("MEETING_LANGUAGE") or "hi").strip()
    if language.lower() in ("auto", "none", ""):
        language = None
    engine = (_pratham_setting("MEETING_STT_ENGINE") or ("groq" if _groq_key() else "local")).lower()
    if engine in ("groq", "openai"):
        chunk = 120 * sr          # 2 minute ke tukde (API file limit se kaafi neeche)
        parts, ok = [], True
        for i in range(0, audio.size, chunk):
            piece = audio[i:i + chunk]
            if piece.size < sr // 2:
                continue
            prompt = _meeting_prompt() + (" " + parts[-1][-200:] if parts else "")
            text = await openai_transcribe(piece, prompt, engine, language=language, timeout=90)
            if text is None:
                ok = False
                break
            if text.strip():
                parts.append(_collapse_repeats(text.strip()))
        if ok and parts:
            return "\n".join(parts), f"{engine} whisper"
        logger.warning("Meeting: %s STT nahi chala; local model se transcribe", engine)
    text = await asyncio.to_thread(_transcribe_meeting_local, audio, language)
    if text:
        return text, f"faster-whisper {MEETING_FAST_MODEL_NAME or 'base'}"
    return "", None


def _as_list(value):
    if not value:
        return []
    if isinstance(value, str):
        return [v.strip(" -•\t") for v in value.splitlines() if v.strip(" -•\t")]
    return [str(v).strip() for v in value if str(v).strip()]


async def generate_mom(transcript, meta):
    """AI se professional MoM (JSON). Return dict ya None."""
    if not transcript.strip() or not llm_api_key():
        return None
    lang = (_pratham_setting("MOM_LANGUAGE") or "english").lower()
    out_lang = ("clear, professional business English" if lang.startswith("en")
                else "simple Roman Hinglish (Hindi in English letters)")
    want_clean = len(transcript) <= 7000
    system = (
        "You are an executive assistant writing Minutes of Meeting (MoM) from a speech-to-text "
        "transcript of an Indian office meeting (Hindi/English mix). The transcript is noisy: "
        "words may be misspelt or misheard; infer the intended meaning carefully. "
        f"Meeting date: {meta['date']}, start {meta['time']}, duration about {meta['minutes']} min. "
        f"Write the MoM in {out_lang}. Never invent facts, names, numbers or dates; if an owner "
        "or deadline is not stated write \"TBD\". Return ONLY JSON with keys: "
        "\"title\" (max 8 words), "
        "\"summary\" (2-3 sentence overview), "
        "\"participants\" (names mentioned, list, may be empty), "
        "\"discussion\" (list of key discussion points), "
        "\"decisions\" (list), "
        "\"actions\" (list of {\"owner\", \"task\", \"due\"}), "
        "\"next_steps\" (list), "
        "\"open_questions\" (list), "
        "\"speech\" (2 short sentences in Hindi Devanagari summarising the meeting, for a speaker), "
        + ("\"clean_transcript\" (the transcript rewritten line by line in Roman Hinglish, obvious "
           "speech-to-text errors fixed, same meaning, nothing added)."
           if want_clean else "\"clean_transcript\": \"\".")
    )
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await llm_post(client, json_body={
                "model": "gpt-4o-mini",
                "temperature": 0.2,
                "max_tokens": 3500,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": transcript[-14000:]},
                ],
            })
            response.raise_for_status()
            data = json.loads(response.json()["choices"][0]["message"]["content"])
    except Exception:
        logger.exception("MoM generate failed")
        return None
    actions = []
    for a in data.get("actions") or []:
        if isinstance(a, dict):
            actions.append({"owner": str(a.get("owner") or "TBD").strip(),
                            "task": str(a.get("task") or "").strip(),
                            "due": str(a.get("due") or "TBD").strip()})
        elif str(a).strip():
            actions.append({"owner": "TBD", "task": str(a).strip(), "due": "TBD"})
    return {
        "title": str(data.get("title") or "Team meeting").strip()[:80],
        "summary": str(data.get("summary") or "").strip(),
        "participants": _as_list(data.get("participants")),
        "discussion": _as_list(data.get("discussion")),
        "decisions": _as_list(data.get("decisions")),
        "actions": [a for a in actions if a["task"]],
        "next_steps": _as_list(data.get("next_steps")),
        "open_questions": _as_list(data.get("open_questions")),
        "speech": str(data.get("speech") or "").strip(),
        "clean_transcript": str(data.get("clean_transcript") or "").strip(),
    }


def mom_to_text(mom, meta, raw_transcript):
    mom = mom or {}
    L = ["MINUTES OF MEETING",
         f"Title: {mom.get('title') or 'Meeting'}",
         f"Date: {meta['date']} | Time: {meta['time']} | Duration: {meta['minutes']} min | Device: {meta['device']}"]
    if mom.get("participants"):
        L.append("Participants: " + ", ".join(mom["participants"]))
    L.append("")

    def sec(name, items):
        if items:
            L.append(name)
            L.extend(f"- {i}" for i in items)
            L.append("")
    sec("SUMMARY", [mom["summary"]] if mom.get("summary") else [])
    sec("KEY DISCUSSION POINTS", mom.get("discussion"))
    sec("DECISIONS", mom.get("decisions"))
    if mom.get("actions"):
        L.append("ACTION ITEMS")
        for n, a in enumerate(mom["actions"], 1):
            L.append(f"{n}. {a['task']}  |  Owner: {a['owner']}  |  Due: {a['due']}")
        L.append("")
    sec("NEXT STEPS", mom.get("next_steps"))
    sec("OPEN QUESTIONS", mom.get("open_questions"))
    if mom.get("clean_transcript"):
        L += ["TRANSCRIPT (cleaned)", mom["clean_transcript"], ""]
    L += [f"RAW TRANSCRIPT ({meta.get('engine') or 'speech-to-text'})",
          raw_transcript or "(kuch sunai nahi diya)", ""]
    return "\n".join(L)


def mom_to_html(mom, meta, raw_transcript, for_email=False):
    e = _html.escape
    mom = mom or {}
    ACC, INK, MUTED, LINE = "#E8742A", "#1d2430", "#6b7280", "#e5e7eb"
    font = "font-family:'Segoe UI',Roboto,Arial,sans-serif;"

    def heading(text):
        return (f'<tr><td style="padding:22px 28px 6px;{font}font-size:12px;font-weight:700;'
                f'letter-spacing:.08em;text-transform:uppercase;color:{ACC};">{e(text)}</td></tr>')

    def bullets(items):
        lis = "".join(f'<li style="margin:0 0 6px;">{e(i)}</li>' for i in items)
        return (f'<tr><td style="padding:0 28px;{font}font-size:15px;line-height:1.6;color:{INK};">'
                f'<ul style="margin:0;padding-left:20px;">{lis}</ul></td></tr>')

    rows = []
    if mom.get("summary"):
        rows.append(heading("Summary"))
        rows.append(f'<tr><td style="padding:0 28px;{font}font-size:15px;line-height:1.6;color:{INK};">'
                    f'{e(mom["summary"])}</td></tr>')
    for title, key in (("Key discussion points", "discussion"), ("Decisions", "decisions")):
        if mom.get(key):
            rows += [heading(title), bullets(mom[key])]
    if mom.get("actions"):
        th = f'style="text-align:left;padding:10px 12px;border-bottom:2px solid {LINE};{font}font-size:12px;color:{MUTED};text-transform:uppercase;letter-spacing:.05em;"'
        trs = ""
        for n, a in enumerate(mom["actions"], 1):
            td = f'style="padding:10px 12px;border-bottom:1px solid {LINE};{font}font-size:14px;color:{INK};vertical-align:top;"'
            trs += (f'<tr><td {td}>{n}</td><td {td}>{e(a["task"])}</td>'
                    f'<td {td}><b>{e(a["owner"])}</b></td><td {td}>{e(a["due"])}</td></tr>')
        rows.append(heading("Action items"))
        rows.append(f'<tr><td style="padding:0 28px;"><table role="presentation" width="100%" cellpadding="0" '
                    f'cellspacing="0" style="border-collapse:collapse;"><tr><th {th}>#</th><th {th}>Task</th>'
                    f'<th {th}>Owner</th><th {th}>Due</th></tr>{trs}</table></td></tr>')
    for title, key in (("Next steps", "next_steps"), ("Open questions", "open_questions")):
        if mom.get(key):
            rows += [heading(title), bullets(mom[key])]
    transcript = mom.get("clean_transcript") or raw_transcript or ""
    if transcript:
        if for_email and len(transcript) > 3000:
            transcript = transcript[:3000] + "\n... (poora transcript attachment mein)"
        rows.append(heading("Transcript" + (" (cleaned)" if mom.get("clean_transcript") else "")))
        rows.append(f'<tr><td style="padding:0 28px;"><div style="background:#f9fafb;border:1px solid {LINE};'
                    f'border-radius:8px;padding:14px 16px;{font}font-size:13px;line-height:1.6;color:#374151;'
                    f'white-space:pre-wrap;">{e(transcript)}</div></td></tr>')

    meta_line = " &nbsp;·&nbsp; ".join(e(x) for x in (
        meta["date"], meta["time"], f"{meta['minutes']} min",
        ("Participants: " + ", ".join(mom["participants"])) if mom.get("participants") else ""
    ) if x)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{e(mom.get("title") or "Minutes of Meeting")}</title></head>'
        '<body style="margin:0;padding:0;background:#f3f4f6;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 10px;">'
        '<tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:680px;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb;">'
        f'<tr><td style="background:{INK};padding:26px 28px;">'
        f'<div style="{font}font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#FFB27A;">Minutes of meeting</div>'
        f'<div style="{font}font-size:24px;font-weight:600;line-height:1.3;color:#ffffff;margin-top:6px;">{e(mom.get("title") or "Meeting")}</div>'
        '</td></tr>'
        f'<tr><td style="padding:12px 28px;background:#fff7ed;border-bottom:1px solid #fde4cc;{font}font-size:13px;color:#7c4a1e;">{meta_line}</td></tr>'
        + "".join(rows) +
        f'<tr><td style="padding:28px;{font}font-size:12px;color:{MUTED};border-top:1px solid {LINE};margin-top:20px;">'
        f'Recorded and summarised by PrathamSmart ({e(meta["device"])}). AI-generated minutes: please verify names, '
        f'numbers and dates.</td></tr>'
        '</table></td></tr></table></body></html>'
    )


def _mom_parts(txt_path):
    """Return (subject, short_text, full_text, html_or_None)."""
    base = txt_path[:-4] if txt_path.endswith(".txt") else txt_path
    with open(txt_path, encoding="utf-8") as fh:
        full = fh.read()
    mom, meta = None, None
    try:
        with open(base + ".json", encoding="utf-8") as fh:
            saved = json.load(fh)
            mom, meta = saved.get("mom"), saved.get("meta")
    except (OSError, ValueError):
        pass
    if meta:
        title = (mom or {}).get("title") or "Meeting"
        subject = f"MoM: {title} | {meta['date']}"
        short = [title, f"{meta['date']}, {meta['time']} ({meta['minutes']} min)"]
        if mom and mom.get("summary"):
            short += ["", mom["summary"]]
        if mom and mom.get("actions"):
            short += ["", "Action items:"] + [f"{n}. {a['task']} ({a['owner']}, {a['due']})"
                                             for n, a in enumerate(mom["actions"], 1)]
        html_body = mom_to_html(mom, meta, saved.get("raw_transcript", ""), for_email=True)
        return subject, "\n".join(short), full, html_body
    header = full.splitlines()[0] if full else "Meeting"
    short = full.split("TRANSCRIPT")[0].strip() or header
    subject = "MoM - " + header.split("|")[0].replace("Meeting:", "").strip()
    return subject, short, full, None


def _send_mom_email_sync(txt_path):
    to_list = [a.strip() for a in (_pratham_setting("MOM_EMAIL_TO") or "").split(",") if a.strip()]
    user = _pratham_setting("MOM_SMTP_USER")
    password = _pratham_setting("MOM_SMTP_PASSWORD")
    if not to_list or not user or not password:
        return False, "email set nahi (MOM_EMAIL_TO / MOM_SMTP_USER / MOM_SMTP_PASSWORD)"
    host = _pratham_setting("MOM_SMTP_HOST") or "smtp.gmail.com"
    port = int(_pratham_setting("MOM_SMTP_PORT") or 587)
    subject, short, full, html_body = _mom_parts(txt_path)
    base = txt_path[:-4]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"PrathamSmart <{user}>"
    msg["To"] = ", ".join(to_list)
    msg.set_content("Namaste,\n\nMinutes of meeting (PrathamSmart):\n\n" + short +
                    "\n\nPoora MoM aur transcript attachment mein hai.\n\n- PrathamSmart")
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    stamp = os.path.basename(base)
    if os.path.isfile(base + ".html"):
        with open(base + ".html", "rb") as fh:
            msg.add_attachment(fh.read(), maintype="text", subtype="html", filename=f"MoM_{stamp}.html")
    msg.add_attachment(full.encode("utf-8"), maintype="text", subtype="plain", filename=f"MoM_{stamp}.txt")
    if (_pratham_setting("MOM_ATTACH_AUDIO") or "0") == "1" and os.path.isfile(base + ".wav") \
            and os.path.getsize(base + ".wav") < 20 * 1024 * 1024:
        with open(base + ".wav", "rb") as fh:
            msg.add_attachment(fh.read(), maintype="audio", subtype="wav", filename=f"{stamp}.wav")
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)
    return True, f"email: {len(to_list)}"


async def send_mom_email(txt_path):
    try:
        return await asyncio.to_thread(_send_mom_email_sync, txt_path)
    except Exception as err:
        logger.exception("MoM email failed")
        return False, f"email error: {type(err).__name__}"


async def send_mom_whatsapp(txt_path):
    """CallMeBot: free, lekin sirf apne (registered) WhatsApp number par."""
    phone = _pratham_setting("MOM_WHATSAPP_PHONE")
    apikey = _pratham_setting("MOM_WHATSAPP_APIKEY")
    if not phone or not apikey:
        return False, "whatsapp set nahi (MOM_WHATSAPP_PHONE / MOM_WHATSAPP_APIKEY)"
    subject, short, _full, _html_body = _mom_parts(txt_path)
    text = f"*{subject}*\n\n{short}"[:1500]
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(
                "https://api.callmebot.com/whatsapp.php",
                params={"phone": phone, "text": text, "apikey": apikey},
            )
        ok = res.status_code == 200 and "error" not in res.text.lower()[:200]
        if not ok:
            logger.warning("MoM WhatsApp failed: HTTP %s %s", res.status_code, res.text[:200])
        return ok, "whatsapp" if ok else f"whatsapp HTTP {res.status_code}"
    except Exception as err:
        logger.exception("MoM WhatsApp failed")
        return False, f"whatsapp error: {type(err).__name__}"


_MOM_SEND_WORDS = ("mom", "एमओएम", "minutes", "notes", "नोट्स", "summary", "सारांश")
_MOM_CHANNEL_WORDS = ("mail", "email", "ईमेल", "मेल", "whatsapp", "व्हाट्सएप", "वॉट्सऐप", "bhejo", "भेजो", "send", "bhej do", "भेज दो")


def is_mom_send(text):
    t = (text or "").lower()
    return _contains_any(t, _MOM_SEND_WORDS + ("meeting", "मीटिंग")) and _contains_any(t, _MOM_CHANNEL_WORDS)


# ---------------------------------------------------------------
# Voice email: "Atul ko mail likho ki ..." -> Gmail draft -> "haan bhej do" -> send
# .env:  MOM_SMTP_USER / MOM_SMTP_PASSWORD (wahi Gmail app password)
#        MAIL_CONTACTS=atul:atul@example.com, office:info@example.com
#        (ya media/mail_contacts.json: {"atul": "atul@example.com"})
# ---------------------------------------------------------------
import imaplib
import email.utils as _email_utils

_MAIL_WORDS = ("mail", "email", "e-mail", "ईमेल", "मेल", "ई-मेल", "gmail", "जीमेल")
_MAIL_ACTION_WORDS = ("likho", "likh", "likhna", "लिखो", "लिख", "लिखना", "bhejo", "bhej", "भेजो", "भेज",
                      "send", "draft", "ड्राफ्ट", "banao", "बनाओ", "compose", "write")
_MAIL_YES = ("haan", "han", "ha ", "हाँ", "हां", "हा", "yes", "send", "bhej", "भेज", "kar do", "कर दो", "ok", "okay",
             "theek", "ठीक", "sure", "jarur", "zaroor", "ज़रूर", "जरूर",
             " ji ", " जी ", "हान", "भेजो", "ہاں", "ہاں", "ہان", "ہا ", "جی", "بھیج", "ٹھیک", "اوکے")
_MAIL_NO = ("nahi", "nahin", "नहीं", "नही", " no ", "cancel", "कैंसल", " mat ", " मत ", "rehne do", "रहने दो",
            "ruko", "रुको", "نہیں", "نہی", "مت ")


def is_mail_compose(text):
    t = " " + (text or "").lower() + " "
    # MoM wala alag raasta: "meeting ka MoM mail karo", "meeting notes bhejo"
    if _contains_any(t, ("mom", "एमओएम", "minutes", "notes", "नोट्स", "summary", "सारांश")) or \
            re.search(r"(meeting|मीटिंग)\s+(ka|ki|ke|का|की|के)\s+(mail|email|मेल|ईमेल)", t):
        return False
    if not _contains_any(t, _MAIL_WORDS):
        return False
    if _contains_any(t, _MAIL_ACTION_WORDS):
        return True
    # "Atul ko mail karo ki ..." (kisi ko + baat)
    return bool(re.search(r"\s(ko|को)\s.*(mail|email|मेल|ईमेल).*\s(ki|कि|that)\s", t))


def mail_contacts():
    contacts = {}
    raw = _pratham_setting("MAIL_CONTACTS") or ""
    for part in re.split(r"[,;\n]", raw):
        if ":" in part or "=" in part:
            name, addr = re.split(r"[:=]", part, 1)
            if "@" in addr:
                contacts[name.strip().lower()] = addr.strip()
    media_dir = getattr(settings, "MEDIA_ROOT", None) or os.path.join(os.getcwd(), "media")
    try:
        with open(os.path.join(str(media_dir), "mail_contacts.json"), encoding="utf-8") as fh:
            for k, v in (json.load(fh) or {}).items():
                if "@" in str(v):
                    contacts[str(k).strip().lower()] = str(v).strip()
    except (OSError, ValueError):
        pass
    # Django users (admin panel) jinka email bhara hai: "atul sharma", "atul"
    if (_pratham_setting("MAIL_CONTACTS_FROM_USERS") or "1") == "1":
        try:
            from django.contrib.auth import get_user_model
            for u in get_user_model().objects.exclude(email="").exclude(email__isnull=True)[:500]:
                full = f"{u.first_name} {u.last_name}".strip().lower()
                for key in (full, u.get_username().lower()):
                    if key and key not in contacts:
                        contacts[key] = u.email
        except Exception:
            logger.debug("Mail contacts from users failed", exc_info=True)
    return contacts


from asgiref.sync import sync_to_async  # (neeche bhi import hai; yahan pehle chahiye)
mail_contacts_async = sync_to_async(mail_contacts, thread_sensitive=True)

_MAIL_FUZZY = re.compile(r"(mail|mel\b|meil|e-?mail|ईमेल|मेल|gmail|जीमेल)", re.I)


async def ai_is_mail_compose(text):
    """'atulpo mail ka no' jaisa bigda command: AI se poochhein kya ye mail likhwana hai."""
    if not _MAIL_FUZZY.search(text or "") or not llm_api_key():
        return False
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            res = await llm_post(client, json_body={
                "model": "gpt-4o-mini", "temperature": 0, "max_tokens": 20,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": (
                        "Hindi/English voice command, badly transcribed (e.g. 'atulpo mail ka no' = "
                        "'Atul ko mail karo'). Is the user asking to WRITE/SEND an email to someone "
                        "(not about meeting minutes/MoM, not asking to read or check mail)? "
                        "Return JSON {\"compose\": true|false}.")},
                    {"role": "user", "content": text},
                ],
            })
            res.raise_for_status()
            ok = bool(json.loads(res.json()["choices"][0]["message"]["content"]).get("compose"))
        logger.info("Mail intent (AI): %r -> %s", text, ok)
        return ok
    except Exception:
        logger.debug("Mail intent AI failed", exc_info=True)
        return False


def resolve_contacts(name, contacts):
    """Naam se milte contacts: [(naam, email), ...] (ek email ek baar)."""
    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    if not n:
        return []
    if "@" in n:
        return [(n.replace(" ", ""), n.replace(" ", ""))]
    if n in contacts:
        return [(n, contacts[n])]
    words = [w for w in n.split() if len(w) >= 2]
    out, seen = [], set()
    for k, v in contacts.items():
        kw = k.split()
        hit = all(any(w == x or (len(w) >= 3 and x.startswith(w)) for x in kw) for w in words) or n in k or (len(k) >= 3 and k in n)
        if hit and v.lower() not in seen:
            seen.add(v.lower())
            out.append((k, v))
    return out


_PICK_WORDS = {
    0: ("pehla", "pehle", "first", "one", "ek", "पहला", "पहले", "एक", "1"),
    1: ("doosra", "dusra", "second", "two", "do", "दूसरा", "दो", "2"),
    2: ("teesra", "tisra", "third", "three", "teen", "तीसरा", "तीन", "3"),
}


def pick_contact(text, cands):
    t = " " + re.sub(r"[.,!?।]", " ", (text or "").lower()) + " "
    for idx, words in _PICK_WORDS.items():
        if idx < len(cands) and any(f" {w} " in t for w in words):
            return idx
    scores = []
    for i, (k, v) in enumerate(cands):
        extra = [w for w in k.split() if len(w) >= 3]
        scores.append(sum(1 for w in extra if w in t) + (2 if v.split("@")[0].lower() in t else 0))
    best = max(scores) if scores else 0
    if best and scores.count(best) == 1:
        return scores.index(best)
    return None


async def ai_compose_mail(transcript, contact_names):
    if not llm_api_key():
        return None
    lang = (_pratham_setting("MAIL_LANGUAGE") or "english").lower()
    out_lang = "professional English" if lang.startswith("en") else "polite Roman Hinglish"
    sender = (_pratham_setting("MAIL_SENDER_NAME") or "").strip()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await llm_post(client, json_body={
                "model": "gpt-4o-mini", "temperature": 0.3, "max_tokens": 700,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": (
                        "The user dictated (Hindi/English voice, may have speech-to-text errors) an email to write. "
                        f"Known contact names: {', '.join(contact_names) or 'none'}. "
                        "Return JSON {\"to_name\": recipient name as said (Roman letters, match a known contact "
                        "if it sounds similar), \"to_email\": email address only if the user spelled one out, else \"\", "
                        f"\"subject\": short clear subject line (always fill it), \"body\": the full email in {out_lang} "
                        "with greeting and sign-off" + (f" ending with 'Regards,\\n{sender}'" if sender else
                        " ending with 'Regards,' (no name placeholder)") + ", "
                        "\"summary_hi\": one short Hindi Devanagari sentence saying what the mail says}. "
                        "Do not invent facts beyond what the user said. If the user did NOT say what the mail "
                        "should say (only who to mail), return \"body\": \"\" and \"subject\": \"\".")},
                    {"role": "user", "content": transcript},
                ],
            })
            res.raise_for_status()
            data = json.loads(res.json()["choices"][0]["message"]["content"])
            return {k: str(data.get(k) or "").strip() for k in ("to_name", "to_email", "subject", "body", "summary_hi")}
    except Exception:
        logger.exception("Mail compose AI failed")
        return None


def _mail_account():
    user = _pratham_setting("MAIL_USER") or _pratham_setting("MOM_SMTP_USER")
    password = _pratham_setting("MAIL_PASSWORD") or _pratham_setting("MOM_SMTP_PASSWORD")
    return user, password


def build_mail(to_addr, subject, body):
    user, _pw = _mail_account()
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject or "(no subject)"
    msg["Date"] = _email_utils.formatdate(localtime=True)
    msg["Message-ID"] = _email_utils.make_msgid()
    msg.set_content(body)
    return msg


def gmail_save_draft_sync(msg):
    """Gmail Drafts mein save (IMAP, wahi app password). Return (ok, info)."""
    user, password = _mail_account()
    if not user or not password:
        return False, "MOM_SMTP_USER / MOM_SMTP_PASSWORD set nahi"
    host = _pratham_setting("MAIL_IMAP_HOST") or "imap.gmail.com"
    with imaplib.IMAP4_SSL(host, timeout=20) as imap:
        imap.login(user, password)
        folder = '"[Gmail]/Drafts"'
        try:
            typ, boxes = imap.list()
            for line in boxes or []:
                text = line.decode(errors="ignore")
                if "\\Drafts" in text:
                    folder = text.split(' "/" ')[-1].strip()
                    break
        except Exception:
            pass
        typ, _ = imap.append(folder, "\\Draft", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        return typ == "OK", folder


def gmail_delete_draft_sync(message_id, folder):
    """Bhejne ke baad wahi draft Gmail Drafts se hata dein (Message-ID se dhoondh kar)."""
    user, password = _mail_account()
    if not (user and password and message_id and folder):
        return False
    host = _pratham_setting("MAIL_IMAP_HOST") or "imap.gmail.com"
    with imaplib.IMAP4_SSL(host, timeout=20) as imap:
        imap.login(user, password)
        typ, _ = imap.select(folder)
        if typ != "OK":
            return False
        typ, data = imap.search(None, "HEADER", "Message-ID", message_id.strip("<>"))
        ids = (data[0] or b"").split() if typ == "OK" else []
        for num in ids:
            imap.store(num, "+FLAGS", "\\Deleted")
        if ids:
            imap.expunge()
        return bool(ids)


def send_mail_sync(msg):
    user, password = _mail_account()
    if not user or not password:
        return False, "MOM_SMTP_USER / MOM_SMTP_PASSWORD set nahi"
    host = _pratham_setting("MOM_SMTP_HOST") or "smtp.gmail.com"
    port = int(_pratham_setting("MOM_SMTP_PORT") or 587)
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)
    return True, "sent"


# ---------------------------------------------------------------
# Assistant ka naam: .env ASSISTANT_NAME=Tulsi (default "Pratham"),
# ya device par bolkar: "tumhara naam Tulsi rakho"
# ---------------------------------------------------------------
_ASSISTANT_NAMES_CACHE = None


def _names_file():
    media_dir = getattr(settings, "MEDIA_ROOT", os.path.join(os.getcwd(), "media"))
    return os.path.join(str(media_dir), "assistant_names.json")


def get_assistant_name(device_id):
    global _ASSISTANT_NAMES_CACHE
    if _ASSISTANT_NAMES_CACHE is None:
        try:
            with open(_names_file(), encoding="utf-8") as fh:
                _ASSISTANT_NAMES_CACHE = json.load(fh)
        except Exception:
            _ASSISTANT_NAMES_CACHE = {}
    return _ASSISTANT_NAMES_CACHE.get(device_id) or _pratham_setting("ASSISTANT_NAME") or "Pratham"


def set_assistant_name(device_id, name):
    global _ASSISTANT_NAMES_CACHE
    get_assistant_name(device_id)
    _ASSISTANT_NAMES_CACHE[device_id] = name
    try:
        os.makedirs(os.path.dirname(_names_file()), exist_ok=True)
        with open(_names_file(), "w", encoding="utf-8") as fh:
            json.dump(_ASSISTANT_NAMES_CACHE, fh, ensure_ascii=False, indent=1)
    except Exception:
        logger.exception("Assistant name save failed")


_NAME_ASK = ("tumhara naam", "tera naam", "aapka naam", "your name", "तुम्हारा नाम", "आपका नाम", "तेरा नाम", "who are you", "kaun ho", "कौन हो")
_NAME_SET = re.compile(
    r"(?:naam|name|नाम)\s+(?:ab\s+|अब\s+)?([A-Za-z\u0900-\u097F]{2,20})\s+(?:rakho|rakh do|rakhdo|kar do|karo|रखो|रख दो|करो|कर दो)"
    r"|(?:call yourself|your name is|name you)\s+([A-Za-z]{2,20})",
    re.IGNORECASE,
)


def parse_name_command(text):
    """('set', name) | ('ask', None) | None"""
    t = (text or "").strip()
    m = _NAME_SET.search(t)
    if m:
        name = (m.group(1) or m.group(2) or "").strip(" .,!?।")
        if name and name.lower() not in ("mera", "tumhara", "apna", "मेरा", "तुम्हारा", "kya", "क्या"):
            return "set", name[:1].upper() + name[1:]
    if _contains_any(t.lower(), _NAME_ASK):
        return "ask", None
    return None


# ---------------------------------------------------------------
# Voice commands: mute / unmute / volume
# ---------------------------------------------------------------
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_VOLUME_WORDS = (
    "volume", "valume", "volum", "वॉल्यूम", "वॉल्युम", "वोल्यूम", "वोल्युम",
    "आवाज", "आवाज़", "awaaz", "awaz", "aawaz", "sound", "साउंड",
)
_PERCENT_WORDS = ("%", "percent", "per cent", "प्रतिशत", "परसेंट", "पर्सेंट", "pratishat")
_UNMUTE_WORDS = (
    "unmute", "un mute", "अनम्यूट", "अन म्यूट", "sound on", "awaaz chalu",
    "awaz chalu", "आवाज़ चालू", "आवाज चालू", "आवाज वापस", "आवाज़ वापस",
)
_MUTE_WORDS = (
    "mute", "म्यूट", "म्युट", "chup", "चुप", "sound off", "silent", "साइलेंट",
    "awaaz band", "awaz band", "आवाज़ बंद", "आवाज बंद",
)
_UP_WORDS = (
    "badha", "badhao", "बढ़ा", "बढा", "increase", "louder", "tez", "तेज़", "तेज",
    "zyada", "ज़्यादा", "ज्यादा", "up",
)
_DOWN_WORDS = (
    "kam", "कम", "decrease", "lower", "dheere", "धीरे", "down",
)
_FULL_WORDS = ("full", "maximum", "max", "फुल", "पूरी", "पूरा", "poori", "pura")
_HALF_WORDS = ("half", "aadhi", "aadha", "आधी", "आधा", "हाफ")

_NUMBER_WORDS = {
    # English
    "zero": 0, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100,
    # Hindi (Devanagari)
    "दस": 10, "बीस": 20, "पच्चीस": 25, "तीस": 30, "चालीस": 40, "पचास": 50,
    "साठ": 60, "सत्तर": 70, "पचहत्तर": 75, "अस्सी": 80, "नब्बे": 90, "सौ": 100,
    # Hindi (Roman)
    "das": 10, "bees": 20, "pachchis": 25, "pachis": 25, "pachees": 25,
    "tees": 30, "chalis": 40, "pachas": 50, "saath": 60, "sattar": 70,
    "pachattar": 75, "pachhattar": 75, "assi": 80, "nabbe": 90, "sau": 100,
}
_ENGLISH_UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}


def _contains_any(text, words):
    """Shabd poore match hon (e.g. "kam" ko "kamra" mein na pakdein)."""
    for w in words:
        if w in ("%",):
            if w in text:
                return True
            continue
        if re.search(r"(?<![\wऀ-ॿ])" + re.escape(w) + r"(?![\wऀ-ॿ])", text):
            return True
    return False


def _find_number(text):
    """Text mein 0..100 number dhoondein (digits, English ya Hindi shabd)."""
    match = re.search(r"(?<!\d)(\d{1,3})(?!\d)", text)
    if match:
        return int(match.group(1))

    tokens = re.findall(r"[\wऀ-ॿ]+", text)
    for i, tok in enumerate(tokens):
        if tok in _NUMBER_WORDS:
            value = _NUMBER_WORDS[tok]
            # "seventy five", "twenty five"
            if 20 <= value <= 90 and i + 1 < len(tokens) and tokens[i + 1] in _ENGLISH_UNITS:
                value += _ENGLISH_UNITS[tokens[i + 1]]
            return value
    return None


def parse_device_command(transcript):
    """Mute/volume command pehchanein.
    Return (action, value, confirm_text) ya None (normal sawal hai)."""
    text = (transcript or "").lower().translate(_DEVANAGARI_DIGITS)
    text = re.sub(r"[.,!?।\"']", " ", text)
    text = " ".join(text.split())
    if not text:
        return None

    # Lambe sawal command nahi hote ("volume of a sphere kaise nikalte hain...")
    if len(text.split()) > 8:
        return None

    has_volume = _contains_any(text, _VOLUME_WORDS)

    if _contains_any(text, _UNMUTE_WORDS):
        return ("unmute", 0, "आवाज़ चालू कर दी है।")

    if _contains_any(text, _MUTE_WORDS):
        return ("mute", 0, None)

    has_percent = _contains_any(text, _PERCENT_WORDS)
    if has_volume or has_percent:
        number = _find_number(text)
        if number is not None and 0 <= number <= 100:
            if number == 0:
                return ("mute", 0, None)
            return ("volume_set", number, f"आवाज़ {number} प्रतिशत कर दी है।")

        if _contains_any(text, _FULL_WORDS):
            return ("volume_set", 100, "आवाज़ पूरी कर दी है।")
        if _contains_any(text, _HALF_WORDS):
            return ("volume_set", 50, "आवाज़ आधी कर दी है।")

    if has_volume:
        if _contains_any(text, _DOWN_WORDS):
            return ("volume_down", 25, "आवाज़ कम कर दी है।")
        if _contains_any(text, _UP_WORDS):
            return ("volume_up", 25, "आवाज़ बढ़ा दी है।")

    return None


# Live API Base URL
# ---------------------------------------------------------------
# Reminders (voice se add / list + time par device bolta hai)
# Pehle AI sirf "reminder add kar diya" BOL deta tha, database mein
# kuch save nahi hota tha. Ab asli core.Reminder row banti hai.
# ---------------------------------------------------------------
from datetime import datetime, timedelta, date as _date, time as _time
from zoneinfo import ZoneInfo

from asgiref.sync import sync_to_async
from django.apps import apps as django_apps
from django.db import models as dj_models
from django.utils import timezone as dj_timezone

REMINDER_TZ = ZoneInfo(os.getenv("REMINDER_TZ", "Asia/Kolkata"))
REMINDER_CHECK_SECONDS = _env_float("REMINDER_CHECK_SECONDS", 15)

REMINDER_INTENT_WORDS = (
    "remind", "reminder", "reminders", "रिमाइंडर", "रिमाइंडर्स", "रिमाइन्डर",
    "याद दिला", "याद दिलाना", "याद दिलाओ", "याद दिलाइए", "yaad dila",
    "alarm", "अलार्म",
)

# Model ke field naam pata nahi? Neeche ke naam mein se jo mile wahi use hoga.
_REM_TITLE_FIELDS = (
    "title", "message", "text", "note", "name", "description", "content",
    "reminder_text", "task", "subject",
)
_REM_DATETIME_FIELDS = (
    "remind_at", "reminder_time", "remind_time", "scheduled_at", "scheduled_time",
    "due_at", "due_time", "trigger_time", "trigger_at", "alarm_time", "datetime",
    "date_time", "time", "when", "reminder_datetime",
)
_REM_DATE_FIELDS = ("date", "remind_date", "reminder_date", "due_date", "scheduled_date")
_REM_TIMEONLY_FIELDS = ("time", "remind_time", "reminder_time", "due_time", "scheduled_time")
_REM_DONE_FIELDS = ("is_done", "is_completed", "completed", "is_triggered", "triggered",
                    "is_sent", "sent", "notified", "is_notified", "delivered")
_DEVICE_LOOKUP_FIELDS = ("plant_id", "device_id", "mac", "mac_address", "macid", "serial",
                         "serial_number", "chip_id", "uid", "unique_id", "name")


# ---------------------------------------------------------------
# Knowledge Base (dashboard par upload kiye documents) se jawab
# .env (optional): KB_ENABLED=1   KB_MAX_CHUNKS=5
# ---------------------------------------------------------------
_KB_STOP = set("""
a an the is are was were be to of in on for and or with what which who how when where why
do does did can could please tell me about this that it i you your my our we hai hain tha thi
ka ki ke ko se me mein par aur ya kya kaun kaise kab kahan kyon kyun bataiye batao bata dijiye
karo kar kare karna hota hoti hote ho raha rahi rahe ek koi kuch bhi to toh na nahi ji mujhe
है हैं था थी का की के को से में पर और या क्या कौन कैसे कब कहां कहाँ क्यों बताइए बताओ बता
करो कर करना होता होती होते हो रहा रही रहे एक कोई कुछ भी तो ना नहीं जी मुझे मेरा मेरी आप
""".split())


def _kb_terms(text):
    words = re.findall(r"[\wऀ-ॿ]+", (text or "").lower())
    terms = [w for w in words if len(w) >= 3 and w not in _KB_STOP and not w.isdigit()]
    return list(dict.fromkeys(terms))[:10]


_KB_ADMIN_ROLES = ("admin", "owner_admin", "owneradmin", "super_admin", "superadmin")
_KB_LINK_NAMES = ("admin", "owner_admin", "parent", "parent_admin", "created_by", "added_by",
                  "manager", "owner", "organization_admin", "company_admin", "invited_by", "user")


def _is_admin_profile(profile):
    user = getattr(profile, "user", None)
    role = str(getattr(profile, "role", "") or "").lower().replace("-", "_").replace(" ", "_")
    return role in _KB_ADMIN_ROLES or bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))


def _as_profile(obj, Profile):
    if obj is None:
        return None
    if isinstance(obj, Profile):
        return obj
    for attr in ("profile", "userprofile", "user_profile"):
        try:
            p = getattr(obj, attr, None)
        except Exception:
            p = None
        if isinstance(p, Profile):
            return p
    try:
        return Profile.objects.filter(user=obj).first()
    except Exception:
        return None


def kb_admin_profiles_for_device(device_id):
    """Device kis admin ki list mein hai? Return (profile_ids, reason).
    Device ke FK (user/owner/admin/...) -> unka profile; admin ho to wahi,
    warna us profile ke admin/parent/created_by link."""
    from django.apps import apps
    from django.contrib.auth import get_user_model
    try:
        Profile = apps.get_model("core", "UserProfile")
    except LookupError:
        return [], "UserProfile model nahi mila"
    User = get_user_model()
    dev_model = next((m for m in apps.get_app_config("core").get_models()
                      if m.__name__.lower() in ("device", "devices", "plant", "esp32device")), None)
    if dev_model is None:
        return [], "Device model nahi mila"
    device = _find_device(dev_model, device_id)
    if device is None:
        return [], f"device '{device_id}' Devices table mein nahi mila"
    linked = []
    for f in dev_model._meta.get_fields():
        if getattr(f, "many_to_one", False) and f.related_model in (User, Profile):
            try:
                linked.append((f.name, getattr(device, f.name)))
            except Exception:
                pass
        elif getattr(f, "many_to_many", False) and f.related_model in (User, Profile) and not f.auto_created:
            try:
                linked += [(f.name, o) for o in getattr(device, f.name).all()[:10]]
            except Exception:
                pass
    admins, seen = [], set()

    def add(p):
        if p is not None and p.pk not in seen:
            seen.add(p.pk)
            admins.append(p.pk)

    for fname, obj in linked:
        prof = _as_profile(obj, Profile)
        if prof is None:
            continue
        if _is_admin_profile(prof):
            add(prof)
        # is user ka admin (UserProfile par admin/parent/created_by jaisa link)
        for pf in Profile._meta.get_fields():
            if getattr(pf, "many_to_one", False) and pf.related_model in (User, Profile) \
                    and pf.name in _KB_LINK_NAMES and pf.name != "user":
                try:
                    boss = _as_profile(getattr(prof, pf.name), Profile)
                except Exception:
                    boss = None
                if boss is not None and _is_admin_profile(boss):
                    add(boss)
    if not admins:
        names = ", ".join(f"{n}={getattr(o, 'pk', o)}" for n, o in linked) or "koi user/owner link nahi"
        return [], f"device ka admin nahi mila ({names})"
    return admins, "ok"


def kb_search_sync(query, limit=5, extra_terms=None, device_id=None):
    """Enabled Knowledge Bases ke chunks mein sawal ke shabd dhoondhein.
    KB_SCOPE=admin (default): sirf us admin ke KB jiski list mein device hai.
    Return [(score, kb_name, doc_name, text), ...] sabse milta-julta pehle."""
    try:
        from django.apps import apps
        from django.db.models import Q
        Chunk = apps.get_model("core", "DocumentChunk")
        KB = apps.get_model("core", "KnowledgeBase")
    except Exception:
        return []
    terms = _kb_terms(query) + [t for t in (extra_terms or []) if t not in _KB_STOP]
    terms = list(dict.fromkeys(t.lower() for t in terms if len(t) >= 3))[:14]
    if not terms:
        return []
    kb_qs = KB.objects.all()
    if (_pratham_setting("KB_SCOPE") or "admin").lower() != "all" and device_id:
        admin_ids, why = kb_admin_profiles_for_device(device_id)
        if not admin_ids and (_pratham_setting("KB_FALLBACK") or "superadmin").lower() != "none":
            # Device kisi admin se juda nahi: main admin = Django ka pehla user (sabse chhota id)
            try:
                from django.contrib.auth import get_user_model
                Profile = apps.get_model("core", "UserProfile")
                first_user = get_user_model().objects.order_by("pk").first()
                prof = _as_profile(first_user, Profile) if first_user else None
                if prof is not None:
                    admin_ids = [prof.pk]
                    why = f"fallback: main admin (pehla user '{first_user.get_username()}')"
            except Exception:
                logger.debug("KB main-admin fallback failed", exc_info=True)
        if not admin_ids:
            logger.info("KB scope: device=%s -> koi KB nahi (%s)", device_id, why)
            return []
        logger.info("KB scope: device=%s source=%s", device_id, why)
        kb_qs = kb_qs.filter(user_id__in=admin_ids)
        logger.info("KB scope: device=%s admin_profiles=%s KBs=%s", device_id, admin_ids,
                    list(kb_qs.values_list("name", flat=True))[:5])
    if any(f.name == "status" for f in KB._meta.get_fields()):
        kb_qs = kb_qs.filter(Q(status__iexact="enabled") | Q(status__isnull=True) | Q(status=""))
    cond = Q()
    for t in terms:
        cond |= Q(chunk_text__icontains=t)
    rows = (Chunk.objects.filter(document__knowledge_base__in=kb_qs).filter(cond)
            .select_related("document", "document__knowledge_base")[:300])
    scored = []
    for ch in rows:
        text = (ch.chunk_text or "")
        low = text.lower()
        score = 0.0
        for t in terms:
            n = low.count(t)
            if n:
                score += (1.0 + min(n, 3) * 0.3) * (1.5 if len(t) >= 6 else 1.0)
        doc_name = getattr(ch.document, "name", "") or ""
        if any(t in doc_name.lower() for t in terms):
            score += 0.5
        if score:
            scored.append((score, getattr(ch.document.knowledge_base, "name", ""), doc_name, text.strip(),
                           ch.document_id, getattr(ch, "chunk_index", 0)))
    scored.sort(key=lambda x: -x[0])
    # Ek hi document ke paas-paas wale chunks jod dein (300 akshar ke tukde chhote hote hain)
    picked, seen = [], set()
    for sc, kb_name, doc_name, text, doc_id, idx in scored:
        key = (doc_id, idx)
        if key in seen:
            continue
        seen.add(key)
        try:
            nxt = Chunk.objects.filter(document_id=doc_id, chunk_index=(idx or 0) + 1).first()
            if nxt is not None and (doc_id, (idx or 0) + 1) not in seen:
                text = text + " " + (nxt.chunk_text or "").strip()
                seen.add((doc_id, (idx or 0) + 1))
        except Exception:
            pass
        picked.append((sc, kb_name, doc_name, text))
        if len(picked) >= limit:
            break
    return picked


kb_search = sync_to_async(kb_search_sync, thread_sensitive=True)


async def kb_keywords_ai(transcript):
    """Hindi (Devanagari) sawal ke English/Roman keywords, taaki English documents mein mile."""
    if not llm_api_key():
        return []
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            res = await llm_post(client, json_body={
                "model": "gpt-4o-mini", "temperature": 0, "max_tokens": 60,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": (
                        "Give search keywords for this question so it can be matched against English or "
                        "Roman-Hinglish documents. Return JSON {\"keywords\": [5-8 single words, lowercase, "
                        "English and Roman Hinglish spellings, no stopwords]}.")},
                    {"role": "user", "content": transcript},
                ],
            })
            res.raise_for_status()
            kws = json.loads(res.json()["choices"][0]["message"]["content"]).get("keywords") or []
            return [str(k).lower().strip() for k in kws if str(k).strip()][:8]
    except Exception:
        logger.debug("KB keyword AI failed", exc_info=True)
        return []


def detect_reminder_intent(transcript):
    text = (transcript or "").lower()
    text = re.sub(r"[.,!?।\"']", " ", text)
    return (
        _contains_any(text, REMINDER_INTENT_WORDS)
        or "remind" in text
        or "रिमाइ" in text
        or "याद दिल" in text
        or "yaad dil" in text
    )


def _reminder_model():
    try:
        return django_apps.get_model("core", "Reminder")
    except Exception:
        return None


def _field_map(model):
    return {f.name: f for f in model._meta.concrete_fields}


def _first_field(fields, names, types):
    for name in names:
        f = fields.get(name)
        if f is not None and isinstance(f, types):
            return f
    return None


def _reminder_schema(model):
    """Reminder model ke andar kaun sa field kis kaam ka hai."""
    fields = _field_map(model)
    schema = {
        "title": _first_field(fields, _REM_TITLE_FIELDS, (dj_models.CharField, dj_models.TextField)),
        "datetime": _first_field(fields, _REM_DATETIME_FIELDS, (dj_models.DateTimeField,)),
        "date": None,
        "time": None,
        "active": fields.get("is_active") if isinstance(fields.get("is_active"), dj_models.BooleanField) else None,
        "done": _first_field(fields, _REM_DONE_FIELDS, (dj_models.BooleanField,)),
        "device_fk": None,
        "device_str": None,
        "user_fk": None,
    }
    if schema["datetime"] is None:
        # DateTimeField nahi hai to alag Date + Time field dekhein
        date_f = _first_field(fields, _REM_DATE_FIELDS, (dj_models.DateField,))
        if date_f is not None and isinstance(date_f, dj_models.DateTimeField):
            date_f = None
        schema["date"] = date_f
        schema["time"] = _first_field(fields, _REM_TIMEONLY_FIELDS, (dj_models.TimeField,))
    schema["time_str"] = None
    if schema["datetime"] is None and schema["date"] is None and schema["time"] is None:
        # "time" CharField ho (text mein time) to "YYYY-MM-DD HH:MM" likhenge
        schema["time_str"] = _first_field(
            fields, _REM_DATETIME_FIELDS, (dj_models.CharField, dj_models.TextField)
        )

    for f in fields.values():
        if isinstance(f, dj_models.ForeignKey):
            target = f.related_model.__name__.lower()
            if target == "device" and schema["device_fk"] is None:
                schema["device_fk"] = f
            elif target == "user" and schema["user_fk"] is None:
                schema["user_fk"] = f
    if schema["title"] is None:
        used = {schema["time_str"].name} if schema["time_str"] is not None else set()
        for f in fields.values():
            if isinstance(f, (dj_models.CharField, dj_models.TextField)) and f.name not in used \
                    and f.name not in ("device", "device_id", "device_mac", "mac"):
                schema["title"] = f
                break
    if schema["device_fk"] is None:
        schema["device_str"] = _first_field(
            fields, ("device_id", "device", "device_mac", "mac"), (dj_models.CharField,)
        )
    return schema


def _find_device(device_model, device_id):
    fields = _field_map(device_model)
    for name in _DEVICE_LOOKUP_FIELDS:
        f = fields.get(name)
        if isinstance(f, (dj_models.CharField, dj_models.TextField)):
            obj = device_model.objects.filter(**{f"{name}__iexact": device_id}).first()
            if obj is not None:
                return obj
    # Upar ke naam nahi mile: Device ke har text field mein dhoondein
    for name, f in fields.items():
        if name in _DEVICE_LOOKUP_FIELDS:
            continue
        if isinstance(f, (dj_models.CharField, dj_models.TextField)):
            try:
                obj = device_model.objects.filter(**{f"{name}__iexact": device_id}).first()
            except Exception:
                continue
            if obj is not None:
                return obj
    if str(device_id).isdigit():
        return device_model.objects.filter(pk=int(device_id)).first()
    return None


def _to_db_datetime(local_dt):
    """IST datetime ko Django ke setting (USE_TZ) ke hisaab se badlein."""
    if getattr(settings, "USE_TZ", False):
        return local_dt.astimezone(ZoneInfo("UTC"))
    return local_dt.astimezone(ZoneInfo(getattr(settings, "TIME_ZONE", "Asia/Kolkata"))).replace(tzinfo=None)


def _from_db_datetime(value):
    if value is None:
        return None
    if dj_timezone.is_aware(value):
        return value.astimezone(REMINDER_TZ)
    db_tz = ZoneInfo(getattr(settings, "TIME_ZONE", "Asia/Kolkata"))
    return value.replace(tzinfo=db_tz).astimezone(REMINDER_TZ)


def _parse_time_text(value):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M",
                "%d/%m/%Y %H:%M", "%Y-%m-%d %I:%M %p", "%d-%m-%Y %I:%M %p"):
        for candidate in (value, value[:16], value[:19]):
            try:
                return datetime.strptime(candidate.upper() if "%p" in fmt else candidate, fmt).replace(tzinfo=REMINDER_TZ)
            except ValueError:
                continue
    for fmt in ("%H:%M", "%I:%M %p", "%I %p", "%I:%M%p", "%I%p"):
        try:
            t = datetime.strptime(value.upper(), fmt).time()
            return datetime.combine(datetime.now(REMINDER_TZ).date(), t).replace(tzinfo=REMINDER_TZ)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value)
        return dt.astimezone(REMINDER_TZ) if dt.tzinfo else dt.replace(tzinfo=REMINDER_TZ)
    except ValueError:
        return None


def _reminder_when(obj, schema):
    if schema.get("time_str") is not None:
        return _parse_time_text(getattr(obj, schema["time_str"].name))
    if schema["datetime"] is not None:
        return _from_db_datetime(getattr(obj, schema["datetime"].name))
    d = getattr(obj, schema["date"].name) if schema["date"] else None
    t = getattr(obj, schema["time"].name) if schema["time"] else None
    if d is None and t is None:
        return None
    d = d or datetime.now(REMINDER_TZ).date()
    t = t or _time(9, 0)
    return datetime.combine(d, t).replace(tzinfo=REMINDER_TZ)


def _device_filter(schema, device_id):
    if schema["device_fk"] is not None:
        device = _find_device(schema["device_fk"].related_model, device_id)
        if device is None:
            if schema["device_fk"].null:
                # Device table mein entry nahi: bina-device wale reminders use karein
                return {f"{schema['device_fk'].name}__isnull": True}, None
            return None, None
        return {schema["device_fk"].name: device}, device
    if schema["device_str"] is not None:
        return {schema["device_str"].name: device_id}, None
    return {}, None  # model mein device field hi nahi: sab reminders is device ke


def save_reminder_sync(device_id, title, local_dt):
    """core.Reminder mein row banayein. Return (ok, message)."""
    model = _reminder_model()
    if model is None:
        return False, "core.Reminder model nahi mila"
    schema = _reminder_schema(model)
    if schema["title"] is None or (schema["datetime"] is None and schema["date"] is None
                                   and schema["time"] is None and schema["time_str"] is None):
        names = ", ".join(f"{n}:{type(f).__name__}" for n, f in _field_map(model).items())
        return False, f"Reminder model ke fields samajh nahi aaye: {names}"

    kwargs = {}
    max_len = getattr(schema["title"], "max_length", None) or 500
    kwargs[schema["title"].name] = (title or "Reminder")[:max_len]

    if schema["time_str"] is not None:
        kwargs[schema["time_str"].name] = local_dt.strftime("%Y-%m-%d %H:%M")
    elif schema["datetime"] is not None:
        kwargs[schema["datetime"].name] = _to_db_datetime(local_dt)
    else:
        if schema["date"] is not None:
            kwargs[schema["date"].name] = local_dt.date()
        if schema["time"] is not None:
            kwargs[schema["time"].name] = local_dt.time().replace(microsecond=0)

    if schema["active"] is not None:
        kwargs[schema["active"].name] = True
    if schema["done"] is not None:
        kwargs[schema["done"].name] = False

    dev_filter, device = _device_filter(schema, device_id)
    if dev_filter is None:
        dev_model = schema["device_fk"].related_model
        names = ", ".join(f"{n}:{type(f).__name__}" for n, f in _field_map(dev_model).items())
        return False, f"Device '{device_id}' Devices table mein nahi mila (Device fields: {names})"
    if device is not None:
        kwargs[schema["device_fk"].name] = device
    elif schema["device_fk"] is None:
        kwargs.update(dev_filter)  # device_id CharField (ya koi device field nahi)
    else:
        logger.warning("Reminder: device '%s' Devices table mein nahi; bina device save", device_id)

    if schema["user_fk"] is not None and device is not None:
        for owner_name in ("user", "owner", "created_by"):
            owner = getattr(device, owner_name, None)
            if owner is not None and isinstance(owner, schema["user_fk"].related_model):
                kwargs[schema["user_fk"].name] = owner
                break

    obj = model.objects.create(**kwargs)
    logger.info("Reminder saved: id=%s fields=%s", obj.pk, list(kwargs.keys()))
    return True, obj.pk


def list_reminders_sync(device_id, limit=5):
    """Aane wale active reminders: [(local_dt, title), ...]"""
    model = _reminder_model()
    if model is None:
        return []
    schema = _reminder_schema(model)
    if schema["title"] is None:
        return []
    dev_filter, _ = _device_filter(schema, device_id)
    if dev_filter is None:
        return []
    qs = model.objects.filter(**dev_filter)
    if schema["active"] is not None:
        qs = qs.filter(**{schema["active"].name: True})
    if schema["done"] is not None:
        qs = qs.filter(**{schema["done"].name: False})
    now = datetime.now(REMINDER_TZ)
    items = []
    for obj in qs.order_by("-pk")[:50]:
        when = _reminder_when(obj, schema)
        if when is not None and when >= now - timedelta(minutes=1):
            items.append((when, getattr(obj, schema["title"].name) or "Reminder"))
    items.sort(key=lambda x: x[0])
    return items[:limit]


def pop_due_reminders_sync(device_id):
    """Jinka time ho gaya, unhe nikaal kar 'done' mark karein. [(local_dt, title)]"""
    model = _reminder_model()
    if model is None:
        return []
    schema = _reminder_schema(model)
    if schema["title"] is None or (schema["active"] is None and schema["done"] is None):
        return []  # bina is_active/done field ke baar-baar bolta rahega, isliye skip
    dev_filter, _ = _device_filter(schema, device_id)
    if dev_filter is None:
        return []
    qs = model.objects.filter(**dev_filter)
    if schema["active"] is not None:
        qs = qs.filter(**{schema["active"].name: True})
    if schema["done"] is not None:
        qs = qs.filter(**{schema["done"].name: False})
    now = datetime.now(REMINDER_TZ)
    due = []
    for obj in qs.order_by("pk")[:50]:
        when = _reminder_when(obj, schema)
        if when is None or when > now:
            continue
        update = {}
        if schema["done"] is not None:
            update[schema["done"].name] = True
        if schema["active"] is not None:
            update[schema["active"].name] = False
        model.objects.filter(pk=obj.pk).update(**update)
        due.append((when, getattr(obj, schema["title"].name) or "Reminder"))
    return due


save_reminder = sync_to_async(save_reminder_sync, thread_sensitive=True)
list_reminders = sync_to_async(list_reminders_sync, thread_sensitive=True)
pop_due_reminders = sync_to_async(pop_due_reminders_sync, thread_sensitive=True)


_HINDI_DAY_WORDS = {
    "parso": 2, "परसों": 2, "kal": 1, "कल": 1, "tomorrow": 1,
    "aaj": 0, "आज": 0, "today": 0,
}


def _fallback_parse_reminder(transcript):
    """OpenAI na chale to simple parse: 'kal 3 baje', 'aaj 5:30 pm', '10 minute baad'."""
    text = (transcript or "").lower().translate(_DEVANAGARI_DIGITS)
    now = datetime.now(REMINDER_TZ)

    m = re.search(r"(\d{1,3})\s*(minute|min|मिनट|ghante|ghanta|hour|घंटे|घंटा)", text)
    if m and ("baad" in text or "बाद" in text or "after" in text or "in " in text):
        n = int(m.group(1))
        delta = timedelta(hours=n) if m.group(2) in ("ghante", "ghanta", "hour", "घंटे", "घंटा") else timedelta(minutes=n)
        return now + delta

    m = re.search(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m|p\.m|baje|बजे|o'?clock)?", text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    m_min = re.search(r"(?:baj\w*|बज\w*)\s*(?:kar|ke|के|कर)?\s*(\d{1,2})\s*(?:minute|min|मिनट)", text)
    if m_min and not m.group(2):
        minute = int(m_min.group(1))
    if hour > 23 or minute > 59:
        return None
    suffix = m.group(3) or ""
    if suffix.startswith("p") and hour < 12:
        hour += 12
    elif suffix.startswith("a") and hour == 12:
        hour = 0
    elif not suffix.startswith(("a", "p")) and 1 <= hour <= 7:
        # "3 baje" ko din ka 3 baje (15:00) maanein
        if any(w in text for w in ("subah", "सुबह", "morning")):
            pass
        else:
            hour += 12
    if any(w in text for w in ("shaam", "शाम", "raat", "रात", "dopahar", "दोपहर", "evening", "night")) and hour < 12:
        hour += 12

    day_offset = 0
    for word, off in _HINDI_DAY_WORDS.items():
        if word in text:
            day_offset = max(day_offset, off)
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
    if day_offset == 0 and when <= now:
        when += timedelta(days=1)
    return when


async def extract_reminder(transcript, api_key, history=None):
    """User ki baat se action + title + time nikaalein.
    Return dict: {"action": "add"|"list"|"none", "title": str, "when": datetime|None}"""
    now = datetime.now(REMINDER_TZ)
    result = {"action": "add", "title": "", "title_hi": "", "when": None}

    if api_key:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await llm_post(
                    client,
                    json_body={
                        "model": "gpt-4o-mini",
                        "temperature": 0,
                        "max_tokens": 120,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You extract reminders from Hindi/Hinglish/English voice commands. "
                                    f"Current local date-time (Asia/Kolkata): {now.strftime('%Y-%m-%d %H:%M, %A')}. "
                                    "Return only JSON: {\"action\": \"add\" | \"list\" | \"none\", "
                                    "\"title\": the TOPIC of the reminder in Roman Hinglish/English letters only "
                                    "(never Devanagari), max 60 chars, without time words and without the word "
                                    "'reminder'. Examples: 'meeting ka reminder 5 baje' -> 'Meeting'; "
                                    "'मीटिंग रिमाइंडर शाम 4 बजे' -> 'Meeting'; 'dawai lene ki yaad dilana' -> "
                                    "'Dawai lena'; 'mummy ko call karna hai 7 baje' -> 'Mummy ko call karna'. "
                                    "If the topic was said earlier in the conversation, use it. "
                                    "Use '' only if no topic at all, "
                                    "\"title_hi\": the same topic in Hindi Devanagari (for speaking), "
                                    "\"datetime\": \"YYYY-MM-DD HH:MM\" in 24h local time or null}. "
                                    "'list' = user asks which reminders are set. "
                                    "Rules: '3 baje' / '3pm' with no am/pm hint means 15:00 for hours 1-7; "
                                    "'subah' = morning, 'shaam'/'raat' = evening/night, 'dopahar' = afternoon; "
                                    "'kal' after a time-setting command means tomorrow; 'parso' = day after tomorrow; "
                                    "'10 minute baad' = now + 10 minutes. If no day is said and the time has "
                                    "already passed today, use tomorrow. "
                                    "Use the previous conversation to fill a missing time or title: "
                                    "e.g. user earlier said '3 baj kar 10 minute' and now says 'reminder set kardo' "
                                    "-> add with that time. If the latest message only gives a time/date or a "
                                    "yes/haan after a reminder question, action is add. "
                                    "If the user cancels (nahi, cancel, rehne do) action is none."
                                ),
                            },
                        ] + [
                            {"role": "system", "content": "Previous conversation:\n" + "\n".join(
                                f"{m.get('role')}: {m.get('content')}" for m in (history or [])[-6:]
                            )}
                        ] * bool(history) + [
                            {"role": "user", "content": transcript},
                        ],
                    },
                )
                response.raise_for_status()
                data = json.loads(response.json()["choices"][0]["message"]["content"])
                result["action"] = (data.get("action") or "add").strip().lower()
                raw_title = str(data.get("title") or "").strip()
                result["title_hi"] = str(data.get("title_hi") or "").strip()[:60]
                result["title"] = ascii_for_display(raw_title, 60).strip()
                if not result["title"] and raw_title:
                    # Model ne Devanagari mein diya: TFT ke liye ASCII nahi, par topic na khoye
                    result["title_hi"] = result["title_hi"] or raw_title[:60]
                dt_text = (data.get("datetime") or "").strip()
                if dt_text:
                    result["when"] = datetime.strptime(dt_text[:16], "%Y-%m-%d %H:%M").replace(tzinfo=REMINDER_TZ)
        except Exception:
            logger.exception("Reminder extract (OpenAI) failed; fallback parser use hoga")

    if result["action"] == "add" and result["when"] is None:
        result["when"] = _fallback_parse_reminder(transcript)
        if result["when"] is None and not api_key:
            # pichhli user lines mein time dhoondein
            for m in reversed(history or []):
                if m.get("role") == "user":
                    result["when"] = _fallback_parse_reminder(m.get("content", ""))
                    if result["when"] is not None:
                        break
    if _is_generic_title(result["title"]) and _is_generic_title(result.get("title_hi")):
        # Model topic na de paya: transcript (ya pichhli user line) se khud nikaalein
        topic = _guess_reminder_topic(transcript)
        if not topic:
            for m in reversed(history or []):
                if m.get("role") == "user":
                    topic = _guess_reminder_topic(m.get("content", ""))
                    if topic:
                        break
        if topic:
            if topic.isascii():
                result["title"] = topic.capitalize()
            else:
                result["title_hi"] = topic
    if _is_generic_title(result["title"]):
        result["title"] = "Reminder"
    if _is_generic_title(result.get("title_hi")):
        result["title_hi"] = "" if result["title"] == "Reminder" else result["title"]
    # DB mein: Roman title; agar sirf Hindi mila to Hindi hi save ho (topic kho na jaaye)
    result["save_title"] = result["title"] if result["title"] != "Reminder" or not result["title_hi"] \
        else result["title_hi"]
    return result


_GENERIC_TITLES = {"", "reminder", "reminders", "remind", "रिमाइंडर", "alarm", "अलार्म",
                   "yaad", "याद", "none", "null"}

_TOPIC_STOP_WORDS = set("""
remind reminder reminders reminde alarm yaad dila dilana dilao dilaiye dilado set setup
add laga lagao lagado lagana lagaiye kar karo kardo kar do karna karde karein kariye
do de dena dijiye please plz mujhe muje me mera meri mere ko ka ki ke ek a an the for at
on to me my about of baje baj bajkar minute minutes min ghante ghanta hour hours baad
after aaj kal parso today tomorrow subah shaam sham raat dopahar morning evening night
am pm hai he hain tha the na ya and aur esp32 s3 wala wali hi bhi abhi
रिमाइंडर रिमाइन्डर रिमाइंडर्स अलार्म याद दिला दिलाना दिलाओ दिलाइए दिलादो दिला दो सेट
लगा लगाओ लगादो लगाना लगाइए कर करो करदो कर दो करना करें करिए दो दे देना दीजिए
मुझे मेरा मेरी मेरे को का की के एक बजे बज बजकर मिनट घंटे घंटा बाद आज कल परसों
सुबह शाम रात दोपहर है हैं था ना या और वाला वाली ही भी अभी प्लीज़ प्लीज
""".split())


def _is_generic_title(title):
    t = re.sub(r"[.,!?।\"'\s]+", " ", str(title or "")).strip().lower()
    return t in _GENERIC_TITLES or all(w in _TOPIC_STOP_WORDS for w in t.split())


def _guess_reminder_topic(text):
    """'meeting ka reminder 5 baje laga do' -> 'meeting'. Time/command shabd hata kar jo bache."""
    text = (text or "").translate(_DEVANAGARI_DIGITS).lower()
    text = re.sub(r"[.,!?।\"':;]+", " ", text)
    text = re.sub(r"\d{1,2}([:.]\d{2})?", " ", text)
    words = [w for w in text.split() if w not in _TOPIC_STOP_WORDS and not w.isdigit()]
    topic = " ".join(words).strip()
    return topic[:60] if len(topic) >= 2 else ""


def _hindi_time_phrase(when):
    """15:00 -> 'आज दोपहर 3 बजे' (gTTS Hindi ke liye)."""
    now = datetime.now(REMINDER_TZ)
    days = (when.date() - now.date()).days
    day = {0: "आज", 1: "कल", 2: "परसों"}.get(days, when.strftime("%d/%m"))
    h = when.hour
    part = "सुबह" if 4 <= h < 12 else "दोपहर" if 12 <= h < 16 else "शाम" if 16 <= h < 20 else "रात"
    h12 = h % 12 or 12
    clock = f"{h12} बजे" if when.minute == 0 else f"{h12} बजकर {when.minute} मिनट"
    return f"{day} {part} {clock}"


def _display_time(when):
    now = datetime.now(REMINDER_TZ)
    days = (when.date() - now.date()).days
    day = {0: "Today", 1: "Tomorrow"}.get(days, when.strftime("%d %b"))
    return f"{day} {when.strftime('%I:%M %p').lstrip('0')}"


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
                rem_device = data.get("device_id") or data.get("device") or ""
                saved, detail = False, "time missing"
                try:
                    rem_when = None
                    if rem_time:
                        rem_when = datetime.fromisoformat(str(rem_time).replace("Z", "+00:00"))
                        if rem_when.tzinfo is None:
                            rem_when = rem_when.replace(tzinfo=REMINDER_TZ)
                    if rem_when is not None:
                        saved, detail = await save_reminder(rem_device, rem_title, rem_when)
                except Exception as err:
                    detail = str(err)
                if saved:
                    response_payload = {
                        "status": "success",
                        "message": f"Reminder '{rem_title}' successfully saved & pushed to ESP32!",
                        "id": detail,
                    }
                else:
                    response_payload = {
                        "status": "error",
                        "message": f"Reminder save nahi hua: {detail}",
                    }

            # ==========================================
            # 6. DYNAMIC MCP ENDPOINTS [PRESERVED]
            # ==========================================
            elif action == "dynamic_mcp_call" or "endpoint" in data or "endpoints" in data:
                endpoints_list = data.get("endpoints", [])
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

        if response_payload:
            await self.send(text_data=json.dumps(response_payload))


# Chalte quiz ka state device ke hisaab se (WebSocket reconnect par quiz na toote)
ACTIVE_QUIZZES = {}


class AudioConsumer(AsyncWebsocketConsumer):
    @property
    def meeting(self):
        return ACTIVE_MEETINGS.get(getattr(self, "device_id", None))

    @meeting.setter
    def meeting(self, value):
        device_id = getattr(self, "device_id", None)
        if value is None:
            ACTIVE_MEETINGS.pop(device_id, None)
        else:
            ACTIVE_MEETINGS[device_id] = value

    @property
    def quiz(self):
        return ACTIVE_QUIZZES.get(getattr(self, "device_id", None))

    @quiz.setter
    def quiz(self, value):
        device_id = getattr(self, "device_id", None)
        if value is None:
            ACTIVE_QUIZZES.pop(device_id, None)
        else:
            ACTIVE_QUIZZES[device_id] = value

    SAMPLE_RATE = 16000
    CHANNELS = 1
    FRAME_MS = 20
    BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * 2
    FRAME_BYTES = BYTES_PER_SECOND * FRAME_MS // 1000  # 640

    # --- VAD (sab .env se tune ho sakte hain) ---
    # "device": ESP32 ka voice_gate already decide karta hai kab bhejna hai,
    #           isliye server har aaye packet ko speech maanta hai aur
    #           packets rukne (inactivity) par utterance khatam karta hai.
    # "server": server apna RMS/peak VAD lagata hai (mic gain theek hone ke baad).
    VAD_MODE = os.getenv("VAD_MODE", "device").strip().lower()
    VAD_PEAK_THRESHOLD = _env_int("VAD_PEAK_THRESHOLD", 900)   # ESP threshold ka starting point
    VAD_RMS_THRESHOLD = _env_int("VAD_RMS_THRESHOLD", 250)     # minimum RMS (floor)
    VAD_NOISE_MULTIPLIER = _env_float("VAD_NOISE_MULTIPLIER", 2.5)  # noise floor se kitna upar = voice
    VAD_START_FRAMES = _env_int("VAD_START_FRAMES", 2)         # 2 × 20 ms lagatar voice = speech start
    VAD_PREROLL_FRAMES = _env_int("VAD_PREROLL_FRAMES", 15)    # speech se pehle ka 300 ms (shuruaat na kate)
    VAD_SILENCE_TAIL_FRAMES = 25                               # 25 × 20 ms = 500 ms tail
    VAD_END_SILENCE_FRAMES = _env_int("VAD_END_SILENCE_FRAMES", 35)  # 700 ms chup = utterance khatam

    INACTIVITY_SECONDS = _env_float("INACTIVITY_SECONDS", 0.8)  # ESP ne packets bhejna band kiya
    MIN_UTTERANCE_SECONDS = _env_float("MIN_UTTERANCE_SECONDS", 0.4)  # isse chhota = ignore
    MAX_UTTERANCE_SECONDS = _env_float("MAX_UTTERANCE_SECONDS", 15.0)
    # Noise filter: 20 ms frame jiska RMS isse upar ho = speech frame.
    # Aapke logs: noise ~100-250, asli speech 1000-5500.
    SPEECH_FRAME_RMS = _env_float("SPEECH_FRAME_RMS", 500)
    MIN_SPEECH_FRAMES = _env_int("MIN_SPEECH_FRAMES", 8)  # kam se kam 160 ms speech

    # --- Whisper input level ---
    STT_TARGET_RMS = _env_float("STT_TARGET_RMS", 0.08)   # ~2600/32768, normal speech level
    STT_MAX_GAIN = _env_float("STT_MAX_GAIN", 40.0)

    # --- TTS playback ---
    # ESP ke speaker buffer mein kitna audio aage rakhein. Zyada = Wi-Fi jhatkon
    # par awaaz nahi atakti. Firmware v1.3+ URL mein apna buffer (?buf_ms=)
    # batata hai; usse zyada nahi bhejte (warna overflow).
    TTS_PREBUFFER_SECONDS = _env_float("TTS_PREBUFFER_SECONDS", 0.6)
    ECHO_GUARD_SECONDS = _env_float("ECHO_GUARD_SECONDS", 0.4)        # speaker band hone ke baad mic ignore

    # Processing ke dauraan ESP32 ko "abhi zinda hoon" message
    KEEPALIVE_SECONDS = _env_float("KEEPALIVE_SECONDS", 0.5)

    # --- AI reply ---
    AI_MAX_TOKENS = _env_int("AI_MAX_TOKENS", 150)          # lambe jawab = lamba TTS
    CHAT_HISTORY_TURNS = _env_int("CHAT_HISTORY_TURNS", 4)  # kitne pichhle sawal-jawab yaad rahein

    async def connect(self):
        self.device_id = self.scope["url_route"]["kwargs"]["device_id"]
        CURRENT_DEVICE.set(self.device_id)

        # Firmware ka speaker buffer (ms) -> kitna audio aage bhej sakte hain
        from urllib.parse import parse_qs
        query = parse_qs((self.scope.get("query_string") or b"").decode(errors="ignore"))
        try:
            buf_ms = int(query.get("buf_ms", ["0"])[0])
        except ValueError:
            buf_ms = 0
        if buf_ms > 0:
            # buffer ka 60% tak bharein (baaki jitter ke liye khaali)
            self.tts_prebuffer = max(0.12, min(self.TTS_PREBUFFER_SECONDS, buf_ms * 0.6 / 1000.0))
        else:
            self.tts_prebuffer = 0.3   # purana firmware: pehle jaisa
        logger.info("TTS prebuffer: device=%s buf_ms=%d prebuffer=%.2fs",
                    self.device_id, buf_ms, self.tts_prebuffer)
        self.packet_count = 0
        self.pcm_frame_count = 0
        self.pcm_buffer = bytearray()
        self.inactivity_task = None
        self.worker_task = None
        self.stop_task = None
        self.ws_open = False
        self.process_lock = asyncio.Lock()
        self.vad_silence_frames = 0

        # Utterance state machine
        self.in_speech = False
        self.voice_run_frames = 0
        self.preroll = deque(maxlen=self.VAD_PREROLL_FRAMES)
        self.last_voice_buffer_len = 0
        self.noise_floor = self.VAD_RMS_THRESHOLD / self.VAD_NOISE_MULTIPLIER
        self.last_packet_time = time.monotonic()

        # TTS ke dauraan speaker ki awaaz mic mein wapas na jaaye
        self.mute_until = 0.0
        self.keepalive_active = False

        # Reminder ka time poochha hai? Agla jawab usi ka follow-up hoga.
        self.pending_reminder_until = 0.0

        # Voice quiz state (reconnect ke baad bhi chalta quiz bana rahe)
        if self.quiz and time.monotonic() - self.quiz.get("last", 0) > 300:
            self.quiz = None
        self.quiz_pick = None          # {"exams": [...], "until": t}
        self.last_quiz_list_time = 0.0

        # STT queue: ek worker, backlog nahi banega
        self.pending_pcm = bytearray()
        self.pending_event = asyncio.Event()
        self.worker_idle = asyncio.Event()
        self.worker_idle.set()
        self._speech_started_busy = False

        if not HAS_OPUS:
            logger.error("opuslib unavailable: device=%s", self.device_id)
            await self.close(code=1011)
            return

        try:
            self.opus_decoder = opuslib.Decoder(
                self.SAMPLE_RATE,
                self.CHANNELS,
            )
        except Exception:
            logger.exception(
                "Opus decoder initialization failed: device=%s",
                self.device_id,
            )
            await self.close(code=1011)
            return

        await self.accept()
        self.ws_open = True

        self.worker_task = asyncio.create_task(self._stt_worker())
        self.inactivity_task = asyncio.create_task(self._inactivity_monitor())
        # Time hone par reminder bolne wala loop
        self.reminder_task = asyncio.create_task(self._reminder_loop())

        await self._send_json({
            "type": "ready",
            "codec": "opus",
            "sample_rate": self.SAMPLE_RATE,
            "channels": self.CHANNELS,
            "frame_ms": self.FRAME_MS,
        })

        logger.info("Audio WebSocket connected: device=%s", self.device_id)

        # Exam list pehle se le aayein: "Excel start karo" pehli baar mein bhi samjhe
        asyncio.create_task(self._prefetch_exams())

        if self.meeting:
            logger.warning("Meeting resumed after reconnect: device=%s", self.device_id)
            await self._send_json({"type": "meeting", "on": True})

        if self.quiz:
            # Connection toot kar wapas aaya: quiz screen dobara dikhayein
            logger.warning("Quiz resumed after reconnect: device=%s q=%d/%d",
                           self.device_id, self.quiz["index"] + 1, len(self.quiz["questions"]))
            await self._send_json(self._quiz_screen("Connection wapas. Jawab boliye"))

    async def _send_json(self, payload):
        if not self.ws_open:
            logger.warning(
                "Cannot send JSON; WebSocket is closed: device=%s",
                self.device_id,
            )
            return False

        try:
            await self.send(text_data=json.dumps(payload))
            logger.info(
                "WS JSON sent: device=%s type=%s",
                self.device_id,
                payload.get("type"),
            )
            return True
        except Exception:
            logger.exception("WS JSON send failed: device=%s", self.device_id)
            return False

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data is not None:
            self.packet_count += 1
            self.last_packet_time = time.monotonic()

            try:
                # frame_size is samples per channel; allow up to 120 ms.
                max_frame_size = self.SAMPLE_RATE * 120 // 1000

                pcm_bytes = self.opus_decoder.decode(
                    bytes_data,
                    max_frame_size,
                    decode_fec=False,
                )

                samples = len(pcm_bytes) // (2 * self.CHANNELS)
                self.pcm_frame_count += 1

                if self.packet_count % 50 == 0:
                    logger.info(
                        "Opus decoded: device=%s packets=%d "
                        "pcm_bytes=%d samples=%d",
                        self.device_id,
                        self.packet_count,
                        len(pcm_bytes),
                        samples,
                    )

                await self.on_pcm(pcm_bytes)

            except Exception:
                logger.exception(
                    "Opus decode failed: device=%s packet=%d bytes=%d",
                    self.device_id,
                    self.packet_count,
                    len(bytes_data),
                )

            return

        if text_data is not None:
            try:
                message = json.loads(text_data)
            except json.JSONDecodeError:
                logger.warning(
                    "Invalid audio-control JSON: device=%s",
                    self.device_id,
                )
                return

            if message.get("type") == "meeting_stop":
                # Device par touch: meeting band + save
                logger.info("Meeting stop (touch): device=%s", self.device_id)
                if self.meeting:
                    asyncio.create_task(self._stop_meeting())
                return

            if message.get("type") == "stop":
                logger.info("Audio stop received: device=%s", self.device_id)

                # receive() ko block na karein; background mein finish karein.
                if self.stop_task is None or self.stop_task.done():
                    self.stop_task = asyncio.create_task(self._handle_stop())

    async def _handle_stop(self):
        try:
            # Jo bhi bola gaya hai use process karein, phir "stopped" bhejein.
            await self._end_utterance("stop", force=True)
            try:
                await asyncio.wait_for(self.worker_idle.wait(), timeout=60)
            except asyncio.TimeoutError:
                logger.warning("Stop wait timed out: device=%s", self.device_id)
            await self._send_json({"type": "stopped"})
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Stop handling failed: device=%s", self.device_id)

    # =========================================================
    # VAD / utterance detection
    # =========================================================
    def _reset_vad(self):
        self.in_speech = False
        self.pcm_buffer.clear()
        self.preroll.clear()
        self.voice_run_frames = 0
        self.vad_silence_frames = 0
        self.last_voice_buffer_len = 0

    async def on_pcm(self, pcm_bytes):
        if not pcm_bytes:
            return

        # TTS chal raha hai: speaker ki awaaz ko user ki awaaz na samjhein.
        if time.monotonic() < self.mute_until:
            if self.in_speech or self.pcm_buffer or self.preroll:
                self._reset_vad()
            return

        # PCM signed 16-bit samples; int32 conversion abs overflow rokta hai.
        samples = np.frombuffer(
            pcm_bytes,
            dtype=np.int16,
        ).astype(np.int32)

        if samples.size == 0:
            return

        peak = int(np.max(np.abs(samples)))
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))

        rms_threshold = max(
            float(self.VAD_RMS_THRESHOLD),
            self.noise_floor * self.VAD_NOISE_MULTIPLIER,
        )
        peak_threshold = float(self.VAD_PEAK_THRESHOLD)
        # "भेज दूँ?" ke baad chhota/dheema "haan" bhi pakdein (VAD_REPLY_FACTOR, default 0.6)
        if self._awaiting_reply():
            f = _env_float("VAD_REPLY_FACTOR", 0.6)
            rms_threshold = max(self.noise_floor * 1.6, rms_threshold * f)
            peak_threshold = max(500.0, peak_threshold * f)

        # Pehle logs se speech aur silence ke actual levels check karein.
        if self.pcm_frame_count % 50 == 0:
            logger.info(
                "Server VAD level: device=%s RMS=%.0f peak=%d "
                "noise_floor=%.0f rms_threshold=%.0f in_speech=%s",
                self.device_id,
                rms,
                peak,
                self.noise_floor,
                rms_threshold,
                self.in_speech,
            )

        if self.VAD_MODE == "device":
            # Pehle yahan har packet ko voice maana jata tha. ESP32 ab lagatar
            # audio bhejta hai, isliye "bolna band hua" kabhi detect nahi hota
            # tha aur har sawal 15 sec (max_length) tak ruka rehta tha.
            # Ab energy se decide karein: aapke logs mein noise RMS ~100-250,
            # asli speech 1000-5000. Threshold noise ke saath adjust hota hai.
            speech_threshold = max(
                float(self.SPEECH_FRAME_RMS),
                self.noise_floor * self.VAD_NOISE_MULTIPLIER * 1.2,
            )
            is_voice = rms >= speech_threshold

            if not is_voice:
                # Noise floor dheere-dheere seekhein (speech ke beech bhi),
                # lekin 400 se upar na jaane dein.
                self.noise_floor = min(
                    400.0, 0.98 * self.noise_floor + 0.02 * rms
                )
        else:
            is_voice = (
                peak >= peak_threshold
                and rms >= rms_threshold
            )

        if not self.in_speech:
            # Speech shuru hone ka wait; pichhla 300 ms preroll mein rakhein.
            self.preroll.append(pcm_bytes)

            if is_voice:
                self.voice_run_frames += 1
                if self.voice_run_frames >= self.VAD_START_FRAMES:
                    self.in_speech = True
                    self.pcm_buffer = bytearray(b"".join(self.preroll))
                    self.preroll.clear()
                    self.vad_silence_frames = 0
                    self.last_voice_buffer_len = len(self.pcm_buffer)
                    # Device us waqt soch/bol raha tha? (echo ya jaldi bola jawab)
                    self._speech_started_busy = not self.worker_idle.is_set()
                    logger.info(
                        "Speech start: device=%s RMS=%.0f peak=%d",
                        self.device_id,
                        rms,
                        peak,
                    )
            else:
                self.voice_run_frames = 0
                # Sirf silence frames se background noise seekhein.
                if self.VAD_MODE != "device":
                    self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms
            return

        # Speech chal rahi hai: chhote pauses (words ke beech) ko bhi rakhein.
        self.pcm_buffer.extend(pcm_bytes)

        if is_voice:
            self.vad_silence_frames = 0
            self.last_voice_buffer_len = len(self.pcm_buffer)
        else:
            self.vad_silence_frames += 1

        if self.vad_silence_frames >= self.VAD_END_SILENCE_FRAMES:
            await self._end_utterance("silence")
        elif len(self.pcm_buffer) / self.BYTES_PER_SECOND >= self.MAX_UTTERANCE_SECONDS:
            await self._end_utterance("max_length")

    async def _inactivity_monitor(self):
        """ESP32 ka voice gate packets bhejna band kar de to utterance yahan khatam hoti hai."""
        try:
            while self.ws_open:
                await asyncio.sleep(0.1)

                if (
                    self.in_speech
                    and time.monotonic() - self.last_packet_time >= self.INACTIVITY_SECONDS
                ):
                    logger.info(
                        "Audio inactivity: device=%s buffer_bytes=%d; processing",
                        self.device_id,
                        len(self.pcm_buffer),
                    )
                    await self._end_utterance("inactivity")

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(
                "Inactivity processing failed: device=%s",
                self.device_id,
            )

    async def _end_utterance(self, reason, force=False):
        async with self.process_lock:
            if not self.pcm_buffer or (not self.in_speech and not force):
                self._reset_vad()
                return

            # End ki lambi silence kaat kar sirf 500 ms tail rakhein.
            keep = min(
                len(self.pcm_buffer),
                self.last_voice_buffer_len
                + self.VAD_SILENCE_TAIL_FRAMES * self.FRAME_BYTES,
            )
            if keep <= 0:
                keep = len(self.pcm_buffer)

            pcm_data = bytes(self.pcm_buffer[:keep])
            self._reset_vad()

        duration_sec = len(pcm_data) / self.BYTES_PER_SECOND

        # Quiz mein "B" jaisa chhota jawab bhi chahiye: limit aadhi
        # Quiz chal raha ho, ya humne kuch poochha ho (kaun sa quiz? kis time?)
        # to chhota jawab ("do", "B", "haan") bhi lena hai
        now_t = time.monotonic()
        pick = getattr(self, "quiz_pick", None)
        quiz_mode = bool(
            getattr(self, "quiz", None)
            or (pick and now_t < pick["until"])
            or now_t < getattr(self, "pending_reminder_until", 0.0)
            or (getattr(self, "pending_mail", None) and now_t < self.pending_mail["until"])
            or (getattr(self, "pending_mail_pick", None) and now_t < self.pending_mail_pick["until"])
            or (getattr(self, "pending_mail_content", None) and now_t < self.pending_mail_content["until"])
        )
        min_seconds = self.MIN_UTTERANCE_SECONDS * (0.5 if quiz_mode else 1.0)
        min_frames = max(3, self.MIN_SPEECH_FRAMES // 2) if quiz_mode else self.MIN_SPEECH_FRAMES
        if duration_sec < min_seconds:
            logger.info(
                "Utterance ignored (too short): device=%s reason=%s duration=%.2fs",
                self.device_id,
                reason,
                duration_sec,
            )
            return

        # ESP32 ka gate background noise (RMS ~100-170) bhi bhej deta hai.
        # Aisi "utterance" Whisper par time barbaad karti thi aur asli speech
        # uske peeche queue mein fas jaati thi. Sirf wahi bhejein jisme
        # kam se kam kuch loud speech frames hon.
        speech_frames, max_frame_rms = self._count_speech_frames(pcm_data)
        if speech_frames < min_frames:
            logger.info(
                "Utterance ignored (noise only): device=%s reason=%s "
                "duration=%.2fs speech_frames=%d max_frame_RMS=%.0f",
                self.device_id,
                reason,
                duration_sec,
                speech_frames,
                max_frame_rms,
            )
            return

        logger.info(
            "Utterance end: device=%s reason=%s bytes=%d duration=%.2fs "
            "speech_frames=%d max_frame_RMS=%.0f",
            self.device_id,
            reason,
            len(pcm_data),
            duration_sec,
            speech_frames,
            max_frame_rms,
        )
        # Jo baat device ke sochne/bolne ke dauraan shuru hui, woh purane sawal ki hai
        # (ya speaker ki echo). Use queue mein rakh kar agle sawal ka jawab banana galat
        # hai: quiz mein bina sune answer lag jata tha. Meeting mode mein sab rakhein.
        if not self.meeting and (getattr(self, "_speech_started_busy", False)
                                 or not self.worker_idle.is_set()):
            logger.info(
                "Utterance dropped (device busy/speaking): device=%s duration=%.2fs",
                self.device_id, duration_sec,
            )
            self._speech_started_busy = False
            if self.worker_idle.is_set():
                # Ab koi jawab aane wala nahi: ESP32 "waiting reply" mein atka na rahe
                await self._send_json({
                    "type": "no_speech",
                    "message": "Device bol raha tha; dobara boliye.",
                })
            return
        self._speech_started_busy = False
        self._utterance_end_time = time.monotonic()
        self._enqueue_utterance(pcm_data)

    def _count_speech_frames(self, pcm_data):
        samples = np.frombuffer(
            pcm_data[: len(pcm_data) // 2 * 2], dtype=np.int16
        ).astype(np.float64)
        frame_len = self.FRAME_BYTES // 2  # 320 samples = 20 ms
        n = len(samples) // frame_len
        if n == 0:
            return 0, 0.0
        frames = samples[: n * frame_len].reshape(n, frame_len)
        frames = frames - frames.mean(axis=1, keepdims=True)
        frame_rms = np.sqrt((frames ** 2).mean(axis=1))
        return int((frame_rms >= self.SPEECH_FRAME_RMS).sum()), float(frame_rms.max())

    def _enqueue_utterance(self, pcm_data):
        if self.pending_pcm:
            # Worker abhi busy hai aur ek utterance pehle se wait kar rahi hai:
            # dono ko jod dein (user ne beech mein pause liya tha). Backlog nahi banega.
            self.pending_pcm.extend(b"\x00\x00" * int(0.2 * self.SAMPLE_RATE))
            logger.info("Merging with pending utterance: device=%s", self.device_id)

        self.pending_pcm.extend(pcm_data)
        self.worker_idle.clear()
        self.pending_event.set()

    async def _stt_worker(self):
        try:
            while True:
                await self.pending_event.wait()
                self.pending_event.clear()

                if not self.pending_pcm:
                    self.worker_idle.set()
                    continue

                pcm_data = bytes(self.pending_pcm)
                self.pending_pcm.clear()

                try:
                    await self.process_audio_stream(pcm_data)
                except Exception:
                    logger.exception(
                        "Audio processing failed: device=%s",
                        self.device_id,
                    )
                finally:
                    if not self.pending_pcm:
                        self.worker_idle.set()

        except asyncio.CancelledError:
            pass

    def _save_wav(self, filename, pcm_data):
        with wave.open(filename, "wb") as wav_file:
            wav_file.setnchannels(self.CHANNELS)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.SAMPLE_RATE)
            wav_file.writeframes(pcm_data)

    # =========================================================
    # STT -> AI -> TTS pipeline
    # =========================================================
    async def _keepalive_loop(self):
        """Whisper/OpenAI/gTTS chal rahe hon tab ESP32 ko har thodi der mein
        ek chhota message bhejein, taaki woh 'jawab nahi aaya' samajh kar
        socket band na kare."""
        try:
            while self.ws_open and self.keepalive_active:
                await asyncio.sleep(self.KEEPALIVE_SECONDS)
                if not (self.ws_open and self.keepalive_active):
                    break
                try:
                    await self.send(text_data=json.dumps({"type": "keepalive"}))
                    logger.debug("Keepalive sent: device=%s", self.device_id)
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    async def process_audio_stream(self, pcm_data):
        if self.meeting:
            # Meeting mode: jawab nahi, sirf record + transcript
            try:
                await self._meeting_segment(pcm_data)
            except Exception:
                logger.exception("Meeting segment failed: device=%s", self.device_id)
            return
        self.keepalive_active = True
        keepalive_task = asyncio.create_task(self._keepalive_loop())
        try:
            await self._process_audio_stream(pcm_data)
        finally:
            self.keepalive_active = False
            keepalive_task.cancel()

    async def _process_audio_stream(self, pcm_data):
        if not pcm_data:
            return

        duration_sec = len(pcm_data) / self.BYTES_PER_SECOND

        logger.info(
            "Processing audio: device=%s bytes=%d duration=%.2fs",
            self.device_id,
            len(pcm_data),
            duration_sec,
        )

        await self._send_json({
            "type": "processing",
            "duration_sec": round(duration_sec, 2),
        })

        # WAV file save (thread mein, event loop block na ho).
        media_dir = getattr(
            settings,
            "MEDIA_ROOT",
            os.path.join(os.getcwd(), "media"),
        )
        os.makedirs(media_dir, exist_ok=True)

        wav_filename = os.path.join(
            media_dir,
            f"recorded_{self.device_id}.wav",
        )

        input_rms_i16 = float(
            np.sqrt(np.mean(np.frombuffer(pcm_data[: len(pcm_data) // 2 * 2], dtype=np.int16).astype(np.float64) ** 2))
        ) if len(pcm_data) >= 2 else 0.0
        logger.info(
            "Utterance level: device=%s avg_RMS=%.0f (speech should be ~1500-5000)",
            self.device_id,
            input_rms_i16,
        )

        try:
            await asyncio.to_thread(self._save_wav, wav_filename, pcm_data)

            logger.info(
                "WAV saved: %s, PCM bytes=%d",
                wav_filename,
                len(pcm_data),
            )
        except Exception:
            logger.exception("WAV save failed: device=%s", self.device_id)

        if len(pcm_data) % 2:
            await self._send_json({
                "type": "error",
                "stage": "audio",
                "message": "Invalid 16-bit PCM data",
            })
            return

        # Isi file mein load hua model use karein; core.apps import nahi.
        model = WHISPER_MODEL
        stt_engine = (_pratham_setting("STT_ENGINE") or "local").lower()

        if model is None and stt_engine not in ("openai", "groq") and FAST_WHISPER_MODEL is None:
            logger.error(
                "Whisper model unavailable: %s",
                WHISPER_LOAD_ERROR,
            )
            await self._send_json({
                "type": "error",
                "stage": "stt",
                "message": "Whisper model failed to load",
            })
            return

        try:
            pcm_np = (
                np.frombuffer(pcm_data, dtype=np.int16)
                .astype(np.float32)
                / 32768.0
            )

            # Mic gain kam hai (speech RMS ~150/32768). Peak se normalize karne par
            # ek click/spike gain ko 1.0 kar deta tha. Isliye RMS se normalize karein.
            pcm_np = pcm_np - float(np.mean(pcm_np)) if pcm_np.size else pcm_np  # DC offset hatayein
            input_rms = float(np.sqrt(np.mean(pcm_np ** 2))) if pcm_np.size else 0.0
            if input_rms > 0.0:
                gain = min(self.STT_TARGET_RMS / input_rms, self.STT_MAX_GAIN)
                gain = max(gain, 1.0)
                pcm_np = np.clip(pcm_np * gain, -1.0, 1.0)
            else:
                gain = 1.0

            logger.info(
                "Whisper start: device=%s samples=%d duration=%.2fs gain=%.1f",
                self.device_id,
                len(pcm_np),
                duration_sec,
                gain,
            )

            stt_started = time.monotonic()
            self._last_pcm_np = pcm_np   # quiz mein jawab samajh na aaye to dobara (Hindi) sun sakein
            stt_prompt = self._stt_prompt()
            transcript = None
            used_engine = "local"
            if stt_engine in ("openai", "groq"):
                transcript = await openai_transcribe(pcm_np, stt_prompt, stt_engine)
                used_engine = stt_engine
            if transcript is None and FAST_WHISPER_MODEL is not None:
                local_prompt = stt_prompt if (getattr(self, "quiz", None) or getattr(self, "quiz_pick", None)) else None
                # Quiz ke jawab English mein ("B", "option C", "stop quiz"): Hindi mode
                # "B" ko "बाएं" / "बपपप" bana deta tha. Quiz chalte waqt English.
                quiz_lang = None
                if getattr(self, "quiz", None):
                    quiz_lang = os.getenv("QUIZ_STT_LANGUAGE", "en").strip() or None
                    local_prompt = (
                        "Quiz answer: A, B, C, D, option A, option B, option C, option D, "
                        "stop quiz, quiz band karo, repeat, next. " + (local_prompt or "")
                    )
                transcript = await asyncio.to_thread(_run_fast_whisper, pcm_np, local_prompt, quiz_lang)
                used_engine = "faster" + (f"/{quiz_lang}" if quiz_lang else "")
                # Hybrid: local kamzor suna to sirf is baat ko Groq se dobara (STT_HYBRID=0 se band)
                lp = getattr(_run_fast_whisper, "last_logprob", 0.0)
                now_m = time.monotonic()
                waiting_answer = any(
                    (getattr(self, k, None) or {}).get("until", 0) > now_m
                    for k in ("pending_mail", "pending_mail_pick", "pending_mail_content")
                ) or now_m < getattr(self, "pending_reminder_until", 0.0) or bool(getattr(self, "quiz", None))
                empty_but_waiting = not (transcript or "").strip() and waiting_answer and duration_sec >= 0.4
                if (_pratham_setting("STT_HYBRID") or "1") == "1" and _groq_key() \
                        and (stt_looks_bad(transcript, lp) or empty_but_waiting):
                    alt = await openai_transcribe(pcm_np, stt_prompt, "groq",
                                                  language=quiz_lang or _pratham_setting("STT_HYBRID_LANGUAGE") or "hi")
                    if alt:
                        logger.info("STT hybrid: local=%r (logprob %.2f) -> groq=%r", transcript, lp, alt)
                        transcript, used_engine = alt, "faster->groq"
            if transcript is None:
                if model is None:
                    raise RuntimeError("Whisper model load nahi hua aur OpenAI STT fail")
                # Local Whisper prompt ko kabhi-kabhi khud bol deta hai; sirf quiz mein dein
                local_prompt = stt_prompt if (getattr(self, "quiz", None) or getattr(self, "quiz_pick", None)) else None
                result = await asyncio.to_thread(_run_whisper, model, pcm_np, local_prompt)
                transcript = result.get("text", "").strip()
                used_engine = "local"

            logger.info(
                "Whisper transcript: device=%s text=%r took=%.2fs engine=%s",
                self.device_id,
                transcript,
                time.monotonic() - stt_started,
                used_engine,
            )

        except Exception as err:
            logger.exception("Whisper STT failed: device=%s", self.device_id)
            await self._send_json({
                "type": "error",
                "stage": "stt",
                "message": str(err),
            })
            return

        if not self.ws_open:
            logger.info(
                "Device disconnected during STT; skipping reply: device=%s",
                self.device_id,
            )
            return

        await self._send_json({
            "type": "transcript",
            "text": transcript,
        })

        if not transcript:
            await self._send_json({
                "type": "no_speech",
                "message": "Speech detect nahi hui.",
            })
            return

        # "Tumhara naam kya hai" / "tumhara naam Tulsi rakho"
        name_cmd = parse_name_command(transcript)
        if name_cmd is not None and not getattr(self, "quiz", None):
            kind, new_name = name_cmd
            if kind == "set":
                set_assistant_name(self.device_id, new_name)
                speech = f"ठीक है, अब से मेरा नाम {new_name} है।"
                display = f"Mera naam: {ascii_for_display(new_name, 20) or new_name}"
            else:
                current = get_assistant_name(self.device_id)
                speech = f"मेरा नाम {current} है। मैं आपकी कैसे मदद कर सकता हूं?"
                display = f"Mera naam {ascii_for_display(current, 20) or current}"
            await self._send_json({"type": "ai_reply", "text": speech, "display": display})
            self._remember_turn(transcript, speech, display)
            await self._speak(speech)
            return

        # "Time kya hai" / "aaj kaun si tareekh": seedha ghadi se (AI andaza na lagaye)
        time_answer = answer_time_query(transcript)
        if time_answer is not None and not getattr(self, "quiz", None):
            speech, display = time_answer
            await self._send_json({"type": "ai_reply", "text": speech, "display": display})
            self._remember_turn(transcript, speech, display)
            await self._speak(speech)
            return

        # "Atul ko kya likhna hai?" ka jawab
        if getattr(self, "pending_mail_content", None) and time.monotonic() < self.pending_mail_content["until"]:
            first = self.pending_mail_content["first"]
            self.pending_mail_content = None
            if _contains_any(transcript.lower(), _MAIL_NO) and len(transcript.split()) <= 3:
                await self._say("ठीक है, मेल रद्द कर दिया।", "Mail cancel")
                return
            await self._mail_compose(f"{first}. Mail mein likhna hai: {transcript}")
            return
        # "Kaun sa Atul?" ka jawab
        if getattr(self, "pending_mail_pick", None) and time.monotonic() < self.pending_mail_pick["until"]:
            if await self._mail_pick(transcript):
                return
        # Mail draft ke baad "haan bhej do" / "nahi"
        if getattr(self, "pending_mail", None) and time.monotonic() < self.pending_mail["until"]:
            if await self._mail_confirm(transcript):
                return
        # "Atul ko mail likho ki ..."
        if not getattr(self, "quiz", None) and not self.meeting and not is_mom_send(transcript) and (
                is_mail_compose(transcript) or await ai_is_mail_compose(transcript)):
            await self._mail_compose(transcript)
            return

        # "MoM mail karo" / "meeting notes WhatsApp bhejo"
        if is_mom_send(transcript) and not getattr(self, "quiz", None) and not self.meeting:
            low = transcript.lower()
            only = None
            if _contains_any(low, ("whatsapp", "व्हाट्सएप", "वॉट्सऐप")) and not _contains_any(low, ("mail", "email", "ईमेल", "मेल")):
                only = "whatsapp"
            elif _contains_any(low, ("mail", "email", "ईमेल", "मेल")) and not _contains_any(low, ("whatsapp", "व्हाट्सएप", "वॉट्सऐप")):
                only = "email"
            await self._send_mom(only=only)
            return

        # Meeting mode on / pichhli meeting ka summary
        if is_meeting_start(transcript) and not getattr(self, "quiz", None):
            await self._start_meeting(transcript)
            return
        if is_meeting_summary(transcript):
            await self._speak_last_meeting()
            return
        if is_meeting_stop(transcript):
            await self._stop_meeting()
            return
        if not getattr(self, "quiz", None):
            ai_intent = await ai_meeting_intent(transcript)
            if ai_intent == "start":
                await self._start_meeting(transcript)
                return
            if ai_intent == "stop":
                await self._stop_meeting()
                return
            if ai_intent == "summary":
                await self._speak_last_meeting()
                return

        # Device voice commands (mute / volume): AI ko bheje bina turant.
        command = parse_device_command(transcript)
        if command is not None:
            action, value, confirm_text = command
            logger.info(
                "Device command: device=%s action=%s value=%s",
                self.device_id,
                action,
                value,
            )
            await self._send_json({
                "type": "device_control",
                "action": action,
                "value": value,
            })
            # Mute par kuch nahi bolte; baaki par chhota confirmation
            if confirm_text:
                await self._speak(confirm_text)
            return

        # Quiz chal raha hai (ya exam chunna hai)? Jawab quiz ko jaaye
        if getattr(self, "quiz", None) or (
            getattr(self, "quiz_pick", None) and time.monotonic() < self.quiz_pick["until"]
        ):
            if await self._quiz_input(transcript):
                return

        if "stop" in transcript.lower():
            await self._send_json({"type": "stop_command"})
            return

        # Reminder add / list: asli database mein save (pehle AI sirf bol deta tha)
        reminder_followup = time.monotonic() < getattr(self, "pending_reminder_until", 0.0)
        if detect_reminder_intent(transcript) or reminder_followup:
            handled = await self._handle_reminder(transcript, followup=reminder_followup)
            if handled:
                return

        # "Quiz shuru karo" / list ke baad "MS Excel wala start karo"
        recent_quiz_list = time.monotonic() - getattr(self, "last_quiz_list_time", 0.0) < 180
        quiz_blocked = time.monotonic() < getattr(self, "quiz_block_until", 0.0)
        if quiz_blocked and (is_quiz_start(transcript) or detect_pratham_intent(transcript) == "quiz"):
            logger.info("Quiz abhi band hua; dobara start ignore: %r", transcript)
            return
        if is_quiz_start(transcript) or (
            recent_quiz_list and _contains_any(transcript.lower(), QUIZ_START_WORDS)
        ):
            await self._start_quiz(transcript)
            return

        # MyPratham portal data (jobs / quiz / learning) chahiye?
        # Data pehle fetch karein, phir AI usi data se jawab banaye.
        pratham_intent = detect_pratham_intent(transcript)
        pratham_context = []
        display_limit = 90
        max_tokens = self.AI_MAX_TOKENS
        if pratham_intent == "quiz":
            # Quiz ki list + "kaun sa shuru karun?" (agla jawab = quiz chunna)
            self.last_quiz_list_time = time.monotonic()
            await self._start_quiz(transcript)
            return

        if pratham_intent:
            if pratham_intent == "quiz":
                self.last_quiz_list_time = time.monotonic()
            fetch_started = time.monotonic()
            ok, payload = await fetch_pratham_data(pratham_intent)
            logger.info(
                "Pratham data: device=%s intent=%s ok=%s took=%.2fs",
                self.device_id,
                pratham_intent,
                ok,
                time.monotonic() - fetch_started,
            )
            labels = PRATHAM_INTENT_LABELS
            if ok:
                context_text = (
                    f"MyPratham portal se live {labels.get(pratham_intent, pratham_intent)} data (JSON):\n"
                    f"{payload}\n\n"
                    "Agar user ka sawal is data ke baare mein hai (list, kitne hain, kaunse hain) "
                    "to sirf isi data se jawab dein, apni taraf se kuch na banayein. "
                    "Agar sawal general hai (jaise exam ki taiyari kaise karein) to normal jawab dein. "
                    "speech: kitne items hain aur sabse upar ke 2-3 ke naam (aur zaroori detail "
                    "jaise questions ya location) chhote mein batayein. "
                    "display: pehli line par heading (jaise 'Jobs: 3'), phir har item nayi line "
                    "par '1. naam' format mein, zyada se zyada 5 items, 200 characters tak."
                )
            else:
                context_text = (
                    f"User ne {labels.get(pratham_intent, pratham_intent)} maanga, lekin data nahi mil paya: {payload} "
                    "User ko vinamrata se batayein ki abhi data nahi mil raha, thodi der baad try karein."
                )
            pratham_context = [{"role": "system", "content": context_text}]
            display_limit = 200
            max_tokens = max(self.AI_MAX_TOKENS, 250)

        # Knowledge Base: dashboard par upload kiye documents mein jawab dhoondhein
        kb_context = []
        if not pratham_context and (_pratham_setting("KB_ENABLED") or "1") == "1":
            try:
                kb_started = time.monotonic()
                limit = int(_pratham_setting("KB_MAX_CHUNKS") or 5)
                hits = await kb_search(transcript, limit, None, self.device_id)
                if not hits and re.search(r"[\u0900-\u097F]", transcript or ""):
                    extra = await kb_keywords_ai(transcript)
                    if extra:
                        hits = await kb_search(transcript, limit, extra, self.device_id)
                logger.info("KB search: device=%s hits=%d took=%.2fs %s", self.device_id, len(hits),
                            time.monotonic() - kb_started, [h[2] for h in hits][:3])
                if hits:
                    kb_text = "\n\n".join(f"[{h[1]} / {h[2]}]\n{h[3][:900]}" for h in hits)
                    kb_context = [{"role": "system", "content": (
                        "Neeche Knowledge Base (company ke apne documents) se mile hisse hain. "
                        "Agar user ka sawal inse juda hai to SIRF inhi ke aadhar par sahi jawab dein, "
                        "apni taraf se tathya na banayein; jawab chhota rakhein (2 vakya). "
                        "Agar sawal inse juda nahi hai to inhe nazarandaz karke normal jawab dein.\n\n"
                        + kb_text[:5000]
                    )}]
                    max_tokens = max(max_tokens, 260)
            except Exception:
                logger.exception("KB search failed: device=%s", self.device_id)

        # AI response: Whisper transcript ko OpenAI ko bhejein
        api_key = llm_api_key()

        if not api_key:
            logger.error("Koi AI key set nahi: .env mein GROQ_API_KEY (AI_PROVIDER=groq) ya OPENAI_API_KEY daalein")
            ai_reply_text = "Maaf kijiye, AI service configure nahi hai."
            display_text = "AI service configure nahi hai."
        else:
            display_text = ""
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await llm_post(
                    client,
                    json_body={
                            "model": "gpt-4o-mini",
                            "messages": (
                                [
                                    {
                                        "role": "system",
                                        "content": (
                                            "Aap ek helpful Hindi voice assistant hain. "
                                            "User ki baat ka seedha jawab dein; "
                                            "uske words ko bas repeat na karein. "
                                            # Voice ke liye: chhota jawab, Devanagari mein
                                            # (gTTS Hindi voice Roman Hinglish theek se nahi bolti).
                                            "Yeh jawab speaker par bola jayega, isliye "
                                            "zyada se zyada 2 chhote vakya (40 shabd tak) mein "
                                            "jawab dein. Hindi Devanagari lipi mein likhein. "
                                            "List, bullet, emoji ya markdown ka use na karein. "
                                            "Agar user aur jaanna chahe to woh khud poochega. "
                                            # Reminder sirf alag code se save hote hain
                                            "Aap khud reminder ya alarm save nahi karte; kabhi mat "
                                            "kahiye ki reminder lag gaya. Agar user koi time ya "
                                            "meeting batata hai to kahiye: 'reminder lagane ke liye "
                                            "boliye, jaise 3 baj kar 10 minute ka reminder'. "
                                            # Device ki TFT screen sirf A-Z, 0-9 dikha sakti hai
                                            "Output sirf JSON object ho, do keys ke saath: "
                                            "\"speech\": bolne wala jawab (Hindi Devanagari), "
                                            "\"display\": usi jawab ka chhota roop Roman "
                                            "Hinglish/English mein (sirf A-Z, 0-9 aur . , ? !), "
                                            "zyada se zyada 90 characters."
                                        ),
                                    },
                                ]
                                # Pichhli baatcheet yaad rahe (commercial chatbot jaisa)
                                # Asli samay/tareekh: AI apne man se time na bataye
                                + [{"role": "system", "content": current_time_context()}]
                                # Assistant ka naam (naam poochhne par yahi bataye)
                                + [{"role": "system", "content": (
                                    f"Aapka naam {get_assistant_name(self.device_id)} hai. "
                                    "Aap PrathamSmart device par chalne wale voice assistant hain. "
                                    "Naam poochha jaye to yahi naam batayein; apne aap ko ChatGPT, "
                                    "OpenAI, Llama ya kisi company ka model na batayein."
                                )}]
                                + list(CHAT_HISTORY.get(self.device_id, []))
                                # Jobs / quiz / learning ka live data (agar maanga ho)
                                + pratham_context
                                # Knowledge Base documents se mile hisse
                                + kb_context
                                + [
                                    {
                                        "role": "user",
                                        "content": transcript,
                                    },
                                ]
                            ),
                            "temperature": 0.5,
                            "max_tokens": max_tokens,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    response.raise_for_status()

                    raw_content = (
                        response.json()["choices"][0]["message"]["content"].strip()
                    )
                    ai_reply_text, display_text = parse_ai_reply(raw_content, display_limit)

                    if not ai_reply_text:
                        ai_reply_text = "Maaf kijiye, mujhe jawab nahi mila."

                # Baatcheet history mein save karein (last few turns)
                history = CHAT_HISTORY.setdefault(
                    self.device_id, deque(maxlen=self.CHAT_HISTORY_TURNS * 2)
                )
                history.append({"role": "user", "content": transcript})
                history.append({
                    "role": "assistant",
                    "content": json.dumps(
                        {"speech": ai_reply_text, "display": display_text},
                        ensure_ascii=False,
                    ),
                })

                logger.info(
                    "AI reply: device=%s text=%r",
                    self.device_id,
                    ai_reply_text,
                )

            except Exception:
                logger.exception("AI API call failed: device=%s", self.device_id)
                ai_reply_text = "Maaf kijiye, abhi main jawab nahi de pa raha."
                display_text = "Abhi jawab nahi de pa raha. Dobara try karein."

        await self._send_json({
            "type": "ai_reply",
            "text": ai_reply_text,
            # TFT ke liye chhota Roman text (screen Devanagari nahi dikha sakti)
            "display": display_text or ascii_for_display(ai_reply_text, display_limit),
        })

        await self._speak(ai_reply_text)

    # =========================================================
    # Meeting mode: "meeting mode on" -> sab kuch record + transcript,
    # "meeting band" -> file save + AI summary
    # =========================================================
    async def _transcribe_pcm(self, pcm_data):
        """Command-wala pipeline nahi: sirf text (meeting ke liye)."""
        pcm_np = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
        if pcm_np.size:
            pcm_np = pcm_np - float(np.mean(pcm_np))
            rms = float(np.sqrt(np.mean(pcm_np ** 2)))
            if rms > 0:
                gain = max(1.0, min(self.STT_TARGET_RMS / rms, self.STT_MAX_GAIN))
                pcm_np = np.clip(pcm_np * gain, -1.0, 1.0)
        engine = (_pratham_setting("STT_ENGINE") or "local").lower()
        text = None
        if engine in ("openai", "groq"):
            text = await openai_transcribe(pcm_np, None, engine)
        if text is None and FAST_WHISPER_MODEL is not None:
            text = await asyncio.to_thread(_run_fast_whisper, pcm_np, None)
        if text is None and WHISPER_MODEL is not None:
            result = await asyncio.to_thread(_run_whisper, WHISPER_MODEL, pcm_np, None)
            text = (result.get("text") or "").strip()
        return _collapse_repeats(text or "")

    async def _start_meeting(self, transcript):
        if self.meeting:
            await self._say("मीटिंग पहले से रिकॉर्ड हो रही है।", "MEETING already ON")
            return
        media_dir = getattr(settings, "MEDIA_ROOT", os.path.join(os.getcwd(), "media"))
        folder = os.path.join(str(media_dir), "meetings")
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now(REMINDER_TZ).strftime("%Y%m%d_%H%M%S")
        base = os.path.join(folder, f"{self.device_id}_{stamp}")
        wav = wave.open(base + ".wav", "wb")
        wav.setnchannels(self.CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(self.SAMPLE_RATE)
        self.meeting = {
            "base": base,
            "wav": wav,
            "started": time.monotonic(),
            "started_at": datetime.now(REMINDER_TZ),
            "lines": [],
            "seconds": 0.0,
        }
        logger.info("Meeting started: device=%s file=%s.wav", self.device_id, base)
        await self._say(
            "मीटिंग रिकॉर्डिंग शुरू। सबको बता दीजिए कि रिकॉर्डिंग हो रही है। "
            "रोकने के लिए बोलिए: मीटिंग बंद करो।",
            "MEETING REC ON\n'Meeting band karo' bolkar rokiye",
        )
        await self._send_json({"type": "meeting", "on": True})

    async def _meeting_segment(self, pcm_data):
        """Meeting chalte waqt har utterance: file mein jodein, text banayein."""
        meeting = self.meeting
        try:
            meeting["wav"].writeframes(pcm_data)
        except Exception:
            logger.exception("Meeting WAV write failed")
        meeting["seconds"] += len(pcm_data) / self.BYTES_PER_SECOND
        text = await self._transcribe_pcm(pcm_data)
        if not text:
            return
        elapsed = int(time.monotonic() - meeting["started"])
        stamp = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
        logger.info("Meeting [%s] %s", stamp, text)
        stop = is_meeting_stop(text)
        low = text.lower()
        looks_cmd = len(text.split()) <= 7 and (
            re.search(r"\b(m[eiu]+t+[ie]*n|meet|record)", low) or re.search(r"(मीट|मिट|मुट|रिकॉर्ड)", low))
        if not stop and looks_cmd:
            check_text = text
            if _groq_key():
                # Local model "meeting band karo" ko "Mitting Mallagarho" sun leta hai: Groq Hindi se dobara
                try:
                    pcm_np = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
                    alt = await openai_transcribe(
                        pcm_np, "मीटिंग बंद करो, meeting band karo, meeting stop, recording band karo",
                        "groq", language="hi")
                except Exception:
                    alt = None
                if alt:
                    logger.info("Meeting re-listen (groq): %r -> %r", text, alt)
                    check_text = alt
                    stop = is_meeting_stop(alt)
            if not stop:
                stop = await ai_meeting_intent(check_text, in_meeting=True) == "stop"
        if stop:
            await self._stop_meeting()
            return
        meeting["lines"].append(f"[{stamp}] {text}")
        if elapsed > MEETING_MAX_SECONDS:
            await self._stop_meeting(auto=True)

    async def _stop_meeting(self, auto=False):
        meeting, self.meeting = self.meeting, None
        if not meeting:
            await self._say("अभी कोई मीटिंग रिकॉर्ड नहीं हो रही।", "No meeting running")
            return
        await self._send_json({"type": "meeting", "on": False})
        try:
            meeting["wav"].close()
        except Exception:
            pass
        minutes = max(1, round((time.monotonic() - meeting["started"]) / 60))
        prefix = "मीटिंग का समय पूरा हुआ। " if auto else ""
        if not meeting["lines"] and meeting["seconds"] < 2:
            await self._say(f"{prefix}मीटिंग बंद, लेकिन कोई बात साफ़ सुनाई नहीं दी।", "MEETING STOPPED\nKuch suna nahi")
            return
        await self._say(f"{prefix}मीटिंग बंद। MoM बना रहा हूँ, थोड़ा समय लगेगा।",
                        f"MEETING SAVED\n{minutes} min\nMoM ban raha hai...")
        # Lamba kaam (poora transcript + AI MoM) background mein: device atke nahi
        task = asyncio.create_task(self._finalize_meeting(meeting, minutes))
        if not hasattr(self, "_bg_tasks"):
            self._bg_tasks = set()
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _finalize_meeting(self, meeting, minutes):
        base = meeting["base"]
        try:
            live = "\n".join(meeting["lines"])
            raw, engine = await transcribe_meeting_wav(base + ".wav")
            if not raw.strip():
                raw = re.sub(r"^\[\d+:\d+\]\s*", "", live, flags=re.M)
                engine = "live (device ke saath)"
            meta = {
                "date": meeting["started_at"].strftime("%d %b %Y"),
                "time": meeting["started_at"].strftime("%I:%M %p").lstrip("0"),
                "minutes": minutes,
                "device": self.device_id,
                "engine": engine,
            }
            logger.info("Meeting transcript: device=%s engine=%s chars=%d", self.device_id, engine, len(raw))
            mom = await generate_mom(raw, meta)
            with open(base + ".json", "w", encoding="utf-8") as fh:
                json.dump({"meta": meta, "mom": mom, "raw_transcript": raw, "live_transcript": live},
                          fh, ensure_ascii=False, indent=2)
            with open(base + ".txt", "w", encoding="utf-8") as fh:
                fh.write(mom_to_text(mom, meta, raw))
            with open(base + ".html", "w", encoding="utf-8") as fh:
                fh.write(mom_to_html(mom, meta, raw))
            LAST_MEETINGS[self.device_id] = base + ".txt"
            logger.info("Meeting saved: device=%s %s (.wav .txt .html .json) %d min, MoM=%s",
                        self.device_id, base, minutes, bool(mom))
        except Exception:
            logger.exception("Meeting finalize failed: device=%s", self.device_id)
            await self._say("मीटिंग की रिकॉर्डिंग सेव है, पर MoM नहीं बन पाया।", "MoM failed\nAudio saved")
            return
        title = (mom or {}).get("title") or "Meeting"
        speech = "MoM तैयार है। " + ((mom or {}).get("speech") or "")
        bullets = (mom or {}).get("discussion") or []
        display = f"MoM READY\n{ascii_for_display(title, 40)}\n" + "\n".join(bullets[:2])
        self._remember_turn("meeting band", speech, display.replace("\n", " "))
        try:
            # User se baat chal rahi ho to beech mein na bolein
            await asyncio.wait_for(self.worker_idle.wait(), timeout=60)
        except Exception:
            pass
        try:
            await self._say(speech, display)
        except Exception:
            pass   # device disconnect ho gaya ho to bhi MoM bhejein
        if (_pratham_setting("MOM_AUTO_SEND") or "1") == "1":
            await self._send_mom(base + ".txt", quiet_if_unset=True)

    async def _mail_compose(self, transcript):
        contacts = await mail_contacts_async()
        draft = await ai_compose_mail(transcript, list(contacts.keys()))
        if draft and not draft["body"] and (draft["to_name"] or draft["to_email"]):
            # Sirf "Atul ko mail karo": content poochhein, agla jawab mail ki baat banega
            self.pending_mail_content = {"first": transcript, "until": time.monotonic() + 60}
            who = draft["to_name"] or draft["to_email"]
            logger.info("Mail: content poochha: to=%r", who)
            await self._say(f"{who} को मेल में क्या लिखना है? बोलिए।",
                            f"Mail: {ascii_for_display(who, 24)}\nKya likhna hai? Boliye")
            return
        if not draft or not draft["body"]:
            await self._say("माफ़ कीजिए, मेल नहीं लिख पाया। दोबारा बोलिए।", "Mail nahi bana")
            return
        if "@" in draft["to_email"]:
            cands = [(draft["to_email"].replace(" ", ""), draft["to_email"].replace(" ", ""))]
        else:
            cands = resolve_contacts(draft["to_name"], contacts)
        if not cands:
            logger.info("Mail: contact nahi mila: %r (contacts=%s)", draft["to_name"], list(contacts))
            await self._say(
                f"{draft['to_name'] or 'उस व्यक्ति'} का ईमेल पता मेरे पास नहीं है। "
                "सर्वर की MAIL_CONTACTS सेटिंग में नाम और ईमेल जोड़ दीजिए।",
                f"Contact nahi mila:\n{ascii_for_display(draft['to_name'], 30)}\nMAIL_CONTACTS mein jodiye")
            return
        if len(cands) > 1:
            cands = cands[:3]
            self.pending_mail_pick = {"draft": draft, "cands": cands, "until": time.monotonic() + 60}
            order = ["पहला", "दूसरा", "तीसरा"]
            names = ", ".join(f"{order[i]} {k.title()}" for i, (k, _v) in enumerate(cands))
            await self._say(f"{draft['to_name']} नाम के {len(cands)} लोग हैं: {names}. किसे भेजूँ?",
                            "Kaun sa?\n" + "\n".join(f"{i}. {ascii_for_display(k.title(), 24)}"
                                                    for i, (k, _v) in enumerate(cands, 1)))
            return
        await self._mail_make_draft(transcript, draft, cands[0][1], cands[0][0])

    async def _mail_pick(self, transcript):
        """'Kaun sa Atul?' ka jawab. Return True agar handle kiya."""
        pend = self.pending_mail_pick
        t = (transcript or "").lower()
        if _contains_any(t, _MAIL_NO):
            self.pending_mail_pick = None
            await self._say("ठीक है, मेल रद्द कर दिया।", "Mail cancel")
            return True
        idx = pick_contact(transcript, pend["cands"])
        if idx is None:
            return False
        self.pending_mail_pick = None
        name, addr = pend["cands"][idx]
        await self._mail_make_draft(transcript, pend["draft"], addr, name)
        return True

    async def _mail_make_draft(self, transcript, draft, to_addr, to_label):
        draft = dict(draft)
        draft["to_name"] = to_label.title() if "@" not in to_label else draft["to_name"]
        if not draft.get("subject"):
            # body ki pehli asli line (Dear/Hi ke baad) se subject
            lines = [l.strip() for l in draft["body"].splitlines() if l.strip()]
            core = next((l for l in lines if not re.match(r"^(dear|hi|hello|namaste|respected)\b", l, re.I)), "")
            draft["subject"] = (re.split(r"[.!?]", core)[0][:70] or "Message").strip()
        msg = build_mail(to_addr, draft["subject"], draft["body"])
        try:
            ok, info = await asyncio.to_thread(gmail_save_draft_sync, msg)
        except Exception as err:
            logger.exception("Gmail draft save failed")
            ok, info = False, type(err).__name__
        logger.info("Mail draft: device=%s to=%s subject=%r draft_saved=%s (%s)",
                    self.device_id, to_addr, draft["subject"], ok, info)
        self.pending_mail = {"msg": msg, "to": to_addr, "until": time.monotonic() + 90,
                             "draft_folder": info if ok else None}
        where = "जीमेल ड्राफ्ट में सेव है। " if ok else ""
        name = draft["to_name"] or to_addr.split("@")[0]
        # Chhota sawal: lamba bolne par user beech mein "haan" bol deta tha (tab mic band hota hai)
        speech = f"{name} को मेल तैयार है। भेज दूँ?"
        display = f"MAIL DRAFT\nTo: {ascii_for_display(name, 24)}\n{ascii_for_display(draft['subject'], 60)}\nBhejein? Haan / Nahi"
        self._remember_turn(transcript, speech, display.replace("\n", " "))
        await self._say(speech, display)

    async def _mail_confirm(self, transcript):
        """Return True agar jawab mail ke liye tha."""
        t = " " + (transcript or "").lower().strip(" .!?।") + " "
        pending = self.pending_mail
        if _contains_any(t, _MAIL_NO):
            self.pending_mail = None
            await self._say("ठीक है, मेल नहीं भेजा। ड्राफ्ट जीमेल में रखा है।", "Mail nahi bheja\nDraft Gmail mein")
            return True
        if _contains_any(t, _MAIL_YES):
            self.pending_mail = None
            try:
                ok, info = await asyncio.to_thread(send_mail_sync, pending["msg"])
            except Exception as err:
                logger.exception("Mail send failed")
                ok, info = False, type(err).__name__
            logger.info("Mail send: device=%s to=%s ok=%s %s", self.device_id, pending["to"], ok, info)
            if ok and pending.get("draft_folder"):
                try:
                    removed = await asyncio.to_thread(gmail_delete_draft_sync,
                                                      pending["msg"]["Message-ID"], pending["draft_folder"])
                    logger.info("Mail draft removed after send: %s", removed)
                except Exception:
                    logger.exception("Draft delete failed (mail to chala gaya)")
            if ok:
                await self._say("मेल भेज दिया।", f"MAIL SENT\n{ascii_for_display(pending['to'], 40)}")
            else:
                await self._say("मेल नहीं भेज पाया। ड्राफ्ट जीमेल में है, वहीं से भेज दीजिए।", f"Mail fail: {info}"[:80])
            return True
        return False   # kuch aur bola: normal flow

    async def _send_mom(self, txt_path=None, quiet_if_unset=False, only=None):
        """MoM email / WhatsApp par bhejein aur bolkar batayein."""
        if txt_path is None:
            txt_path = LAST_MEETINGS.get(self.device_id)
            if not txt_path:
                media_dir = getattr(settings, "MEDIA_ROOT", os.path.join(os.getcwd(), "media"))
                folder = os.path.join(str(media_dir), "meetings")
                try:
                    files = sorted(f for f in os.listdir(folder)
                                   if f.startswith(f"{self.device_id}_") and f.endswith(".txt"))
                    txt_path = os.path.join(folder, files[-1]) if files else None
                except OSError:
                    txt_path = None
        if not txt_path or not os.path.isfile(txt_path):
            await self._say("भेजने के लिए कोई मीटिंग नहीं मिली।", "No meeting to send")
            return
        results = []
        if only in (None, "email"):
            results.append(("email",) + await send_mom_email(txt_path))
        if only in (None, "whatsapp"):
            results.append(("whatsapp",) + await send_mom_whatsapp(txt_path))
        sent = [name for name, ok, _ in results if ok]
        logger.info("MoM send: device=%s file=%s results=%s", self.device_id, txt_path, results)
        if sent:
            names = " और ".join("ईमेल" if n == "email" else "व्हाट्सएप" for n in sent)
            await self._say(f"मीटिंग का MoM {names} पर भेज दिया।",
                            "MoM SENT\n" + ", ".join(n.upper() for n in sent))
        elif not quiet_if_unset or any("set nahi" not in d for _, _, d in results):
            await self._say("MoM नहीं भेज पाया। सर्वर की सेटिंग जांचें।",
                            "MoM send failed\n" + "\n".join(d for _, _, d in results)[:150])

    async def _speak_last_meeting(self):
        path = LAST_MEETINGS.get(self.device_id)
        if not path:
            media_dir = getattr(settings, "MEDIA_ROOT", os.path.join(os.getcwd(), "media"))
            folder = os.path.join(str(media_dir), "meetings")
            try:
                files = sorted(f for f in os.listdir(folder)
                               if f.startswith(f"{self.device_id}_") and f.endswith(".txt"))
                path = os.path.join(folder, files[-1]) if files else None
            except OSError:
                path = None
        if not path or not os.path.isfile(path):
            await self._say("अभी कोई सेव की हुई मीटिंग नहीं मिली।", "No saved meeting")
            return
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        summary_part = content.split("TRANSCRIPT")[0]
        bullets = [l[2:].strip() for l in summary_part.splitlines() if l.startswith("- ")]
        if not bullets:
            await self._say("पिछली मीटिंग का सारांश नहीं बन पाया था।", "No summary")
            return
        speech = "पिछली मीटिंग की मुख्य बातें: " + "। ".join(bullets[:4]) + "।"
        await self._say(speech, "LAST MEETING\n" + "\n".join(bullets[:4]))

    def _stt_prompt(self):
        """Whisper ko context: quiz ke naam/options, taaki 'Excel wala' sahi sune."""
        extra = []
        quiz = getattr(self, "quiz", None)
        if quiz:
            q = quiz["questions"][quiz["index"]]
            extra.append("Options: " + ", ".join(
                f"{_OPTION_LETTERS[i]} {o}" for i, o in enumerate(q["options"])
            ))
        pick = getattr(self, "quiz_pick", None)
        if pick:
            extra.append("Quiz: " + ", ".join(e["name"] for e in pick["exams"]))
        pm = getattr(self, "pending_mail", None)
        if pm and time.monotonic() < pm.get("until", 0):
            extra.append("जवाब: हाँ, हां, हाँ भेज दो, भेज दो, भेजो, ok, yes, send, नहीं, मत भेजो, cancel")
        return " ".join([STT_VOCAB_PROMPT] + extra)

    def _awaiting_reply(self):
        """Device ne kuch poochha hai (haan/nahi, option, time) aur jawab ka wait hai?"""
        now_m = time.monotonic()
        pick = getattr(self, "quiz_pick", None)
        return bool(
            getattr(self, "quiz", None)
            or (pick and now_m < pick.get("until", 0))
            or now_m < getattr(self, "pending_reminder_until", 0.0)
            or any((getattr(self, k, None) or {}).get("until", 0) > now_m
                   for k in ("pending_mail", "pending_mail_pick", "pending_mail_content"))
        )

    # =========================================================
    # Voice quiz
    # =========================================================
    async def _say(self, speech, display, quiz_screen=None):
        """ai_reply (TFT) + TTS (speaker). quiz_screen = TFT quiz layout."""
        display = ascii_for_display(display, 200) or "..."
        await self._send_json({"type": "ai_reply", "text": speech, "display": display})
        if quiz_screen is not None:
            await self._send_json(quiz_screen)
        await self._speak(speech)

    def _quiz_screen(self, feedback="", fb_kind=0):
        """ESP32 TFT quiz layout: Q n/total, score, sawal, options A-D."""
        quiz = self.quiz
        q = quiz["questions"][quiz["index"]]
        return {
            "type": "quiz",
            "n": quiz["index"] + 1,
            "total": len(quiz["questions"]),
            "score": quiz["score"],
            "q": q.get("q_disp") or "Sawal Hindi mein hai - suniye",
            "options": [o or "(suniye)" for o in (q.get("opts_disp") or [""] * len(q["options"]))][:4],
            "feedback": ascii_for_display(feedback, 40),
            "fb": fb_kind,
        }

    @staticmethod
    def _quiz_question_texts(quiz):
        q = quiz["questions"][quiz["index"]]
        n, total = quiz["index"] + 1, len(quiz["questions"])
        opts_speech = " ".join(
            f"{_OPTION_LETTERS[i]}: {opt}." for i, opt in enumerate(q["options"])
        )
        speech = f"सवाल {n}. {q['q']} {opts_speech}"
        q_ascii = ascii_for_display(q["q"], 70)
        lines = [f"Q{n}/{total} {q_ascii}".strip()]
        for i, opt in enumerate(q["options"]):
            lines.append(f"{_OPTION_LETTERS[i]}) {ascii_for_display(opt, 30)}")
        return speech, "\n".join(lines)

    async def _prefetch_exams(self):
        try:
            exam_url = _pratham_setting("PRATHAM_EXAM_URL") or "/school/exams/D/?page=1"
            cached = _EXAM_LIST_CACHE.get(exam_url)
            if cached and time.monotonic() - cached[0] < 600:
                return
            ok, data = await pratham_get_json(exam_url)
            if ok and parse_exam_list(data):   # khaali list cache na ho
                _EXAM_LIST_CACHE[exam_url] = (time.monotonic(), data)
        except Exception:
            logger.debug("Exam prefetch failed", exc_info=True)

    async def _start_quiz(self, transcript):
        self.quiz = None
        exam_url = _pratham_setting("PRATHAM_EXAM_URL") or "/school/exams/D/?page=1"
        cached = _EXAM_LIST_CACHE.get(exam_url)
        if cached and time.monotonic() - cached[0] < 120 and parse_exam_list(cached[1]):
            ok, data = True, cached[1]   # 2 min tak dobara fetch nahi (tez jawab)
        else:
            ok, data = await pratham_get_json(exam_url)
            if ok and parse_exam_list(data):
                _EXAM_LIST_CACHE[exam_url] = (time.monotonic(), data)
        exams = parse_exam_list(data) if ok else []
        logger.info("Quiz: exams=%d (%s)", len(exams), [e["name"] for e in exams][:6])
        if ok and not exams:
            # API ne kya bheja? (debug ke liye pehle 400 akshar)
            logger.warning("Quiz: exam list khaali. url=%s response=%s", exam_url,
                           json.dumps(data, ensure_ascii=False)[:400])
        if not exams:
            await self._say(
                "माफ़ कीजिए, अभी कोई क्विज़ नहीं मिला।",
                "Quiz nahi mila. " + ("" if ok else str(data)),
            )
            return
        exam = pick_exam(transcript, exams)
        if exam is None and _contains_any(transcript.lower(), QUIZ_START_WORDS) and len(transcript) > 12:
            idx = await ai_pick_choice(transcript, [e["name"] for e in exams], "quiz")
            exam = exams[idx] if idx is not None else None
        if exam is None:
            self.quiz_pick = {"exams": exams[:5], "until": time.monotonic() + 60}
            names = ", ".join(f"{i}. {e['name']}" for i, e in enumerate(exams[:5], 1))
            display = "Kaun sa quiz?\n" + "\n".join(
                f"{i}. {e['name']}" for i, e in enumerate(exams[:5], 1)
            )
            await self._say(f"कौन सा क्विज़ शुरू करूं? {names}. नाम या नंबर बोलिए।", display)
            return
        await self._begin_exam(exam)

    async def _begin_exam(self, exam):
        self.quiz_pick = None
        ok, qdata = await pratham_get_json(f"/school/questions/{exam['id']}")
        questions = parse_questions(qdata) if ok else []
        if ok and not questions:
            sample = _find_dict_list(qdata)[:1] or qdata
            logger.warning("Quiz: questions JSON samajh nahi aaya, AI se try. sample=%s",
                           json.dumps(sample, ensure_ascii=False)[:600])
            questions = await normalize_questions_with_ai(
                qdata, llm_api_key(), QUIZ_MAX_QUESTIONS
            )
        logger.info("Quiz: exam=%r id=%s questions=%d with_answer=%d",
                    exam["name"], exam["id"], len(questions),
                    sum(1 for q in questions if q["correct"] is not None))
        if not questions:
            await self._say(
                f"माफ़ कीजिए, {exam['name']} के सवाल नहीं मिल पाए।",
                f"{exam['name']}: sawal nahi mile.",
            )
            return
        questions = questions[:QUIZ_MAX_QUESTIONS]
        await romanize_quiz_for_display(questions)
        self.quiz = {
            "exam": exam,
            "questions": questions,
            "index": 0,
            "score": 0,
            "retries": 0,
            "last": time.monotonic(),
        }
        q_speech, q_display = self._quiz_question_texts(self.quiz)
        intro = (
            f"{exam['name']} क्विज़ शुरू। कुल {len(questions)} सवाल। "
            "हर सवाल के बाद ऑप्शन A, ऑप्शन B, ऑप्शन C या ऑप्शन D बोलिए। रोकने के लिए क्विज़ बंद बोलिए। "
        )
        await self._say(intro + q_speech, q_display, self._quiz_screen())

    async def _finish_quiz(self, prefix_speech="", prefix_display=""):
        quiz, self.quiz = self.quiz, None
        self.quiz_pick = None
        self.last_quiz_list_time = 0.0
        # Quiz band hone ke turant baad (apni hi awaaz / galat sunai) quiz dobara na shuru ho
        self.quiz_block_until = time.monotonic() + 8.0
        await self._send_json({"type": "quiz_end"})
        total = len(quiz["questions"])
        score = quiz["score"]
        logger.info("Quiz finished: device=%s exam=%r score=%d/%d",
                    self.device_id, quiz["exam"]["name"], score, total)
        speech = f"{prefix_speech} क्विज़ खत्म! आपने {total} में से {score} सही किए।".strip()
        display = f"{prefix_display}\nQUIZ DONE\nScore: {score}/{total}".strip()
        self._remember_turn(f"{quiz['exam']['name']} quiz", speech, display.replace("\n", " "))
        await self._say(speech, display)
        await self._submit_quiz_result(quiz)

    async def _submit_quiz_result(self, quiz):
        """Score MyPratham mein save: POST /school/results/.
        Payload ka format .env PRATHAM_RESULT_TEMPLATE se (MyPratham ka exact format
        jaane bina galat data na bheje). Placeholders: {exam_id} {score} {total}
        {percentage} {answers_json} {date} {datetime}"""
        template = _pratham_setting("PRATHAM_RESULT_TEMPLATE")
        total = len(quiz["questions"])
        if (_pratham_setting("PRATHAM_RESULT_SEND") or "1") != "1":
            return
        now = datetime.now(REMINDER_TZ)
        if not template:
            # GET /school/results/ ke format se banaya payload (exam + uski board/
            # class/subject/chapter ids). Score: % (pass_percentage jaisa) default;
            # .env PRATHAM_RESULT_SCORE=marks par sahi jawabon ki ginti.
            raw = quiz["exam"].get("raw") or {}

            def _id(v):
                if isinstance(v, dict):
                    return v.get("id")
                if isinstance(v, list):
                    return _id(v[0]) if v else None
                return v

            pct = round(100.0 * quiz["score"] / total, 2) if total else 0.0
            score_value = float(quiz["score"]) if (_pratham_setting("PRATHAM_RESULT_SCORE") or "percent") == "marks" else pct
            payload = {
                "exam": quiz["exam"]["id"],
                "result_name": quiz["exam"]["name"],
                "score": score_value,
            }
            for key in ("boards", "class_obj", "subject", "chapter"):
                val = _id(raw.get(key))
                if val is not None:
                    payload[key] = val
            body_text = json.dumps(payload, ensure_ascii=False)
            template = body_text   # neeche wahi raasta (placeholders nahi hain)
        values = {
            "{exam_id}": json.dumps(quiz["exam"]["id"]),
            "{score}": str(quiz["score"]),
            "{total}": str(total),
            "{percentage}": str(round(100.0 * quiz["score"] / total, 2) if total else 0),
            "{answers_json}": json.dumps(quiz.get("answers", []), ensure_ascii=False),
            "{date}": json.dumps(now.strftime("%Y-%m-%d")),
            "{datetime}": json.dumps(now.isoformat()),
        }
        body_text = template
        for key, val in values.items():
            body_text = body_text.replace(key, val)
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError:
            logger.error("PRATHAM_RESULT_TEMPLATE JSON galat hai: %s", body_text[:300])
            return
        url = _pratham_setting("PRATHAM_RESULT_URL") or f"{API_BASE_URL}/school/results/"
        token = _pratham_setting("PRATHAM_USER_TOKEN")
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                res = await client.post(url, json=payload, headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/json",
                })
            if res.status_code in (200, 201):
                logger.info("Quiz result saved on MyPratham: exam=%s score=%d/%d HTTP %s",
                            quiz["exam"]["id"], quiz["score"], total, res.status_code)
            else:
                logger.warning("Quiz result POST failed: HTTP %s payload=%s response=%s",
                               res.status_code, json.dumps(payload, ensure_ascii=False)[:400], res.text[:400])
        except Exception:
            logger.exception("Quiz result POST error")

    async def _quiz_input(self, transcript):
        """Quiz mode mein har baat yahan. Return True = handle ho gaya."""
        text = (transcript or "").lower()

        # Exam chunna baaki hai
        if self.quiz is None and self.quiz_pick:
            exams = self.quiz_pick["exams"]
            exam = pick_exam(transcript, exams)
            if exam is None and not _contains_any(text, QUIZ_STOP_WORDS):
                idx = await ai_pick_choice(transcript, [e["name"] for e in exams], "quiz")
                exam = exams[idx] if idx is not None else None
            if exam is None:
                self.quiz_pick = None
                if _contains_any(text, QUIZ_STOP_WORDS):
                    await self._say("ठीक है, क्विज़ रद्द।", "Quiz cancel.")
                    return True
                return False  # kuch aur poocha: normal flow
            await self._begin_exam(exam)
            return True

        quiz = self.quiz
        if quiz is None:
            return False
        if time.monotonic() - quiz["last"] > 300:  # 5 min se koi jawab nahi
            self.quiz = None
            await self._send_json({"type": "quiz_end"})
            return False
        quiz["last"] = time.monotonic()
        q = quiz["questions"][quiz["index"]]

        if _contains_any(text, QUIZ_STOP_WORDS) and parse_quiz_answer(transcript, q["options"]) is None:
            await self._finish_quiz("ठीक है, क्विज़ रोक दिया।", "Quiz stopped.")
            return True

        if _contains_any(text, QUIZ_REPEAT_WORDS):
            speech, display = self._quiz_question_texts(quiz)
            await self._say(speech, display, self._quiz_screen("Dobara suniye"))
            return True

        fb_kind = 0
        if _contains_any(text, QUIZ_SKIP_WORDS):
            feedback, fb_display = "ठीक है, अगला सवाल।", "Skipped."
        else:
            choice = parse_quiz_answer(transcript, q["options"])
            pcm_np = getattr(self, "_last_pcm_np", None)
            if choice is None and pcm_np is not None:
                # Jawab option ke shabdon mein (Hindi) bola ho: quiz STT English mein tha,
                # isliye Hindi mein dobara sunein, options ko hint bana kar.
                opts_prompt = "Jawab in mein se ek: " + "; ".join(str(o) for o in q["options"])
                alt = None
                try:
                    if _groq_key():
                        alt = await openai_transcribe(pcm_np, opts_prompt, "groq", language="hi")
                    elif FAST_WHISPER_MODEL is not None:
                        alt = await asyncio.to_thread(_run_fast_whisper, pcm_np, opts_prompt, "hi")
                except Exception:
                    logger.exception("Quiz re-listen failed")
                if alt and alt.strip() and alt.strip() != transcript.strip():
                    logger.info("Quiz re-listen (hi): device=%s %r -> %r", self.device_id, transcript, alt)
                    transcript = alt.strip()
                    choice = parse_quiz_answer(transcript, q["options"])
            if choice is None:
                # AI se poochhein: kaun sa option? ya quiz band / dobara / agla?
                labelled = [f"{_OPTION_LETTERS[i]}) {o}" for i, o in enumerate(q["options"])]
                n_opts = len(labelled)
                labelled += [
                    "STOP: quiz band / stop / khatam karo",
                    "REPEAT: sawal dobara / repeat",
                    "SKIP: agla sawal / skip",
                ]
                choice = await ai_pick_choice(transcript, labelled, "answer option or command")
                if choice == n_opts:
                    await self._finish_quiz("ठीक है, क्विज़ रोक दिया।", "Quiz stopped.")
                    return True
                if choice == n_opts + 1:
                    speech, display = self._quiz_question_texts(quiz)
                    await self._say(speech, display, self._quiz_screen("Dobara suniye"))
                    return True
                if choice == n_opts + 2:
                    choice = None
                    quiz["retries"] = 99   # neeche "agla sawal" wala raasta
            logger.info("Quiz answer: device=%s heard=%r choice=%s correct=%s",
                        self.device_id, transcript, choice, q["correct"])
            if choice is None:
                quiz["retries"] += 1
                if quiz["retries"] <= 2:
                    letters = ", ".join(_OPTION_LETTERS[: len(q["options"])])
                    await self._say(
                        f"समझ नहीं आया। {letters} में से एक बोलिए। सवाल दोबारा सुनने के लिए दोबारा बोलिए।",
                        f"Boliye: {letters}",
                        self._quiz_screen(f"Samjha nahi. Boliye: {letters}"),
                    )
                    return True
                feedback, fb_display = "ठीक है, अगला सवाल।", "Skipped."
            elif q["correct"] is None:
                feedback = f"आपका जवाब {_OPTION_LETTERS[choice]} नोट कर लिया।"
                fb_display = f"Answer {_OPTION_LETTERS[choice]} noted."
            elif choice == q["correct"]:
                quiz["score"] += 1
                feedback, fb_display = "सही जवाब!", f"{_OPTION_LETTERS[choice]} - Sahi! +1"
                fb_kind = 1
            else:
                c = q["correct"]
                feedback = f"गलत। सही जवाब है {_OPTION_LETTERS[c]}: {q['options'][c]}।"
                c_disp = (q.get("opts_disp") or [""] * len(q["options"]))[c] or ascii_for_display(q["options"][c], 40)
                fb_display = f"Galat. Sahi: {_OPTION_LETTERS[c]}) {c_disp}"
                fb_kind = 2

        quiz.setdefault("answers", []).append({
            "question_id": q.get("id"),
            "selected_index": choice,
            "selected_option": (q["options"][choice] if isinstance(choice, int)
                                and 0 <= choice < len(q["options"]) else None),
            "selected_option_id": ((q.get("option_ids") or [None] * 6)[choice]
                                   if isinstance(choice, int) and choice < len(q.get("option_ids") or []) else None),
            "is_correct": (choice == q["correct"]) if q["correct"] is not None and isinstance(choice, int) else None,
        })
        quiz["retries"] = 0
        quiz["index"] += 1
        if quiz["index"] >= len(quiz["questions"]):
            await self._finish_quiz(feedback, fb_display)
            return True
        q_speech, q_display = self._quiz_question_texts(quiz)
        await self._say(f"{feedback} {q_speech}", f"{fb_display}\n{q_display}",
                        self._quiz_screen(fb_display, fb_kind))
        return True

    # =========================================================
    # Reminders
    # =========================================================
    def _remember_turn(self, user_text, speech, display):
        history = CHAT_HISTORY.setdefault(
            self.device_id, deque(maxlen=self.CHAT_HISTORY_TURNS * 2)
        )
        history.append({"role": "user", "content": user_text})
        history.append({
            "role": "assistant",
            "content": json.dumps({"speech": speech, "display": display}, ensure_ascii=False),
        })

    async def _handle_reminder(self, transcript, followup=False):
        """Return True agar reminder ne jawab de diya; False = normal AI ko jaane dein."""
        self.pending_reminder_until = 0.0
        api_key = llm_api_key()
        info = await extract_reminder(
            transcript, api_key, list(CHAT_HISTORY.get(self.device_id, []))
        )
        logger.info(
            "Reminder intent: device=%s action=%s title=%r when=%s",
            self.device_id, info["action"], info["title"], info["when"],
        )

        if info["action"] not in ("add", "list"):
            if followup and not detect_reminder_intent(transcript):
                return False  # user ne kuch aur poocha: normal AI jawab de
            speech = "ठीक है, रिमाइंडर नहीं लगाया।"
            await self._send_json({"type": "ai_reply", "text": speech, "display": "Reminder cancel."})
            self._remember_turn(transcript, speech, "Reminder cancel.")
            await self._speak(speech)
            return True

        if info["action"] == "list":
            items = await list_reminders(self.device_id)
            if not items:
                speech = "अभी कोई रिमाइंडर सेट नहीं है।"
                display = "Reminders: 0\nKoi reminder set nahi hai."
            else:
                first_when, first_title = items[0]
                speech = (
                    f"आपके {len(items)} रिमाइंडर हैं। अगला {_hindi_time_phrase(first_when)}: "
                    f"{first_title}।"
                )
                lines = [f"Reminders: {len(items)}"] + [
                    f"{i}. {_display_time(w)} {t}" for i, (w, t) in enumerate(items, 1)
                ]
                display = "\n".join(lines)
            await self._send_json({
                "type": "ai_reply",
                "text": speech,
                "display": ascii_for_display(display, 200),
            })
            self._remember_turn(transcript, speech, display)
            await self._speak(speech)
            return True

        when = info["when"]
        if when is None:
            speech = "रिमाइंडर किस समय का लगाऊं? जैसे बोलिए, आज शाम 5 बजे।"
            await self._send_json({
                "type": "ai_reply",
                "text": speech,
                "display": "Time batayein. Jaise: aaj shaam 5 baje reminder",
            })
            self._remember_turn(transcript, speech, "Reminder ka time batayein")
            await self._speak(speech)
            # Agla jawab (sirf time bhi) isi reminder ka maana jayega
            self.pending_reminder_until = time.monotonic() + 45
            return True

        try:
            ok, detail = await save_reminder(self.device_id, info.get("save_title") or info["title"], when)
        except Exception as err:
            logger.exception("Reminder save failed: device=%s", self.device_id)
            ok, detail = False, str(err)

        if ok:
            spoken_topic = info.get("title_hi") or info["title"]
            if spoken_topic and spoken_topic != "Reminder":
                speech = f"ठीक है, {_hindi_time_phrase(when)} {spoken_topic} का रिमाइंडर लगा दिया।"
            else:
                speech = f"ठीक है, {_hindi_time_phrase(when)} का रिमाइंडर लगा दिया।"
            display = f"REMINDER SET\n{_display_time(when)}\n{info['title']}"
            logger.info("Reminder added: device=%s id=%s at=%s", self.device_id, detail, when)
        else:
            logger.error("Reminder NOT saved: device=%s reason=%s", self.device_id, detail)
            speech = "माफ़ कीजिए, रिमाइंडर सेव नहीं हो पाया।"
            display = "Reminder save nahi hua. Server log dekhein."

        await self._send_json({
            "type": "ai_reply",
            "text": speech,
            "display": ascii_for_display(display, 200),
        })
        self._remember_turn(transcript, speech, display.replace("\n", " "))
        await self._speak(speech)
        return True

    async def _reminder_loop(self):
        """Har kuch second mein dekhein: kisi reminder ka time hua? To bolein."""
        try:
            while self.ws_open:
                await asyncio.sleep(REMINDER_CHECK_SECONDS)
                if not self.ws_open:
                    break
                # User bol raha ho ya jawab chal raha ho to beech mein na bolein
                if self.in_speech or not self.worker_idle.is_set() or self.keepalive_active:
                    continue
                try:
                    due = await pop_due_reminders(self.device_id)
                except Exception:
                    logger.exception("Reminder check failed: device=%s", self.device_id)
                    continue
                for when, title in due:
                    if not self.ws_open:
                        break
                    logger.info("Reminder due: device=%s title=%r at=%s", self.device_id, title, when)
                    if _is_generic_title(title):
                        speech = "रिमाइंडर का समय हो गया।"
                    else:
                        speech = f"रिमाइंडर: {title} का समय हो गया।"
                    shown = ascii_for_display(title, 60) or "Reminder"
                    await self._send_json({
                        "type": "ai_reply",
                        "text": speech,
                        "display": ascii_for_display(f"REMINDER\n{_display_time(when)}\n{shown}", 200),
                    })
                    await self._speak(speech)
        except asyncio.CancelledError:
            pass

    async def _speak(self, text):
        """Text ko gTTS se bolwa kar ESP32 ko real-time PCM stream karein.
        (Pehle yeh code AI reply ke andar tha; ab voice commands ke
        confirmation bhi isi se bolte hain.)"""
        if not HAS_TTS:
            logger.error("TTS unavailable: gTTS/pydub install check karein")
            await self._send_json({"type": "tts_unavailable"})
            return

        try:
            def make_tts_pcm(text):
                tts = gTTS(text=text, lang="hi")

                mp3_buffer = io.BytesIO()
                tts.write_to_fp(mp3_buffer)
                mp3_buffer.seek(0)

                audio = AudioSegment.from_file(
                    mp3_buffer,
                    format="mp3",
                )
                audio = (
                    audio
                    .set_frame_rate(self.SAMPLE_RATE)
                    .set_channels(self.CHANNELS)
                    .set_sample_width(2)
                )
                return audio.raw_data

            # Sentence-by-sentence TTS: pehle poore jawab ka TTS banne ka wait
            # hota tha (2-11 sec). Ab pehla vakya banate hi bolna shuru, aur
            # jab tak woh bajta hai, agla vakya background mein ban raha hota hai.
            sentences = split_into_sentences(text)
            if not sentences:
                sentences = [text]
            # Pehla vakya chhota (jaldi shuru), baaki ko jod kar bade tukde:
            # kam gTTS calls = vakyon ke beech kam ruk-ruk
            if len(sentences) > 2:
                rest, merged = sentences[1:], []
                for part in rest:
                    if merged and len(merged[-1]) < 120:
                        merged[-1] = f"{merged[-1]} {part}"
                    else:
                        merged.append(part)
                sentences = [sentences[0]] + merged

            tts_started = time.monotonic()
            # Saare vakyon ka TTS ek saath shuru (max 3 parallel). Pehle agla vakya
            # tabhi banna shuru hota tha jab pichhla bajne lagta; Google TTS der se
            # aata to vakyon ke beech awaaz atak jaati thi.
            tts_sem = asyncio.Semaphore(3)

            async def _make(sentence):
                async with tts_sem:
                    return await asyncio.to_thread(make_tts_pcm, sentence)

            tts_tasks = [asyncio.create_task(_make(sent)) for sent in sentences]

            # PCM stream ke beech mein keepalive JSON na jaaye.
            stream_started = False

            # 16 kHz, mono, 16-bit PCM. Pehle 640 B (20 ms) ke 50 frame/sec jaate the:
            # ESP ka WebSocket task har frame par kaam karta hai, lamba jawab atakta tha.
            # Ab 1920 B (60 ms) = ~17 frame/sec. ESP ka WS buffer 2048 B hai, isse chhota.
            CHUNK_BYTES = _env_int("TTS_CHUNK_BYTES", 640)

            # Real-time pacing: pehle saara audio ek saath (9 ms mein) bhej diya jata tha,
            # ESP32 ka buffer overflow hota tha -> awaaz atakti/katti thi.
            # Ab sirf TTS_PREBUFFER_SECONDS aage bhejte hain.
            send_started = None
            sent_seconds = 0.0
            total_bytes = 0

            for index in range(len(sentences)):
                raw_pcm_bytes = await tts_tasks[index]

                if not self.ws_open:
                    for task in tts_tasks[index + 1:]:
                        task.cancel()
                    return

                if not stream_started:
                    stream_started = True
                    logger.info(
                        "TTS first audio: device=%s after=%.2fs sentences=%d",
                        self.device_id,
                        time.monotonic() - tts_started,
                        len(sentences),
                    )
                    utt_end = getattr(self, "_utterance_end_time", 0.0)
                    if utt_end:
                        logger.info(
                            "LATENCY: device=%s bolna-khatam -> awaaz-shuru = %.2fs",
                            self.device_id, time.monotonic() - utt_end,
                        )
                        self._utterance_end_time = 0.0

                    # Playback ke dauraan mic input ignore karein (echo se fake utterances).
                    # Total length abhi pata nahi; stream khatam hone par theek karenge.
                    self.mute_until = time.monotonic() + 3600
                    self._reset_vad()
                    self.keepalive_active = False

                    await self._send_json({
                        "type": "tts_start",
                        "codec": "pcm_s16le",
                        "sample_rate": self.SAMPLE_RATE,
                        "channels": self.CHANNELS,
                        "sample_width": 2,
                    })
                    send_started = time.monotonic()

                total_bytes += len(raw_pcm_bytes)

                for start in range(0, len(raw_pcm_bytes), CHUNK_BYTES):
                    if not self.ws_open:
                        return

                    chunk = raw_pcm_bytes[start:start + CHUNK_BYTES]
                    await self.send(bytes_data=chunk)
                    sent_seconds += len(chunk) / self.BYTES_PER_SECOND

                    ahead = sent_seconds - (time.monotonic() - send_started)
                    if ahead < 0:
                        # Hum late the (agla vakya der se bana): ESP ne itni der
                        # chup bajaya. Pichhda time "catch up" karne ke liye ek saath
                        # bahut audio na bhejein (ESP buffer overflow = awaaz kat-ti).
                        send_started -= ahead   # ahead manfi hai: clock aage
                        ahead = 0.0
                    prebuffer = getattr(self, "tts_prebuffer", self.TTS_PREBUFFER_SECONDS)
                    if ahead > prebuffer:
                        await asyncio.sleep(ahead - prebuffer)
                    else:
                        await asyncio.sleep(0.0)

            logger.info(
                "TTS sent: device=%s bytes=%d duration=%.2fs",
                self.device_id,
                total_bytes,
                total_bytes / self.BYTES_PER_SECOND,
            )

            if send_started is None:
                send_started = time.monotonic()

            # ESP ke buffer mein abhi bhi ~prebuffer jitna audio bacha hai (+ firmware
            # ka 0.2 s pre-roll). Pehle tts_complete turant chala jaata tha: ESP mic
            # chalu kar deta tha jabki speaker abhi bol raha tha -> apni hi awaaz
            # ("...quiz khatam") sun kar quiz dobara shuru ho jaata tha.
            # Ab bajna khatam hone tak ruk kar tts_complete bhejte hain.
            remaining = max(0.0, sent_seconds - (time.monotonic() - send_started))
            play_tail = remaining + 0.25
            self.mute_until = time.monotonic() + play_tail + self.ECHO_GUARD_SECONDS
            if play_tail > 0.05:
                await asyncio.sleep(min(play_tail, 2.0))

            await self._send_json({"type": "tts_complete"})

        except Exception as err:
            # Stream beech mein fail ho to mic ko hamesha ke liye mute na chhodein
            self.mute_until = time.monotonic() + self.ECHO_GUARD_SECONDS
            logger.exception("TTS failed: device=%s", self.device_id)
            await self._send_json({
                "type": "error",
                "stage": "tts",
                "message": str(err),
            })

    async def disconnect(self, close_code):
        self.ws_open = False

        for task in (
            getattr(self, "inactivity_task", None),
            getattr(self, "worker_task", None),
            getattr(self, "stop_task", None),
            getattr(self, "reminder_task", None),
        ):
            if task and not task.done():
                task.cancel()

        # Disconnect ke baad reply nahi bheja ja sakta; pending audio sirf save karein.
        pending_pcm = bytes(getattr(self, "pending_pcm", b"")) + bytes(
            getattr(self, "pcm_buffer", b"")
        )
        if hasattr(self, "pcm_buffer"):
            self.pcm_buffer.clear()
        if hasattr(self, "pending_pcm"):
            self.pending_pcm.clear()

        if pending_pcm:
            try:
                media_dir = getattr(
                    settings,
                    "MEDIA_ROOT",
                    os.path.join(os.getcwd(), "media"),
                )
                os.makedirs(media_dir, exist_ok=True)

                filename = os.path.join(
                    media_dir,
                    f"recorded_{self.device_id}_disconnect.wav",
                )

                await asyncio.to_thread(self._save_wav, filename, pending_pcm)

                logger.warning(
                    "Pending disconnect audio saved: device=%s bytes=%d",
                    self.device_id,
                    len(pending_pcm),
                )
            except Exception:
                logger.exception(
                    "Pending audio save failed: device=%s",
                    getattr(self, "device_id", "unknown"),
                )

        logger.info(
            "Audio WebSocket disconnected: device=%s packets=%d "
            "decoded_frames=%d code=%s",
            getattr(self, "device_id", "unknown"),
            getattr(self, "packet_count", 0),
            getattr(self, "pcm_frame_count", 0),
            close_code,
        )
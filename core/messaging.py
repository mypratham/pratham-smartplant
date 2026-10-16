# PrathamSmart: Telegram (user ka apna bot) + SMS (user ke Android phone se, SMS Gateway app)
# Sab sync (Django ORM + httpx); consumers se asyncio.to_thread se bulaayein.
import hashlib
import hmac
import logging
import re

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

TG_API = "https://api.telegram.org/bot{token}/{method}"
SMS_API = "https://api.sms-gate.app/3rdparty/v1"


# ---------------- Telegram ----------------
def tg_call(token, method, params=None, timeout=15):
    res = httpx.post(TG_API.format(token=token, method=method), json=params or {}, timeout=timeout)
    try:
        data = res.json()
    except Exception:
        data = {"ok": False, "description": f"HTTP {res.status_code}"}
    return data


def tg_check_token(token):
    """Return (bot_username, error)."""
    if not re.fullmatch(r"\d{5,16}:[A-Za-z0-9_-]{30,60}", token or ""):
        return "", "Token ka format galat hai (jaise 123456789:AAH...)"
    try:
        d = tg_call(token, "getMe")
    except Exception as err:
        return "", f"Telegram se connect nahi hua ({type(err).__name__})"
    if not d.get("ok"):
        return "", "Token galat hai ya bot band hai"
    return d["result"].get("username", ""), None


def _sig(device_pk, what):
    key = (getattr(settings, "SECRET_KEY", "") + ":tg-start").encode()
    return hmac.new(key, f"{device_pk}:{what}".encode(), hashlib.sha256).hexdigest()[:10]


def tg_start_param(device_pk, what):
    """what: 'me' (device ka maalik) ya contact id. Telegram start: [A-Za-z0-9_-], 64 tak."""
    w = "me" if what == "me" else f"c{int(what)}"
    return f"{w}_{_sig(device_pk, w)}"


def tg_link(bot_username, device_pk, what):
    return f"https://t.me/{bot_username}?start={tg_start_param(device_pk, what)}" if bot_username else ""


def tg_sync(device):
    """Bot ke naye /start messages padho, chat_id jodo. Return (linked_count, error)."""
    from core.models import DeviceContact, DeviceSettings
    from core.secretbox import unseal
    cfg = DeviceSettings.objects.filter(device=device).first()
    token = unseal(cfg.telegram_bot_token_enc) if cfg else ""
    if not token:
        return 0, "Telegram bot set nahi"
    try:
        d = tg_call(token, "getUpdates", {"timeout": 0, "allowed_updates": ["message"]})
    except Exception as err:
        return 0, f"Telegram se connect nahi hua ({type(err).__name__})"
    if not d.get("ok"):
        return 0, d.get("description") or "Telegram error"
    linked, last = 0, None
    for u in d.get("result", []):
        last = u.get("update_id", last)
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = (msg.get("chat") or {}).get("id")
        m = re.fullmatch(r"/start\s+(me|c\d+)_([0-9a-f]{10})", text)
        if not (m and chat_id):
            continue
        what, sig = m.group(1), m.group(2)
        if not hmac.compare_digest(sig, _sig(device.pk, what)):
            continue
        if what == "me":
            cfg.telegram_owner_chat_id = str(chat_id)
            cfg.save(update_fields=["telegram_owner_chat_id"])
            who = "aap"
        else:
            c = DeviceContact.objects.filter(device=device, id=int(what[1:])).first()
            if c is None:
                continue
            c.telegram_chat_id = str(chat_id)
            c.save(update_fields=["telegram_chat_id"])
            who = c.name
        linked += 1
        try:
            tg_call(token, "sendMessage", {"chat_id": chat_id,
                                           "text": f"PrathamSmart se jud gaye ({who}). Ab yahan message aayenge."})
        except Exception:
            pass
    if last is not None:
        try:
            tg_call(token, "getUpdates", {"offset": last + 1, "timeout": 0})   # padhe hue updates hatao
        except Exception:
            pass
    return linked, None


def tg_send(token, chat_id, text):
    try:
        d = tg_call(token, "sendMessage", {"chat_id": chat_id, "text": (text or "")[:4000]}, timeout=20)
    except Exception as err:
        return False, f"telegram error: {type(err).__name__}"
    if d.get("ok"):
        return True, "telegram"
    return False, "telegram: " + str(d.get("description") or "fail")[:80]


# ---------------- SMS (Android phone, SMS Gateway app, cloud mode) ----------------
def sms_check(user, password):
    try:
        res = httpx.get(f"{SMS_API}/devices", auth=(user, password), timeout=15)
    except Exception as err:
        return f"SMS Gateway se connect nahi hua ({type(err).__name__})"
    if res.status_code in (401, 403):
        return "Username ya password galat (app ke Home tab wala Cloud username / password)"
    if res.status_code != 200:
        return f"SMS Gateway ne HTTP {res.status_code} diya"
    try:
        if not res.json():
            return "Is account mein koi phone online nahi. App mein Cloud server chalu karein."
    except Exception:
        pass
    return None


def sms_send(user, password, phone, text):
    try:
        res = httpx.post(f"{SMS_API}/messages", auth=(user, password), timeout=20,
                         json={"phoneNumbers": [phone], "textMessage": {"text": (text or "")[:700]}})
    except Exception as err:
        return False, f"sms error: {type(err).__name__}"
    if res.status_code in (200, 201, 202):
        return True, "sms"
    return False, f"sms HTTP {res.status_code}"


# ---------------- Device level (consumers ke liye) ----------------
def _device(plant_id):
    from core.models import Device
    return Device.objects.filter(plant_id=plant_id).first()


def channel_targets(plant_id, channel):
    """Return (targets, error). targets: {naam/alias (lower): "contact_id"}; Telegram par pehle sync."""
    from core.models import DeviceContact, DeviceSettings
    from core.secretbox import unseal
    dev = _device(plant_id)
    if dev is None:
        return {}, "device nahi mila"
    cfg = DeviceSettings.objects.filter(device=dev).first()
    if channel == "telegram":
        if not (cfg and unseal(cfg.telegram_bot_token_enc)):
            return {}, "telegram set nahi"
        tg_sync(dev)
        qs = DeviceContact.objects.filter(device=dev).exclude(telegram_chat_id="")
    else:
        if not (cfg and cfg.sms_user and unseal(cfg.sms_password_enc)):
            return {}, "sms set nahi"
        qs = DeviceContact.objects.filter(device=dev).exclude(phone="")
    out = {}
    for c in qs:
        for key in [c.name] + (c.aliases or "").split(","):
            key = re.sub(r"\s+", " ", key).strip().lower()
            if key:
                out[key] = str(c.id)
    return out, None


def channel_send(plant_id, channel, contact_id, text):
    """contact_id: DeviceContact id ya 'me' (Telegram par maalik)."""
    from core.models import DeviceContact, DeviceSettings
    from core.secretbox import unseal
    dev = _device(plant_id)
    cfg = DeviceSettings.objects.filter(device=dev).first() if dev else None
    if cfg is None:
        return False, f"{channel} set nahi"
    if channel == "telegram":
        token = unseal(cfg.telegram_bot_token_enc)
        if not token:
            return False, "telegram set nahi"
        if contact_id == "me":
            if not cfg.telegram_owner_chat_id:
                tg_sync(dev)
                cfg.refresh_from_db()
            chat = cfg.telegram_owner_chat_id
        else:
            c = DeviceContact.objects.filter(device=dev, id=int(contact_id)).first()
            chat = c.telegram_chat_id if c else ""
        if not chat:
            return False, "telegram jude nahi (Start link)"
        return tg_send(token, chat, text)
    password = unseal(cfg.sms_password_enc)
    if not (cfg.sms_user and password):
        return False, "sms set nahi"
    c = DeviceContact.objects.filter(device=dev, id=int(contact_id)).first()
    if not (c and c.phone):
        return False, "number nahi"
    return sms_send(cfg.sms_user, password, c.phone, text)


def telegram_owner_ready(plant_id):
    from core.models import DeviceSettings
    from core.secretbox import unseal
    cfg = DeviceSettings.objects.filter(device__plant_id=plant_id).first()
    return bool(cfg and unseal(cfg.telegram_bot_token_enc))

# Device settings ke secrets (API key, Gmail App Password, ...) DB mein encrypt karke.
# Chaabi: .env SETTINGS_ENC_KEY (Fernet key) ya, na ho to, Django SECRET_KEY se bani.
# SECRET_KEY / SETTINGS_ENC_KEY badli to purane secrets nahi khulenge: users ko dobara daalne honge.
import base64
import hashlib
import os

from django.conf import settings

_F = None


def _fernet():
    global _F
    if _F is None:
        from cryptography.fernet import Fernet
        key = getattr(settings, "SETTINGS_ENC_KEY", "") or os.getenv("SETTINGS_ENC_KEY", "")
        if not key:
            raw = hashlib.sha256(("pratham-device-settings:" + settings.SECRET_KEY).encode()).digest()
            key = base64.urlsafe_b64encode(raw).decode()
        _F = Fernet(key.encode() if isinstance(key, str) else key)
    return _F


def seal(value):
    value = (value or "").strip()
    return _fernet().encrypt(value.encode()).decode() if value else ""


def unseal(token):
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception:
        return ""


def mask(value):
    # Frontend ko sirf itna: "set hai" + aakhri 4
    if not value:
        return ""
    return "****" + value[-4:] if len(value) >= 10 else "****"

"""PayPal.me identifier validation and normalization used by setup and UI.

Supports the official paypal.me/username and paypal.com/paypalme/username
formats as well as a bare username. Does not send payments or verify them.
"""
import re
from urllib.parse import urlsplit

USER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def paypal_username(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("https://"):
        u = urlsplit(raw)
        host = (u.hostname or "").lower()
        if u.username or u.password or u.port or u.query or u.fragment:
            return None
        parts = [p for p in u.path.split("/") if p]
        if host in ("paypal.me", "www.paypal.me"):
            if len(parts) != 1:
                return None
            raw = parts[0]
        elif host in ("paypal.com", "www.paypal.com"):
            if len(parts) != 2 or parts[0].lower() != "paypalme":
                return None
            raw = parts[1]
        else:
            return None
    elif "://" in raw or "/" in raw:
        return None
    username = raw.lstrip("@")
    if not USER_PATTERN.fullmatch(username):
        return None
    return username


def paypal_base(value):
    username = paypal_username(value)
    return "https://paypal.me/" + username if username else None

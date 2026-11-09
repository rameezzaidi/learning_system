"""RFC 6238 time-based one-time passwords with the standard library (works with Google/Microsoft Authenticator, Authy, etc.)."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret, counter, digits=6):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


def totp(secret, at=None, step=30):
    return _hotp(secret, int((time.time() if at is None else at) // step))


def verify(secret, code, at=None, window=1, step=30):
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != 6:
        return False
    now = int((time.time() if at is None else at) // step)
    return any(hmac.compare_digest(_hotp(secret, now + d), code) for d in range(-window, window + 1))


def uri(secret, account, issuer):
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"


def new_backup_codes(n=8):
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(n)]


def hash_code(code):
    return hashlib.sha256("".join(ch for ch in str(code).lower() if ch.isalnum()).encode()).hexdigest()

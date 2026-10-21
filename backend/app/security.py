"""Cryptographic utilities using Python standard library (zero C-extension issues)."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Optional

from .config import COOKIE_MAX_AGE, SECRET_KEY

PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a random 16-byte salt."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored PBKDF2 hash."""
    try:
        algorithm, iterations_str, salt, hash_hex = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def create_signed_token(payload: Dict[str, Any], max_age: int = COOKIE_MAX_AGE) -> str:
    """Create an HMAC-SHA256 signed token containing JSON payload and expiry."""
    data = dict(payload)
    data["exp"] = int(time.time()) + max_age
    raw_json = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"),
        b64_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{b64_payload}.{signature}"


def verify_signed_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify an HMAC-SHA256 signed token and return payload if valid and not expired."""
    if not token or "." not in token:
        return None
    try:
        b64_payload, signature = token.rsplit(".", 1)
        expected_sig = hmac.new(
            SECRET_KEY.encode("utf-8"),
            b64_payload.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        padding = "=" * (-len(b64_payload) % 4)
        raw_json = base64.urlsafe_b64decode(b64_payload + padding).decode("utf-8")
        data = json.loads(raw_json)
        if data.get("exp", 0) < int(time.time()):
            return None
        return data
    except Exception:
        return None


def generate_guest_token() -> str:
    """Generate a cryptographically random guest session identifier."""
    return secrets.token_urlsafe(24)

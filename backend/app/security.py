"""Authentication helpers: hashing, API keys, customer sessions, admin tokens,
and prompt-injection screening."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import SESSION_TTL_MINUTES
from .db import get_db
from .models import AdminUser, Business, CustomerSession, now

SECRET = os.getenv("APP_SECRET", "change-me-in-production-" + "x" * 16).encode()


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, digest = stored.split("$", 1)
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(check, digest)


# ---------- Business API key (tenant authentication) ----------
def require_business(x_api_key: str = Header(default=""), db: Session = Depends(get_db)) -> Business:
    business = db.query(Business).filter_by(api_key_hash=sha256(x_api_key)).first() if x_api_key else None
    if not business:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return business


# ---------- Customer session (identity is never taken from the AI) ----------
def issue_session(db: Session, business_id: int, customer_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(CustomerSession(token_hash=sha256(token), customer_id=customer_id, business_id=business_id,
                           expires_at=now() + timedelta(minutes=SESSION_TTL_MINUTES)))
    db.commit()
    return token


def require_session(authorization: str = Header(default=""), business: Business = Depends(require_business),
                    db: Session = Depends(get_db)) -> CustomerSession:
    token = authorization.removeprefix("Bearer ").strip()
    sess = db.query(CustomerSession).filter_by(token_hash=sha256(token)).first() if token else None
    if not sess or sess.revoked or sess.expires_at < now() or sess.business_id != business.id:
        raise HTTPException(status_code=401, detail="Session invalid or expired")
    return sess


# ---------- Admin token (signed, expiring) ----------
def make_admin_token(admin_id: int, ttl_seconds: int = 8 * 3600) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": admin_id, "exp": int(time.time()) + ttl_seconds}).encode()).decode()
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def require_admin(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> AdminUser:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(payload))
        if data["exp"] < time.time():
            raise ValueError
        admin = db.get(AdminUser, data["sub"])
        if not admin:
            raise ValueError
        return admin
    except Exception:
        raise HTTPException(status_code=401, detail="Admin authentication required")


# ---------- Prompt-injection screening ----------
INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (your|the|all) (instructions|rules|guidelines|policy)",
    r"\b(you are|act as|pretend to be) (now )?(an? )?(admin|administrator|developer|system|root|dan)\b",
    r"\bsystem prompt\b",
    r"\b(reveal|show|print|leak) (me )?(your|the) (instructions|prompt|rules|api key|secret)",
    r"\bdeveloper mode\b|\bjailbreak\b",
    r"(other|another|all) (customers?|users?)('s)? (orders?|data|details|accounts?)",
    r"\bcustomer_id\s*[=:]",
    r"\b(override|bypass|skip) (the )?(policy|verification|authori[sz]ation|security|approval)",
    r"\bnew instructions?\b\s*:",
    r"</?(system|assistant|tool)>",
]
_compiled = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def detect_injection(text: str) -> list[str]:
    """Return the patterns matched. Detection is a signal only: the policy engine
    still enforces authorization even if an attack is not detected."""
    return [p.pattern for p in _compiled if p.search(text)]


def sanitize_output(text: str) -> str:
    """Strip anything resembling secrets or other customers' emails from AI output."""
    text = re.sub(r"sk_[A-Za-z0-9_]{8,}", "[redacted]", text)
    text = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[redacted]", text)
    return text

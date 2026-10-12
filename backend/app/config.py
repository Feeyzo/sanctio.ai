"""Application configuration, read from environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Database (SQLite by default; any SQLAlchemy URL works, e.g. PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'agent.db'}")

# LLM provider: "gemini" uses Google Gemini; "mock" uses the built-in rule-based
# engine (no internet / no key needed — used for tests and offline demos).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini" if GEMINI_API_KEY else "mock")

# Security / policy thresholds
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "60"))
REFUND_AUTO_LIMIT = float(os.getenv("REFUND_AUTO_LIMIT", "50000"))  # NGN; above this needs a human
MAX_ACTIONS_PER_SESSION = int(os.getenv("MAX_ACTIONS_PER_SESSION", "5"))
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "1000"))

# Handoff thresholds
NEGATIVE_SENTIMENT_THRESHOLD = float(os.getenv("NEGATIVE_SENTIMENT_THRESHOLD", "-0.6"))
LOW_CONFIDENCE_THRESHOLD = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.55"))
MAX_FAILED_ATTEMPTS = int(os.getenv("MAX_FAILED_ATTEMPTS", "2"))

# Admin login (change in production)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@shopdemo.ng")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@123")
DEMO_API_KEY = os.getenv("DEMO_API_KEY", "sk_demo_shopwise_2026")

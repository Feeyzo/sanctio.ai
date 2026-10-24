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
MAX_ACTIONS_PER_SESSION = int(os.getenv("MAX_ACTIONS_PER_SESSION", "5"))
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "1000"))
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "3"))  # read-only lookups the agent may chain in one turn

# Calls to the business's own backend (webhook actions)
WEBHOOK_TIMEOUT_SECONDS = float(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "10"))
# Local development needs http://localhost URLs. Set to 0 in production so action
# URLs must be public https endpoints (blocks requests into the internal network).
ALLOW_PRIVATE_WEBHOOK_URLS = os.getenv("ALLOW_PRIVATE_WEBHOOK_URLS", "1") == "1"

# Handoff thresholds
NEGATIVE_SENTIMENT_THRESHOLD = float(os.getenv("NEGATIVE_SENTIMENT_THRESHOLD", "-0.6"))
LOW_CONFIDENCE_THRESHOLD = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.55"))
MAX_FAILED_ATTEMPTS = int(os.getenv("MAX_FAILED_ATTEMPTS", "2"))

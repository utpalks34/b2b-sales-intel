"""Centralized settings loaded from environment variables.

Reads lazily/warns instead of hard-failing at import time. The original
version did `os.environ["DATABASE_URL"]` etc. — a bare KeyError there
means ANY module that imports config (even ones that never touch
Postgres) fails to import if a single unrelated var is missing. This
version warns and leaves the value None; the module that actually
needs it (db.py, tavily_client.py, ...) is responsible for checking
before it makes the call that needs it.
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _get(name: str, default: str | None = None, required_for: str = "") -> str | None:
    value = os.environ.get(name, default)
    if not value:
        msg = f"{name} not set in environment"
        if required_for:
            msg += f" — {required_for} will fail when it's actually called"
        logger.warning(msg)
    return value


class Settings:
    TAVILY_API_KEY = _get("TAVILY_API_KEY", required_for="Tier 1 Tavily research")
    GROQ_API_KEY = _get("GROQ_API_KEY", required_for="extract_data()")
    
    DATABASE_URL = _get("DATABASE_URL", required_for="all Postgres reads/writes")
    CRITIC_SCORE_THRESHOLD = float(os.environ.get("CRITIC_SCORE_THRESHOLD", "0.7"))
    MAX_REVISIONS = int(os.environ.get("MAX_REVISIONS", "3"))


settings = Settings()
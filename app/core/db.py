"""Postgres connection setup via psycopg3 -- no ORM, no SQLAlchemy.

get_connection() raises only when actually called without DATABASE_URL
configured, matching config.py's warn-at-import/fail-at-call pattern --
importing this module never fails just because the env var is unset.
Run this file directly (`python -m app.core.db`) to sanity-check the
connection to orchestrator_db before building write logic on top of it.
"""
import logging

import psycopg

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_connection() -> psycopg.Connection:
    """Open a new psycopg3 connection to DATABASE_URL.

    Raises RuntimeError if DATABASE_URL isn't configured. The caller
    owns the returned connection's lifecycle (commit/rollback/close).
    """
    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured — cannot connect to Postgres")
    return psycopg.connect(settings.DATABASE_URL)


def check_connection() -> bool:
    if not settings.DATABASE_URL:
        logger.error("DATABASE_URL not set — cannot connect.")
        return False
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        logger.info("Postgres connection OK.")
        return True
    except Exception as exc:
        logger.error("Postgres connection failed: %s", exc)
        return False
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ok = check_connection()
    print("Connection OK" if ok else "Connection FAILED — check DATABASE_URL in .env")

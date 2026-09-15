"""
tests/test_db_crud.py

Integration tests for app.db.crud against the real orchestrator_db
Postgres instance (see app/db/schema.sql) -- not unit tests with a
mocked connection, they need a real database. Skipped entirely if
DATABASE_URL isn't set, matching the pattern in app/core/db.py.

Do NOT run these against a database you care about without reading
them first: the fixture below DELETEs any existing rows for the two
test domains (companies/sources/decision_makers/signals) before and
after every test, so repeated runs stay idempotent.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.db import get_connection
from app.db import crud

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL, reason="DATABASE_URL not set — skipping DB integration tests"
)

IDEMPOTENCY_DOMAIN = "test-crud-idempotency.example"
ROLLBACK_DOMAIN = "test-crud-rollback.example"

SOURCES = [
    {
        "url": "https://test-crud-idempotency.example/about",
        "title": "About",
        "content": "Some content about the company.",
        "source_type": "company_site",
        "scraped_via": "tavily",
        "fetched_at": "2026-01-01T00:00:00+00:00",
    },
]

EXTRACTED = {
    "company_name": "Idempotency Test Co",
    "decision_makers": [{"name": "Jane Doe", "title": "VP Engineering"}],
    "pain_points": [],
    "recent_signals": ["Raised a $10M Series A", "Launched a new product"],
    "confidence": 0.8,
}


def _cleanup(domain: str) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM companies WHERE domain = %s", (domain,))
            row = cur.fetchone()
            if row is not None:
                company_id = row[0]
                cur.execute("DELETE FROM signals WHERE company_id = %s", (company_id,))
                cur.execute("DELETE FROM decision_makers WHERE company_id = %s", (company_id,))
                cur.execute("DELETE FROM sources WHERE company_id = %s", (company_id,))
                cur.execute("DELETE FROM companies WHERE id = %s", (company_id,))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _clean_test_domains():
    _cleanup(IDEMPOTENCY_DOMAIN)
    _cleanup(ROLLBACK_DOMAIN)
    yield
    _cleanup(IDEMPOTENCY_DOMAIN)
    _cleanup(ROLLBACK_DOMAIN)


def _row_count(company_id: str, table: str) -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # table is always one of a fixed internal set below, never user input
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE company_id = %s", (company_id,))
            return cur.fetchone()[0]
    finally:
        conn.close()


def test_save_research_is_idempotent_on_rerun():
    """Calling save_research() twice with identical sources/extracted data
    for the same domain must not create duplicate sources,
    decision_makers, or signals rows (companies is upserted; the other
    three tables are guarded by WHERE NOT EXISTS)."""
    company_id_1 = crud.save_research(
        IDEMPOTENCY_DOMAIN, EXTRACTED["company_name"], SOURCES, EXTRACTED
    )
    company_id_2 = crud.save_research(
        IDEMPOTENCY_DOMAIN, EXTRACTED["company_name"], SOURCES, EXTRACTED
    )

    assert company_id_1 == company_id_2

    assert _row_count(company_id_1, "sources") == len(SOURCES)
    assert _row_count(company_id_1, "decision_makers") == len(EXTRACTED["decision_makers"])
    assert _row_count(company_id_1, "signals") == len(EXTRACTED["recent_signals"])


def test_save_research_rolls_back_fully_on_failure_partway_through():
    """If insert_signals() (the last step) raises, the earlier writes in
    that same transaction -- the company upsert, sources,
    decision_makers -- must not be left committed either. This checks
    the actual DB state, not just that the exception propagated."""
    with patch("app.db.crud.insert_signals", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            crud.save_research(
                ROLLBACK_DOMAIN, EXTRACTED["company_name"], SOURCES, EXTRACTED
            )

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM companies WHERE domain = %s", (ROLLBACK_DOMAIN,))
            assert cur.fetchone() is None, (
                "companies row was committed despite insert_signals() raising — "
                "transaction did not roll back"
            )
    finally:
        conn.close()

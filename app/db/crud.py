"""
app/db/crud.py

Postgres write logic for persisting research_domain() + extract_data()
output. This used to live (wrongly) in app/agents/writer.py -- that
file is now restored to the draft_email() stub it should have had;
do not put draft_email() or any email-drafting logic in here.

Uses psycopg3 directly against the existing orchestrator_db schema
(app/db/schema.sql) -- no ORM, no migrations. Every PK/FK in that
schema is UUID (gen_random_uuid()), so company_id here is a str
(UUID), not an int.

upsert_company/insert_sources/insert_decision_makers/insert_signals
all take an open `conn: psycopg.Connection` as their first argument
(rather than opening their own) so save_research() can run all four
under one shared transaction.

Dedup strategy:
  - companies.domain has a UNIQUE constraint -> upsert_company() uses
    INSERT ... ON CONFLICT (domain) DO UPDATE.
  - sources, decision_makers, signals have no unique constraint, so
    each insert function guards duplicates itself via a
    WHERE NOT EXISTS subquery keyed on the columns that make a row
    "the same" for that table, so re-running save_research() for a
    domain with unchanged data doesn't accumulate duplicate rows.

Both ExtractedData's `pain_points` and `recent_signals` are written into
the same `signals` table, distinguished by signal_type: pain_points are
tagged "pain_point"; recent_signals are classified via the
_classify_signal() keyword heuristic (funding/product_launch/hiring/other).
"""
from __future__ import annotations

import logging

import psycopg

from app.core.db import get_connection
from app.core.state import ExtractedData, SourceDoc

logger = logging.getLogger(__name__)


def upsert_company(conn: psycopg.Connection, domain: str, company_name: str) -> str:
    """Get-or-create a companies row keyed on the unique `domain` column.

    An existing company_name is never overwritten: it's only filled in
    if the row didn't already have one. Returns the company id (UUID str).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO companies (domain, company_name)
            VALUES (%s, %s)
            ON CONFLICT (domain) DO UPDATE
                SET company_name = COALESCE(companies.company_name, NULLIF(EXCLUDED.company_name, ''))
            RETURNING id
            """,
            (domain, company_name or None),
        )
        return str(cur.fetchone()[0])


def insert_sources(conn: psycopg.Connection, company_id: str, sources: list[SourceDoc]) -> None:
    """Insert each source not already recorded for this company at this URL."""
    with conn.cursor() as cur:
        for s in sources:
            cur.execute(
                """
                INSERT INTO sources (company_id, url, source_type, scraped_via, content)
                SELECT %(company_id)s, %(url)s, %(source_type)s, %(scraped_via)s, %(content)s
                WHERE NOT EXISTS (
                    SELECT 1 FROM sources WHERE company_id = %(company_id)s AND url = %(url)s
                )
                """,
                {
                    "company_id": company_id,
                    "url": s["url"],
                    "source_type": s["source_type"],
                    "scraped_via": s["scraped_via"],
                    "content": s["content"],
                },
            )


def insert_decision_makers(
    conn: psycopg.Connection, company_id: str, decision_makers: list[dict], confidence: float
) -> None:
    """Insert each decision-maker not already recorded for this company
    under the same (name, title).

    `confidence` is written into source_confidence for every row here --
    ExtractedData only carries one overall extraction confidence today,
    so this applies that single score uniformly across all decision
    makers from the run rather than a true per-person confidence.
    """
    with conn.cursor() as cur:
        for dm in decision_makers:
            name = dm.get("name", "")
            title = dm.get("title", "")
            cur.execute(
                """
                INSERT INTO decision_makers (company_id, name, title, source_confidence)
                SELECT %(company_id)s, %(name)s, %(title)s, %(confidence)s
                WHERE NOT EXISTS (
                    SELECT 1 FROM decision_makers
                    WHERE company_id = %(company_id)s AND name = %(name)s AND title = %(title)s
                )
                """,
                {"company_id": company_id, "name": name, "title": title, "confidence": confidence},
            )


_FUNDING_KEYWORDS = ("fund", "raise", "series", "investment")
_PRODUCT_LAUNCH_KEYWORDS = ("launch", "release", "ship")
_HIRING_KEYWORDS = ("hir", "join", "appoint")


def _classify_signal(text: str) -> str:
    lowered = text.lower()
    if any(kw in lowered for kw in _FUNDING_KEYWORDS):
        return "funding"
    if any(kw in lowered for kw in _PRODUCT_LAUNCH_KEYWORDS):
        return "product_launch"
    if any(kw in lowered for kw in _HIRING_KEYWORDS):
        return "hiring"
    return "other"


def insert_signals(
    conn: psycopg.Connection,
    company_id: str,
    pain_points: list[str],
    recent_signals: list[str],
) -> None:
    """Insert each pain point and recent signal not already recorded for
    this company under the same description. Pain points are tagged
    signal_type="pain_point"; recent signals are classified via the
    keyword heuristic in _classify_signal()."""
    entries = [("pain_point", description) for description in pain_points]
    entries += [(_classify_signal(signal), signal) for signal in recent_signals]
    with conn.cursor() as cur:
        for signal_type, description in entries:
            cur.execute(
                """
                INSERT INTO signals (company_id, signal_type, description)
                SELECT %(company_id)s, %(signal_type)s, %(description)s
                WHERE NOT EXISTS (
                    SELECT 1 FROM signals
                    WHERE company_id = %(company_id)s AND description = %(description)s
                )
                """,
                {"company_id": company_id, "signal_type": signal_type, "description": description},
            )


def save_research(
    domain: str, company_name: str, sources: list[SourceDoc], extracted: ExtractedData
) -> str:
    """
    Persist a full research_domain() + extract_data() result for `domain`
    in a single transaction: upsert_company(), then insert_sources(),
    insert_decision_makers(), insert_signals() all share one connection.

    Unlike the scraping tiers (which log-and-continue on a single source
    failure) and research_domain() overall, a write failure here must
    NOT be swallowed: if any statement in the transaction raises, the
    whole transaction is rolled back and the exception re-raised, so
    the caller (graph node) knows this run's data did not land, rather
    than silently persisting a partial write.

    Returns the company's id (str UUID).
    """
    conn = get_connection()
    try:
        with conn:
            company_id = upsert_company(conn, domain, company_name)
            insert_sources(conn, company_id, sources)
            insert_decision_makers(
                conn, company_id, extracted.get("decision_makers", []), extracted.get("confidence", 0.0)
            )
            insert_signals(
                conn, company_id, extracted.get("pain_points", []), extracted.get("recent_signals", [])
            )
        logger.info(
            "save_research(%s): wrote %d sources, %d decision_makers, %d signals",
            domain, len(sources), len(extracted.get("decision_makers", [])),
            len(extracted.get("pain_points", [])) + len(extracted.get("recent_signals", [])),
        )
        return company_id
    except Exception:
        logger.exception("save_research(%s): write failed, rolled back", domain)
        raise
    finally:
        conn.close()

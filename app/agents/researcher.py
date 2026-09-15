"""Tier 1: Tavily -> Tier 2: Trafilatura -> Tier 3: BeautifulSoup fallback.
Rule: never raise on a single source failure -- log and continue.
"""
import logging
from datetime import datetime, timezone

from app.core.state import SourceDoc
from app.scraping.bs4_fetch import fetch_with_bs4
from app.scraping.tavily_client import tavily_search_with_gaps
from app.scraping.trafilatura_fetch import fetch_with_trafilatura

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def research_domain(domain: str) -> list[SourceDoc]:
    """Gather recent news, SEC filings, blog posts, and reviews for a domain.

    Three tiers, in order:
      1. Tavily search (4 targeted queries) -- fast, usually sufficient.
      2. Trafilatura direct fetch -- retries URLs Tavily *found* but
         couldn't get raw_content for (the "gap" case).
      3. BeautifulSoup w/ rotating headers -- last resort for whatever
         Trafilatura still couldn't parse (JS-heavy pages, bot walls).

    Note on scope: this only recovers URLs Tavily actually surfaced.
    A query that fails outright at the Tavily tier (rate limited, etc.)
    never produces a candidate URL, so there's nothing for Tier 2/3 to
    retry in that case -- it just means fewer results for this run.

    Never raises: every tier already swallows its own failures.
    """
    docs: list[SourceDoc] = []
    tavily_docs, gaps = tavily_search_with_gaps(domain)

    for r in tavily_docs:
        docs.append(SourceDoc(
            url=r["url"],
            title=r.get("title", ""),
            content=r["content"],
            source_type=r["source_type"],
            scraped_via="tavily",
            fetched_at=_now_iso(),
        ))

    # Tier 2: retry gap URLs directly via trafilatura.
    still_missing: list[dict] = []
    for gap in gaps:
        content = fetch_with_trafilatura(gap["url"])
        if content:
            docs.append(SourceDoc(
                url=gap["url"],
                title=gap.get("title", ""),
                content=content,
                source_type=gap["source_type"],
                scraped_via="trafilatura",
                fetched_at=_now_iso(),
            ))
        else:
            still_missing.append(gap)

    if still_missing:
        logger.info(
            "research_domain(%s): %d URLs falling through to Tier 3 (bs4) after trafilatura",
            domain, len(still_missing),
        )

    # Tier 3: last resort for whatever Tier 2 still couldn't get.
    for gap in still_missing:
        content = fetch_with_bs4(gap["url"])
        if content:
            docs.append(SourceDoc(
                url=gap["url"],
                title=gap.get("title", ""),
                content=content,
                source_type=gap["source_type"],
                scraped_via="beautifulsoup",
                fetched_at=_now_iso(),
            ))
        else:
            logger.warning(
                "research_domain(%s): could not recover content for %s at any tier",
                domain, gap["url"],
            )

    logger.info("research_domain(%s): %d source docs total (Tier 1+2+3)", domain, len(docs))
    return docs
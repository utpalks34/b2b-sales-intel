"""
app/scraping/trafilatura_fetch.py

Tier 2 fallback fetcher.

Used by researcher.py to retry:
  - URLs Tavily returned with raw_content: null (URL was found, content wasn't)
  - Queries that failed outright at the Tavily tier (rate limited, etc.),
    where researcher.py has a URL candidate but no content at all

Design mirrors tavily_client.py's failure contract: never raises. Any
failure (network error, bad status, non-HTML response, empty extraction)
is logged as a warning and yields None, so researcher.py can hand the URL
on to Tier 3 (bs4_fetch) without special-casing exception types.
"""

from __future__ import annotations

import logging

import requests
import trafilatura

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10  # seconds
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def fetch_with_trafilatura(url: str) -> str | None:
    """
    Fetch `url` directly and extract its main text content with trafilatura.

    Returns the extracted plain-text content, or None if the fetch or
    extraction failed for any reason: network error, non-2xx status,
    non-HTML content type, or trafilatura finding nothing extractable.

    Intentionally does its own requests.get() rather than relying on
    trafilatura.fetch_url()'s built-in fetcher, so we control timeout and
    headers directly -- same reason bs4_fetch.py (Tier 3) will need its
    own header handling for pages this tier can't parse.
    """
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("trafilatura tier: fetch failed for %s (%s)", url, exc)
        return None

    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower():
        logger.warning(
            "trafilatura tier: skipping non-HTML content for %s (Content-Type: %s)",
            url,
            content_type or "unknown",
        )
        return None

    try:
        extracted = trafilatura.extract(
            response.text,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
    except Exception as exc:  # trafilatura can raise on malformed/unexpected input
        logger.warning("trafilatura tier: extraction raised for %s (%s)", url, exc)
        return None

    if not extracted or not extracted.strip():
        logger.warning("trafilatura tier: no extractable content for %s", url)
        return None

    return extracted

"""
app/scraping/bs4_fetch.py

Tier 3 (last resort) fallback fetcher.

Runs after trafilatura_fetch.py has already failed on a URL -- typically
JS-heavy pages static extraction can't parse, or sites with aggressive
bot detection that reject a plain default fetch. This tier rotates
through a small pool of realistic browser headers and retries a couple
of times before giving up.

Never raises: any failure is logged as a warning and yields None. If
this tier also fails, research_domain() logs the URL as unrecoverable
and moves on -- there's no Tier 4.
"""
from __future__ import annotations

import logging
import random
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10  # seconds
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.5

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# Tags whose text is almost never part of the main article/body content.
_STRIP_TAGS = ["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]

# Rough priority order for where the "real" content usually lives.
_CONTENT_SELECTORS = ["article", "main", "[role=main]"]


def _headers() -> dict:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _extract_text(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    for tag_name in _STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    container = None
    for selector in _CONTENT_SELECTORS:
        container = soup.select_one(selector)
        if container:
            break
    if container is None:
        container = soup.body or soup

    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) > 40]  # drop nav/UI crumbs, not real content

    if not paragraphs:
        return None

    return "\n\n".join(paragraphs)


def fetch_with_bs4(url: str) -> str | None:
    """
    Last-resort fetch: rotate headers across a few attempts, then parse
    with BeautifulSoup using a simple "paragraphs inside the main content
    container" heuristic. Returns None if every attempt fails, the
    response isn't HTML, or no substantial paragraph text is found (e.g.
    a JS-rendered shell with no server-side content -- this tier can't
    execute JS, so that case is a real dead end, not a bug).
    """
    response = None
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
            if response.status_code in (403, 429) and attempt < MAX_ATTEMPTS:
                logger.warning(
                    "bs4 tier: got %d for %s on attempt %d, rotating headers and retrying",
                    response.status_code, url, attempt,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)
            continue
    else:
        logger.warning("bs4 tier: all %d attempts failed for %s (%s)", MAX_ATTEMPTS, url, last_error)
        return None

    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower():
        logger.warning(
            "bs4 tier: skipping non-HTML content for %s (Content-Type: %s)",
            url, content_type or "unknown",
        )
        return None

    try:
        text = _extract_text(response.text)
    except Exception as exc:
        logger.warning("bs4 tier: parsing raised for %s (%s)", url, exc)
        return None

    if not text:
        logger.warning("bs4 tier: no substantial paragraph content found for %s (likely JS-rendered)", url)
        return None

    return text
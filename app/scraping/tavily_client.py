"""Tier 1 research source: Tavily search + extract.

Returns raw dicts (url, title, content, source_type) rather than
SourceDoc directly — app/agents/researcher.py owns assembling the final
SourceDoc (it adds scraped_via and fetched_at, and is where Tier 2/3
results get merged in too).

Never raises: a failed query logs a warning and contributes nothing.

tavily_search() is unchanged from Phase 1: same signature, same
behavior (URLs with no usable content are silently dropped). Phase 2
adds tavily_search_with_gaps(), which additionally surfaces those
dropped URLs so researcher.py can retry them through Tier 2/3 instead
of losing them -- this is the fix for the known gap flagged at the end
of Phase 1.
"""
import logging

from tavily import TavilyClient

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: TavilyClient | None = None


def _get_client() -> TavilyClient | None:
    global _client
    if _client is None and settings.TAVILY_API_KEY:
        _client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    return _client


def _safe_search(query: str, **kwargs) -> list[dict]:
    client = _get_client()
    if client is None:
        logger.warning("Tavily client not configured (missing TAVILY_API_KEY); skipping query: %s", query)
        return []
    try:
        resp = client.search(query=query, **kwargs)
        return resp.get("results", [])
    except Exception as exc:
        logger.warning("Tavily search failed for query=%r: %s", query, exc)
        return []


# (query template, source_type, tavily search kwargs)
_QUERY_PLAN: list[tuple[str, str, dict]] = [
    ("{domain} company news", "news",
     {"topic": "news", "max_results": 5, "include_raw_content": True}),
    ("{domain} SEC filing 10-K 10-Q 8-K", "sec_filing",
     {"include_domains": ["sec.gov"], "max_results": 5, "include_raw_content": True}),
    ("site:{domain} blog OR announcement OR press release", "blog",
     {"max_results": 5, "include_raw_content": True}),
    ("{domain} about company overview", "company_site",
     {"include_domains": ["{domain}"], "max_results": 3, "include_raw_content": True}),
]


def _run_query_plan(domain: str) -> tuple[list[dict], list[dict]]:
    """
    Shared implementation for tavily_search() and tavily_search_with_gaps().

    Returns (docs, gaps):
      - docs: usable results (url, title, content, source_type)
      - gaps: URLs the search surfaced (query succeeded) but with no
        usable raw_content/content (url, title, source_type -- no
        content key, since there wasn't any)
    """
    docs: list[dict] = []
    gaps: list[dict] = []
    seen: set[str] = set()

    for query_tmpl, source_type, kwargs in _QUERY_PLAN:
        query = query_tmpl.format(domain=domain)
        call_kwargs = dict(kwargs)
        if "include_domains" in call_kwargs:
            call_kwargs["include_domains"] = [d.format(domain=domain) for d in call_kwargs["include_domains"]]

        for result in _safe_search(query, **call_kwargs):
            url = result.get("url")
            if not url or url in seen:
                continue
            seen.add(url)

            content = result.get("raw_content") or result.get("content")
            title = result.get("title", "")
            if not content:
                gaps.append({"url": url, "title": title, "source_type": source_type})
                continue

            docs.append({
                "url": url,
                "title": title,
                "content": content,
                "source_type": source_type,
            })

    logger.info("Tavily: %d raw docs, %d gap URLs for %s", len(docs), len(gaps), domain)
    return docs, gaps


def tavily_search(domain: str) -> list[dict]:
    """
    Run the Tier 1 query plan for `domain`. Returns raw result dicts
    tagged with source_type, deduplicated by URL across queries.

    Unchanged from Phase 1: URLs with no usable content are dropped
    silently. Use tavily_search_with_gaps() if you need those too.
    """
    docs, _gaps = _run_query_plan(domain)
    return docs


def tavily_search_with_gaps(domain: str) -> tuple[list[dict], list[dict]]:
    """
    Same underlying search as tavily_search(), but also returns the
    "gap" entries: URLs Tavily's search found (the query itself
    succeeded) but for which raw_content/content came back empty or
    null. Each gap dict has url/title/source_type so a Tier 2/3 fetcher
    can retry the URL directly and the result can still be tagged
    correctly once recovered.
    """
    return _run_query_plan(domain)
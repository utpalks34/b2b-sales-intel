"""
tests/test_researcher.py

Unit tests for app.agents.researcher.research_domain().

Rewritten for Phase 2: research_domain() now calls
tavily_search_with_gaps() (returns a tuple: (docs, gaps)) instead of the
old tavily_search() (returns a plain list), and falls gaps through
fetch_with_trafilatura() then fetch_with_bs4(). All three tier functions
are patched at their app.agents.researcher import site so no real
network/API calls happen.

Note: tavily_search() itself is untouched (see tavily_client.py) and
still works exactly as it did in Phase 1 -- it's just no longer what
research_domain() calls directly, so these tests no longer target it.
"""
from unittest.mock import patch

from app.agents.researcher import research_domain


def test_research_domain_happy_path_dedup_and_source_type():
    """Two distinct Tavily docs, no gaps -> both come through untouched,
    tagged scraped_via='tavily', and Tier 2/3 are never invoked."""
    tavily_docs = [
        {"url": "https://example.com/a", "title": "A", "content": "content a", "source_type": "news"},
        {"url": "https://example.com/b", "title": "B", "content": "content b", "source_type": "sec_filing"},
    ]
    with patch("app.agents.researcher.tavily_search_with_gaps", return_value=(tavily_docs, [])), \
         patch("app.agents.researcher.fetch_with_trafilatura") as mock_trafilatura, \
         patch("app.agents.researcher.fetch_with_bs4") as mock_bs4:

        result = research_domain("example.com")

    assert len(result) == 2
    by_url = {d["url"]: d for d in result}
    assert by_url["https://example.com/a"]["source_type"] == "news"
    assert by_url["https://example.com/a"]["scraped_via"] == "tavily"
    assert by_url["https://example.com/b"]["source_type"] == "sec_filing"
    assert by_url["https://example.com/b"]["scraped_via"] == "tavily"
    mock_trafilatura.assert_not_called()
    mock_bs4.assert_not_called()


def test_research_domain_total_tavily_failure_returns_empty_list():
    """No docs, no gaps (e.g. missing TAVILY_API_KEY or every query
    failed) -> [] without raising, and no fallback tiers run."""
    with patch("app.agents.researcher.tavily_search_with_gaps", return_value=([], [])), \
         patch("app.agents.researcher.fetch_with_trafilatura") as mock_trafilatura, \
         patch("app.agents.researcher.fetch_with_bs4") as mock_bs4:

        result = research_domain("example.com")

    assert result == []
    mock_trafilatura.assert_not_called()
    mock_bs4.assert_not_called()


def test_research_domain_gap_recovered_by_trafilatura():
    """A gap URL that Tier 2 successfully fetches is appended with
    scraped_via='trafilatura' and never reaches Tier 3."""
    gaps = [{"url": "https://example.com/c", "title": "C", "source_type": "blog"}]
    with patch("app.agents.researcher.tavily_search_with_gaps", return_value=([], gaps)), \
         patch("app.agents.researcher.fetch_with_trafilatura", return_value="recovered content") as mock_trafilatura, \
         patch("app.agents.researcher.fetch_with_bs4") as mock_bs4:

        result = research_domain("example.com")

    assert len(result) == 1
    assert result[0]["url"] == "https://example.com/c"
    assert result[0]["content"] == "recovered content"
    assert result[0]["source_type"] == "blog"
    assert result[0]["scraped_via"] == "trafilatura"
    mock_trafilatura.assert_called_once_with("https://example.com/c")
    mock_bs4.assert_not_called()


def test_research_domain_gap_falls_through_to_bs4():
    """A gap URL that Tier 2 fails on gets retried at Tier 3; a Tier 3
    success is appended with scraped_via='beautifulsoup'."""
    gaps = [{"url": "https://example.com/d", "title": "D", "source_type": "company_site"}]
    with patch("app.agents.researcher.tavily_search_with_gaps", return_value=([], gaps)), \
         patch("app.agents.researcher.fetch_with_trafilatura", return_value=None) as mock_trafilatura, \
         patch("app.agents.researcher.fetch_with_bs4", return_value="bs4 recovered content") as mock_bs4:

        result = research_domain("example.com")

    assert len(result) == 1
    assert result[0]["url"] == "https://example.com/d"
    assert result[0]["content"] == "bs4 recovered content"
    assert result[0]["scraped_via"] == "beautifulsoup"
    mock_trafilatura.assert_called_once_with("https://example.com/d")
    mock_bs4.assert_called_once_with("https://example.com/d")


def test_research_domain_gap_unrecoverable_at_any_tier():
    """A gap URL that fails at both Tier 2 and Tier 3 is dropped, not
    raised -- final result has no entry for it."""
    gaps = [{"url": "https://example.com/e", "title": "E", "source_type": "news"}]
    with patch("app.agents.researcher.tavily_search_with_gaps", return_value=([], gaps)), \
         patch("app.agents.researcher.fetch_with_trafilatura", return_value=None), \
         patch("app.agents.researcher.fetch_with_bs4", return_value=None):

        result = research_domain("example.com")

    assert result == []

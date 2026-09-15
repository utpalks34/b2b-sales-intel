---
name: scraping-fallback
description: Use when writing or debugging scraping logic in app/scraping/. Encodes the tiered fallback rule.
---

Tier order: Tavily -> Trafilatura -> BeautifulSoup+httpx.
Rule: a single source failing must never raise past its tier function -- return None/empty and let researcher.py move to the next tier or log and continue.
Never scrape pages behind a login wall or disallowed by robots.txt.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

NeuroLeads AI is an autonomous B2B sales intelligence pipeline: given a company
domain, it researches the company, extracts structured facts, reasons about
the company's biggest relevant weakness, drafts a personalized outreach
email, has it critiqued, and pauses for human approval before marking the
email ready to send.

## Conventions
- Package manager: pip + requirements.txt
- Run tests: pytest (e.g. `pytest tests/test_researcher.py::test_research_domain_tier1_only` for a single test)
- Run API locally: uvicorn app.api.main:app --reload
- Run UI locally: streamlit run app/ui/dashboard.py
- Postgres access: psycopg (v3) directly -- no SQLAlchemy in this project.
- LLM calls: langchain-groq's ChatGroq -- no raw groq/anthropic SDK calls.
- HTTP fetches: httpx -- no requests library.

## Hard rules
- Never hardcode API keys or secrets. `.env` already holds GROQ_API_KEY,
  TAVILY_API_KEY, and DATABASE_URL -- load them via os.environ, not dotenv
  (python-dotenv is not installed).
- Scraping failures must never hard-fail a pipeline run -- log to error_log and continue.
- Do not add fields to PipelineState without updating app/core/state.py first.
- The Writer must use strategic_angle from the analyzer -- the Critic checks for this.

## Current drift from the conventions above

The codebase does not yet match the Conventions/Hard rules in several places.
Follow the rules above for anything you write or change; don't copy patterns
from the files below without fixing them first.
- `app/core/db.py` uses SQLAlchemy (`create_engine`/`sessionmaker`), and
  `sqlalchemy` + `psycopg2-binary` are in `requirements.txt` -- despite
  `app/db/models.py`'s own docstring and the Hard Rules above calling for
  psycopg3 with no ORM.
- `app/core/config.py` calls `load_dotenv()`, and `python-dotenv` is in
  `requirements.txt` -- despite the Hard Rules saying it isn't installed and
  env vars should be read directly via `os.environ`.
- `httpx` is imported by `app/scraping/trafilatura_fetch.py`,
  `app/scraping/bs4_fetch.py`, and `app/ui/dashboard.py`, and `langchain-groq`
  is referenced in docstrings in `app/agents/extractor.py` and
  `app/agents/writer.py`, but neither package is listed in `requirements.txt`.
  `requests` is listed but unused.
- If you touch dependencies, reconcile `requirements.txt` with the Hard Rules
  (psycopg3 + langchain-groq + httpx; drop sqlalchemy/psycopg2-binary/python-dotenv/requests)
  rather than treating the current file as ground truth.

## Architecture

Everything hangs off one frozen state shape: `PipelineState` (a `TypedDict`
in `app/core/state.py`) is passed through every LangGraph node as the single
source of truth. Never add a field without updating it there first (see the
`langgraph-node` skill).

Pipeline (`app/agents/graph.py`; currently unwired -- `compiled = None`,
node registration and edges are still a TODO):

    researcher -> extractor -> analyzer -> writer -> critic -> human_review -> finalize

- `researcher.py` -- Tier 1 (Tavily) -> Tier 2 (Trafilatura) -> Tier 3
  (BeautifulSoup) fallback chain that assembles `SourceDoc`s for a domain.
  Only Tier 1 (`app/scraping/tavily_client.py`) is implemented; Tiers 2/3
  (`app/scraping/trafilatura_fetch.py`, `app/scraping/bs4_fetch.py`) are
  stubs. A source failing at any tier must log and fall through rather than
  raise (see the `scraping-fallback` skill).
- `extractor.py` -- LLM structured extraction of `ExtractedData` (decision
  makers, pain points, signals) from raw sources. Stub (`NotImplementedError`).
- `analyzer.py` -- reasons over `ExtractedData` to produce `strategic_angle`,
  the single biggest relevant weakness to target. Stub.
- `writer.py` -- drafts the outreach email from `ExtractedData` +
  `strategic_angle` (and prior `feedback` on a revision pass). Must use
  `strategic_angle`. Stub.
- `critic.py` -- scores a draft 0-1 and returns feedback, specifically
  checking the draft used `strategic_angle` rather than a generic pitch.
  Intended revision loop: routes back to `writer` below
  `CRITIC_SCORE_THRESHOLD` (`app/core/config.py`, default 0.7) up to
  `MAX_REVISIONS` times (default 3), then on to human review. Stub.
- `human_review` / `finalize` -- the compiled graph is meant to use a
  Postgres checkpointer with `interrupt_before=["finalize"]` so a run pauses
  for human approval, resumed via the API using `thread_id=run_id`. Not yet
  wired.

API (`app/api/`): `main.py` mounts `routes.py`'s `/research` router (trigger
a run, poll status, fetch drafts, submit a human decision). All four
endpoints are currently stubs; request/response models live in `schemas.py`
per the `fastapi-endpoint` skill (long-running graph work must go through
`BackgroundTasks`, not block the request).

UI (`app/ui/dashboard.py`): Streamlit human-review screen, meant to poll the
drafts endpoint and POST decisions via httpx. Stub.

DB (`app/db/`): `schema.sql` defines `companies`, `sources`,
`decision_makers`, `signals`, `email_drafts` (UUID PKs, FK'd to
`companies`); `models.py` has matching plain dataclasses with explicitly no
ORM layer (see the drift note above re: `db.py` not yet following this).
`docker-compose.yml` is currently an empty file, not a working local
Postgres setup.

Tests (`tests/`): only `test_researcher.py` has real assertions (mocks
`tavily_search`, checks `SourceDoc` shape and Tier-1-only behavior). The
rest are `test_placeholder` stubs to fill in as their corresponding modules
get implemented.

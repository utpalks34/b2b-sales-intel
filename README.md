# NeuroLeads AI -- Sales Intelligence Orchestrator

Autonomous B2B sales intelligence pipeline: given a company domain, it
researches the company, extracts structured facts, reasons about the
company's biggest relevant weakness, drafts a personalized outreach email,
has it critiqued, and pauses for human approval before marking the email
ready to send.

Built as a [LangGraph](https://github.com/langchain-ai/langgraph) state
machine with a Postgres checkpointer (human-in-the-loop pause/resume),
served over FastAPI, with a Streamlit dashboard for the human-review step.

See `CLAUDE.md` for dev conventions, hard rules, and a note on where the
codebase currently drifts from them.

## Pipeline

```
researcher -> extractor -> persist -> analyzer -> writer -> critic -> human_review -> finalize
                                                       ^         |
                                                       +---------+
                                          (loops back to writer below
                                           CRITIC_SCORE_THRESHOLD,
                                           up to MAX_REVISIONS times)
```

| Node | Module | What it does |
|---|---|---|
| `researcher` | `app/agents/researcher.py` | Tier 1 (Tavily search) -> Tier 2 (Trafilatura direct fetch) -> Tier 3 (BeautifulSoup w/ rotating headers) fallback chain that assembles `SourceDoc`s for a domain. A source failing at any tier logs and falls through rather than raising. |
| `extractor` | `app/agents/extractor.py` | LLM structured extraction of `ExtractedData` (decision makers, pain points, recent signals, confidence) from the raw sources, via Groq. |
| `persist` | `app/db/crud.py` (`save_research`) | Writes the domain's company/sources/decision-makers/signals to Postgres in one transaction. Unlike the other nodes, a failure here is *not* swallowed -- it propagates as a real error. |
| `analyzer` | `app/agents/analyzer.py` | Reasons over `ExtractedData` to produce `strategic_angle` -- the single biggest relevant weakness/hook to lead the email with. |
| `writer` | `app/agents/writer.py` | Drafts the outreach email from `ExtractedData` + `strategic_angle` (and, on a revision pass, the critic's prior `feedback`, which it must actually incorporate). |
| `critic` | `app/agents/critic.py` | Scores a draft 0-1 and returns feedback, specifically checking the draft used `strategic_angle` rather than a generic pitch. Routes back to `writer` below `CRITIC_SCORE_THRESHOLD` (default `0.7`) up to `MAX_REVISIONS` times (default `3`), then proceeds to human review regardless of score. |
| `human_review` | `app/agents/graph.py` | No-op node; the actual pause happens via `interrupt_before=["finalize"]` on the compiled graph, resumed by the API using `thread_id=run_id`. |
| `finalize` | `app/agents/graph.py` | Applies the human decision (`approved` / `rejected` / `edited`) to produce `final_email`. |

All state flows through one frozen shape: `PipelineState`, a `TypedDict` in
`app/core/state.py`. It's the single source of truth passed through every
LangGraph node -- never add a field without updating it there first.

## Project structure

```
app/
  agents/            LangGraph node logic (one module per pipeline stage)
    researcher.py     Tier 1/2/3 scraping fallback chain -> SourceDoc[]
    extractor.py       Groq structured extraction -> ExtractedData
    analyzer.py         Groq reasoning -> strategic_angle
    writer.py            Groq drafting -> draft_email (feedback-aware)
    critic.py             Groq scoring -> (critic_score, critic_feedback)
    graph.py               Wires the nodes into a StateGraph + Postgres
                            checkpointer; exposes get_compiled_graph()

  api/               FastAPI HTTP layer
    main.py            App + routes: POST /runs, GET /runs/{id},
                        POST /runs/{id}/decision
    runs.py             Execution wrapper: starts runs as background
                        threads, reads status from LangGraph checkpoint
                        state, submits human decisions to resume a run
    schemas.py          Pydantic request/response models
    routes.py            Legacy stub router (not mounted by main.py --
                        superseded by main.py + runs.py; kept for
                        reference, not part of the live API)

  core/              Cross-cutting infrastructure
    state.py           PipelineState / ExtractedData / SourceDoc TypedDicts
                        -- the frozen contract every node reads/writes
    config.py            Settings loaded from .env (GROQ_API_KEY,
                        TAVILY_API_KEY, DATABASE_URL, CRITIC_SCORE_THRESHOLD,
                        MAX_REVISIONS); warns rather than hard-failing on a
                        missing var at import time
    db.py                 psycopg3 connection helper (get_connection,
                        check_connection) -- no ORM

  db/                Postgres schema + data-access layer
    schema.sql         companies / sources / decision_makers / signals /
                        email_drafts / run_status tables (UUID PKs)
    crud.py              save_research() and friends -- upsert + dedup'd
                        inserts, all in one transaction
    models.py             SQLAlchemy ORM models mirroring schema.sql
                        (drift: the rest of the DB layer is ORM-free psycopg3;
                        see CLAUDE.md)

  scraping/          Source fetchers used by researcher.py
    tavily_client.py    Tier 1: Tavily search (4 targeted queries),
                        surfaces "gap" URLs with no usable content
    trafilatura_fetch.py  Tier 2: direct fetch + trafilatura extraction
                        for gap URLs
    bs4_fetch.py           Tier 3: last-resort fetch with rotating
                        headers/retries + BeautifulSoup paragraph heuristic

  ui/
    streamlit_app.py    Human-review dashboard: trigger runs, poll status,
                        approve/reject/edit drafts via the FastAPI layer

tests/
  test_researcher.py    Full coverage of the Tier 1/2/3 fallback chain
  test_db_crud.py         Idempotency + rollback coverage for save_research()
  test_api.py, test_extractor.py, test_graph.py   Placeholder stubs

docker/
  Dockerfile.api       uvicorn app.api.main:app
  Dockerfile.ui           streamlit run app/ui/streamlit_app.py
docker-compose.yml    Currently empty -- no working local Postgres setup yet

setup_checkpointer.py  One-off script: creates the LangGraph Postgres
                        checkpoint tables (PostgresSaver.setup())
requirements.txt
.env                    Local secrets (gitignored): GROQ_API_KEY,
                        TAVILY_API_KEY, DATABASE_URL
CLAUDE.md               Conventions, hard rules, and architecture notes for
                        AI-assisted development in this repo
```

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows; use `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
```

Create a `.env` in the project root:

```
GROQ_API_KEY=...
TAVILY_API_KEY=...
DATABASE_URL=postgresql://<user>:<password>@localhost:5432/orchestrator_db
```

Create the schema and checkpoint tables against a running Postgres instance:

```bash
psql "$DATABASE_URL" -f app/db/schema.sql
python setup_checkpointer.py
```

## Running

```bash
# API
uvicorn app.api.main:app --reload

# Dashboard (in a separate terminal, with the API running)
streamlit run app/ui/streamlit_app.py
```

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/runs` | Body: `{"domains": ["acme.com", ...]}`. Starts one background pipeline run per domain, returns `run_id` for each. |
| `GET` | `/runs/{run_id}` | Current status: `running` / `awaiting_review` / `completed` / `rejected` / `failed`, plus `strategic_angle`, `draft_email`, `critic_score`/`critic_feedback`, `final_email`, and `error_log` once available. |
| `POST` | `/runs/{run_id}/decision` | Body: `{"decision": "approved" \| "rejected" \| "edited", "edited_email": "..."}`. Resumes a run paused at human review. |

## Testing

```bash
pytest
pytest tests/test_researcher.py::test_research_domain_happy_path_dedup_and_source_type   # single test
```

`test_researcher.py` and `test_db_crud.py` have real coverage; `test_api.py`,
`test_extractor.py`, and `test_graph.py` are placeholder stubs.

## Known drift from CLAUDE.md's conventions

See `CLAUDE.md` for the authoritative list. Notably:
- `app/db/models.py` is a SQLAlchemy ORM layer, despite the rest of the DB
  code (`app/core/db.py`, `app/db/crud.py`) being plain psycopg3.
- The agent modules use the raw `groq` SDK rather than `langchain-groq`.
- `app/api/routes.py` is an orphaned stub -- the live API is defined in
  `app/api/main.py` + `app/api/runs.py`.
- `docker-compose.yml` is empty; there's no one-command local Postgres yet.

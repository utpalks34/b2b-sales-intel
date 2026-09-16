"""Wires researcher -> extractor -> analyzer -> writer -> critic ->
human_review -> finalize into a LangGraph StateGraph, with a Postgres
checkpointer and an interrupt before finalize for human-in-the-loop approval.
"""
import logging
from datetime import datetime, timezone

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from app.agents.analyzer import analyze_data
from app.agents.critic import critique_email
from app.agents.extractor import extract_data
from app.agents.researcher import research_domain
from app.agents.writer import draft_email
from app.core.config import settings
from app.core.db import get_connection
from app.core.state import PipelineState
from app.db.crud import save_research

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Node functions. Per the langgraph-node skill: take PipelineState, return a
# partial state update (dict), never mutate in place. Every external call is
# wrapped in try/except that logs to error_log rather than raising, even
# though each underlying function already documents "never raises" -- this
# is defense in depth against the contract being wrong or changing later,
# consistent with that skill's rule.
# ---------------------------------------------------------------------------


def researcher_node(state: PipelineState) -> dict:
    try:
        sources = research_domain(state["domain"])
        return {"raw_sources": sources, "updated_at": _now_iso()}
    except Exception as exc:
        logger.exception("researcher_node: research_domain failed unexpectedly for %s", state["domain"])
        error_log = state.get("error_log", []) + [f"researcher_node: {exc}"]
        return {"raw_sources": state.get("raw_sources", []), "error_log": error_log, "updated_at": _now_iso()}


def extractor_node(state: PipelineState) -> dict:
    try:
        extracted = extract_data(state.get("raw_sources", []))
        return {"extracted_data": extracted, "updated_at": _now_iso()}
    except Exception as exc:
        logger.exception("extractor_node: extract_data failed unexpectedly")
        error_log = state.get("error_log", []) + [f"extractor_node: {exc}"]
        return {"error_log": error_log, "updated_at": _now_iso()}


def persist_node(state: PipelineState) -> dict:
    """Persist research + extraction to Postgres via save_research().

    JUDGMENT CALL (a) -- see chat summary for full rationale/alternative.
    Placed right after extractor, before analyzer: save_research() only
    needs `domain` + `raw_sources` + `extracted_data`, none of which
    change again downstream, so persisting here fails fast (before
    analyze/write/critique spend further LLM calls on data that turned
    out not to be durably saveable) rather than persisting late.

    Deliberately NOT wrapped in try/except, unlike every other node here:
    save_research() is the one function in this pipeline that is allowed
    to raise on a real DB failure, and that's intentional on the caller's
    (this project's) part -- letting it propagate out of the graph
    invocation surfaces a genuine data-loss risk to whatever called the
    graph (the API layer) as a real error, instead of quietly downgrading
    it to a soft-logged error_log entry alongside routine scraping
    hiccups that are fine to ignore.
    """
    extracted = state.get("extracted_data") or {}
    company_name = extracted.get("company_name", "")
    save_research(state["domain"], company_name, state.get("raw_sources", []), extracted)
    return {"updated_at": _now_iso()}


def analyzer_node(state: PipelineState) -> dict:
    try:
        angle = analyze_data(state.get("extracted_data") or {})
        return {"strategic_angle": angle, "updated_at": _now_iso()}
    except Exception as exc:
        logger.exception("analyzer_node: analyze_data failed unexpectedly")
        error_log = state.get("error_log", []) + [f"analyzer_node: {exc}"]
        return {"error_log": error_log, "updated_at": _now_iso()}


def writer_node(state: PipelineState) -> dict:
    try:
        draft = draft_email(
            state.get("extracted_data") or {},
            state.get("strategic_angle") or "",
            state.get("critic_feedback"),
        )
        return {"draft_email": draft, "updated_at": _now_iso()}
    except Exception as exc:
        logger.exception("writer_node: draft_email failed unexpectedly")
        error_log = state.get("error_log", []) + [f"writer_node: {exc}"]
        return {"error_log": error_log, "updated_at": _now_iso()}


def critic_node(state: PipelineState) -> dict:
    """Runs critique_email() and bumps revision_count.

    Note on revision_count semantics: it's incremented here, once per
    critique pass, rather than only when actually looping back to the
    writer. So with the default MAX_REVISIONS=3, the pipeline allows up
    to 3 critique passes total (i.e. up to 2 writer revisions after the
    first draft) before giving up and proceeding to human_review even
    below threshold. Incrementing only on an actual loop-back (1st draft
    = revision 0, each loop-back bumps it) was the alternative, but that
    requires either a dedicated node or a router with side effects, which
    plain LangGraph conditional edges don't support -- this was the
    simpler option given the two produce nearly the same behavior.
    """
    try:
        score, feedback = critique_email(
            state.get("draft_email") or "",
            state.get("extracted_data") or {},
            state.get("strategic_angle") or "",
        )
        return {
            "critic_score": score,
            "critic_feedback": feedback,
            "revision_count": state.get("revision_count", 0) + 1,
            "updated_at": _now_iso(),
        }
    except Exception as exc:
        logger.exception("critic_node: critique_email failed unexpectedly")
        error_log = state.get("error_log", []) + [f"critic_node: {exc}"]
        return {"error_log": error_log, "updated_at": _now_iso()}


def human_review_node(state: PipelineState) -> dict:
    """No-op pass-through node.

    JUDGMENT CALL (b) -- see chat summary. This node exists only so the
    graph has a distinct "human_review" step matching the documented
    critic -> human_review -> finalize flow; the actual pause for human
    input happens via interrupt_before=["finalize"] below (the graph
    runs researcher..human_review automatically, then halts before
    finalize). Whatever resumes the run is expected to call
    graph.update_state(config, {"human_decision": ...}) (and, for an
    "edited" decision, {"edited_email": <edited text>}) before invoking
    the graph again with the same thread_id to proceed into finalize.
    """
    return {"updated_at": _now_iso()}


def finalize_node(state: PipelineState) -> dict:
    decision = state.get("human_decision")
    if decision == "approved":
        return {"final_email": state.get("draft_email"), "updated_at": _now_iso()}
    if decision == "rejected":
        return {"final_email": None, "updated_at": _now_iso()}
    if decision == "edited":
        edited_email = state.get("edited_email")
        if edited_email:
            return {"final_email": edited_email, "updated_at": _now_iso()}
        # JUDGMENT CALL: edited_email is required for an "edited" decision but
        # came back empty -- rather than silently returning nothing (leaving
        # final_email unset), log it and fall back to draft_email so finalize
        # always produces a final_email for this branch.
        error_log = state.get("error_log", []) + [
            "finalize_node: human_decision was 'edited' but edited_email was empty -- falling back to draft_email"
        ]
        return {"final_email": state.get("draft_email"), "error_log": error_log, "updated_at": _now_iso()}
    # unset/no-decision: nothing further to derive here.
    return {"updated_at": _now_iso()}


def route_after_critic(state: PipelineState) -> str:
    score = state.get("critic_score")
    revisions = state.get("revision_count", 0)
    if score is not None and score < settings.CRITIC_SCORE_THRESHOLD and revisions < settings.MAX_REVISIONS:
        return "writer"
    return "human_review"


# ---------------------------------------------------------------------------
# Graph wiring
# ---------------------------------------------------------------------------

graph = StateGraph(PipelineState)

graph.add_node("researcher", researcher_node)
graph.add_node("extractor", extractor_node)
graph.add_node("persist", persist_node)
graph.add_node("analyzer", analyzer_node)
graph.add_node("writer", writer_node)
graph.add_node("critic", critic_node)
graph.add_node("human_review", human_review_node)
graph.add_node("finalize", finalize_node)

graph.add_edge(START, "researcher")
graph.add_edge("researcher", "extractor")
graph.add_edge("extractor", "persist")
graph.add_edge("persist", "analyzer")
graph.add_edge("analyzer", "writer")
graph.add_edge("writer", "critic")
graph.add_conditional_edges("critic", route_after_critic, {"writer": "writer", "human_review": "human_review"})
graph.add_edge("human_review", "finalize")
graph.add_edge("finalize", END)


def _build_checkpointer() -> PostgresSaver:
    """Build the Postgres checkpointer the compiled graph needs so
    interrupt_before=["finalize"] can actually persist state across the
    pause/resume boundary (resumed later via the API using thread_id=run_id,
    per this project's architecture docs).

    JUDGMENT CALL (b) continued: the original scaffold's TODO referenced a
    `get_checkpointer()` helper -- repo-wide search found no such function
    anywhere (app/core/db.py only has get_connection()/check_connection()).
    Rather than add one to app/core/db.py (out of scope: only this file may
    be touched), this builds the checkpointer inline here, reusing
    get_connection() so it inherits the same "raise only when actually
    called without DATABASE_URL configured" behavior as the rest of the
    project instead of duplicating connection logic.

    Note: PostgresSaver.setup() (creates the checkpoint tables) is
    intentionally NOT called here -- this module must not execute/import
    anything with side effects at load time, and setup() is a one-time
    migration-style operation that belongs in ops/startup tooling, not in
    a function called on every graph compile.
    """
    conn = get_connection()
    conn.autocommit = True
    return PostgresSaver(conn)


_compiled = None


def get_compiled_graph():
    """Lazily build and cache the compiled graph.

    JUDGMENT CALL (b) continued: the scaffold's TODO implied a module-level
    `compiled = graph.compile(...)` assignment evaluated at import time.
    That would mean `import app.agents.graph` always opens a live Postgres
    connection (via _build_checkpointer()) and raises if DATABASE_URL isn't
    configured -- which conflicts with this project's established
    lazy-fail-at-call-time convention (see app/core/config.py's and
    app/core/db.py's docstrings, which exist specifically to avoid
    import-time failures on missing env vars). This function defers that
    connection until the graph is actually needed and caches the result,
    so merely importing this module stays side-effect-free. The
    alternative -- keeping a plain module-level `compiled` built eagerly,
    matching the scaffold literally -- is one line to switch to if you'd
    rather have that instead.
    """
    global _compiled
    if _compiled is None:
        _compiled = graph.compile(
            checkpointer=_build_checkpointer(),
            interrupt_before=["finalize"],
        )
    return _compiled

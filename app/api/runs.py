"""
app/api/runs.py

Execution wrapper around the compiled LangGraph pipeline for the API
layer. Owns: starting new runs in the background, checking a run's
status, and submitting human review decisions to resume a paused run.

Status for the normal path is derived from LangGraph's own checkpoint
state (graph.get_state()). The run_status Postgres table exists only to
catch persist_node raising inside a background thread -- otherwise
invisible to checkpoint state.
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone

from app.agents.graph import get_compiled_graph
from app.api.schemas import RunStatusResponse, TriggeredRun
from app.core.db import get_connection
from app.core.state import PipelineState

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_for(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _insert_run_status(run_id: str, domain: str) -> None:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO run_status (run_id, domain, status) VALUES (%s, %s, 'running')",
                    (run_id, domain),
                )
    finally:
        conn.close()


def _mark_failed(run_id: str, error_message: str) -> None:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE run_status SET status = 'failed', error_message = %s, updated_at = now() WHERE run_id = %s",
                    (error_message, run_id),
                )
    finally:
        conn.close()


def _get_run_status_row(run_id: str) -> dict | None:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT domain, status, error_message FROM run_status WHERE run_id = %s",
                    (run_id,),
                )
                row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"domain": row[0], "status": row[1], "error_message": row[2]}


def _initial_state(run_id: str, domain: str) -> PipelineState:
    return PipelineState(
        run_id=run_id,
        domain=domain,
        raw_sources=[],
        extracted_data=None,
        strategic_angle=None,
        draft_email=None,
        critic_score=None,
        critic_feedback=None,
        revision_count=0,
        human_decision=None,
        edited_email=None,
        final_email=None,
        error_log=[],
        updated_at=_now_iso(),
    )


def _run_graph_in_background(run_id: str, domain: str) -> None:
    try:
        get_compiled_graph().invoke(_initial_state(run_id, domain), config=_config_for(run_id))
    except Exception as exc:
        logger.exception("Background graph run failed for run_id=%s domain=%s", run_id, domain)
        _mark_failed(run_id, str(exc))


def start_runs(domains: list[str]) -> list[TriggeredRun]:
    """Kick off one independent graph run per domain in its own
    background thread, returning immediately with a run_id per domain."""
    triggered: list[TriggeredRun] = []
    for domain in domains:
        run_id = str(uuid.uuid4())
        _insert_run_status(run_id, domain)
        thread = threading.Thread(target=_run_graph_in_background, args=(run_id, domain), daemon=True)
        thread.start()
        triggered.append(TriggeredRun(domain=domain, run_id=run_id))
    return triggered


def get_run_status(run_id: str) -> RunStatusResponse | None:
    """Current status for a run. None if run_id is unknown entirely."""
    row = _get_run_status_row(run_id)
    if row is None:
        return None

    if row["status"] == "failed":
        return RunStatusResponse(
            run_id=run_id,
            domain=row["domain"],
            status="failed",
            error_log=[row["error_message"] or "Unknown failure"],
        )

    compiled = get_compiled_graph()
    snapshot = compiled.get_state(_config_for(run_id))
    values = snapshot.values or {}

    if not values:
        status = "running"
    elif snapshot.next == ("finalize",):
        status = "awaiting_review"
    elif snapshot.next == ():
        status = "rejected" if values.get("human_decision") == "rejected" else "completed"
    else:
        status = "running"

    return RunStatusResponse(
        run_id=run_id,
        domain=row["domain"],
        status=status,
        strategic_angle=values.get("strategic_angle"),
        draft_email=values.get("draft_email"),
        critic_score=values.get("critic_score"),
        critic_feedback=values.get("critic_feedback"),
        human_decision=values.get("human_decision"),
        final_email=values.get("final_email"),
        error_log=values.get("error_log", []),
    )


def submit_decision(run_id: str, decision: str, edited_email: str | None) -> RunStatusResponse | None:
    """Submit a human decision and resume the paused run past finalize."""
    row = _get_run_status_row(run_id)
    if row is None:
        return None

    compiled = get_compiled_graph()
    config = _config_for(run_id)

    update: dict = {"human_decision": decision}
    if edited_email is not None:
        update["edited_email"] = edited_email
    compiled.update_state(config, update)

    try:
        compiled.invoke(None, config=config)
    except Exception as exc:
        logger.exception("Resume-after-decision failed for run_id=%s", run_id)
        _mark_failed(run_id, str(exc))

    return get_run_status(run_id)

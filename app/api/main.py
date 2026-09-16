"""
app/api/main.py

FastAPI app wiring the pipeline's HTTP interface. Thin: request/response
validation via schemas.py, actual logic lives in runs.py.

Route handlers are sync `def`, not `async def` -- FastAPI runs sync route
functions in a threadpool automatically, matching this project's existing
constraint that the graph's checkpointer is a synchronous PostgresSaver
(see app/agents/graph.py), not async-compatible.
"""
import logging

from fastapi import FastAPI, HTTPException

from app.api.runs import get_run_status, start_runs, submit_decision
from app.api.schemas import (
    DecisionRequest,
    RunStatusResponse,
    TriggerRequest,
    TriggerResponse,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="B2B Sales Intelligence Pipeline API")


@app.post("/runs", response_model=TriggerResponse, status_code=202)
def trigger_runs(request: TriggerRequest) -> TriggerResponse:
    """Kick off one background run per domain, return immediately."""
    triggered = start_runs(request.domains)
    return TriggerResponse(runs=triggered)


@app.get("/runs/{run_id}", response_model=RunStatusResponse)
def read_run_status(run_id: str) -> RunStatusResponse:
    status = get_run_status(run_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id}")
    return status


@app.post("/runs/{run_id}/decision", response_model=RunStatusResponse)
def decide_run(run_id: str, request: DecisionRequest) -> RunStatusResponse:
    status = submit_decision(run_id, request.decision, request.edited_email)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id}")
    return status

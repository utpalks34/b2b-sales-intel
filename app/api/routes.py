"""POST /research/trigger, GET /research/{run_id}/status,
GET /research/{run_id}/drafts, POST /research/{run_id}/drafts/{id}/decision
"""
from fastapi import APIRouter, BackgroundTasks
from app.api.schemas import TriggerRequest, DecisionRequest

router = APIRouter(prefix="/research")


@router.post("/trigger")
def trigger(req: TriggerRequest, background_tasks: BackgroundTasks):
    # TODO: kick off graph run(s) in background, return run_id(s)
    raise NotImplementedError


@router.get("/{run_id}/status")
def status(run_id: str):
    raise NotImplementedError


@router.get("/{run_id}/drafts")
def drafts(run_id: str):
    raise NotImplementedError


@router.post("/{run_id}/drafts/{draft_id}/decision")
def decision(run_id: str, draft_id: str, req: DecisionRequest):
    # TODO: resume graph from checkpoint using thread_id=run_id
    raise NotImplementedError

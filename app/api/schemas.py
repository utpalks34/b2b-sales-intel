"""Pydantic request/response models for the API."""
from typing import Literal, Optional
from pydantic import BaseModel


class TriggerRequest(BaseModel):
    domains: list[str]


class DecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "edited"]
    edited_email: Optional[str] = None


class TriggeredRun(BaseModel):
    domain: str
    run_id: str


class TriggerResponse(BaseModel):
    runs: list[TriggeredRun]


class RunStatusResponse(BaseModel):
    run_id: str
    domain: str
    status: Literal["running", "awaiting_review", "completed", "rejected", "failed"]
    strategic_angle: Optional[str] = None
    draft_email: Optional[str] = None
    critic_score: Optional[float] = None
    critic_feedback: Optional[str] = None
    human_decision: Optional[Literal["approved", "rejected", "edited"]] = None
    final_email: Optional[str] = None
    error_log: list[str] = []


class ErrorResponse(BaseModel):
    detail: str

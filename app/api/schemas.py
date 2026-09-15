"""Pydantic request/response models for the API."""
from typing import Literal, Optional
from pydantic import BaseModel


class TriggerRequest(BaseModel):
    domains: list[str]


class DecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "edited"]
    edited_text: Optional[str] = None

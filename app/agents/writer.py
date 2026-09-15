"""
app/agents/writer.py

draft_email(extracted_data, strategic_angle, feedback=None) -> str

Drafts a personalized outreach email from `extracted_data` (decision
makers, pain points, recent signals) targeted at the single biggest
weakness identified by the analyzer as `strategic_angle`. When
`feedback` is provided (a revision pass triggered by the critic
routing back below CRITIC_SCORE_THRESHOLD), the draft must incorporate
it rather than starting over from scratch.

Must use `strategic_angle` -- the critic checks for this rather than
accepting a generic pitch.
"""
from __future__ import annotations

from app.core.state import ExtractedData


def draft_email(
    extracted_data: ExtractedData, strategic_angle: str, feedback: str | None = None
) -> str:
    raise NotImplementedError

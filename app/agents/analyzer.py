"""
app/agents/analyzer.py

analyze_data(extracted_data) -> str

Turns ExtractedData into a short, concrete "strategic_angle" -- the one
hook the outreach email should lead with (e.g. "they just tripled
headcount, likely straining onboarding" rather than something generic).

Uses the raw `groq` client, same pattern as extractor.py -- consistent
with this project's current choice to keep `groq` directly rather than
migrate to `langchain-groq`.

Never raises: no usable signal in the input, missing Groq config, API
failure, or an empty response all fall through to a generic-but-honest
fallback angle rather than inventing specifics or crashing the graph.
"""
from __future__ import annotations

import logging

from groq import Groq

from app.core.config import settings
from app.core.state import ExtractedData

logger = logging.getLogger(__name__)

MODEL = "openai/gpt-oss-120b"

_FALLBACK_ANGLE = (
    "No strong signals were found for this company. Lead with a general "
    "introduction referencing their core business rather than inventing "
    "a specific hook."
)

_client: Groq | None = None


def _get_client() -> Groq | None:
    global _client
    if _client is None and settings.GROQ_API_KEY:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


def _has_usable_signal(extracted_data: ExtractedData) -> bool:
    """True if there's enough real material to justify a specific angle
    rather than falling back to a generic one -- avoids asking the model
    to manufacture a "strategic angle" out of nothing."""
    has_content = bool(extracted_data.get("pain_points") or extracted_data.get("recent_signals"))
    return has_content and extracted_data.get("confidence", 0.0) > 0.0


def _build_prompt(extracted_data: ExtractedData) -> str:
    company = extracted_data.get("company_name") or "this company"
    decision_makers = extracted_data.get("decision_makers", [])
    pain_points = extracted_data.get("pain_points", [])
    signals = extracted_data.get("recent_signals", [])

    dm_lines = "\n".join(f"- {dm.get('name', '')} ({dm.get('title', '')})" for dm in decision_makers) or "None identified"
    pain_lines = "\n".join(f"- {p}" for p in pain_points) or "None identified"
    signal_lines = "\n".join(f"- {s}" for s in signals) or "None identified"

    return f"""You are a B2B sales strategist. Based ONLY on the information
below about {company}, write ONE strategic angle for a cold outreach
email -- a single concrete hook, 1-2 sentences, that a salesperson could
lead with. It must reference something specific and true from the data
below. Do not invent facts not present here. Do not write the email
itself, only the angle.

Decision makers:
{dm_lines}

Pain points:
{pain_lines}

Recent signals:
{signal_lines}

Confidence in this data: {extracted_data.get('confidence', 0.0)}

Respond with ONLY the strategic angle -- no preamble, no quotation marks,
no "Here's the angle:" prefix.
"""


def analyze_data(extracted_data: ExtractedData) -> str:
    """
    Produce a short strategic angle for the outreach email from
    ExtractedData. Never raises: falls back to a generic-but-honest
    angle on thin input, missing config, API failure, or empty response.
    """
    if not _has_usable_signal(extracted_data):
        logger.info("analyze_data: no usable signal in extracted_data, using fallback angle")
        return _FALLBACK_ANGLE

    client = _get_client()
    if client is None:
        logger.warning("analyze_data: Groq client not configured (missing GROQ_API_KEY)")
        return _FALLBACK_ANGLE

    prompt = _build_prompt(extracted_data)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
            reasoning_effort="low",
        )
        angle = response.choices[0].message.content
    except Exception as exc:
        logger.warning("analyze_data: Groq API call failed (%s)", exc)
        return _FALLBACK_ANGLE

    if not angle or not angle.strip():
        logger.warning("analyze_data: Groq returned empty content")
        return _FALLBACK_ANGLE

    return angle.strip()
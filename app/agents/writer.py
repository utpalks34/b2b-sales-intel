"""
app/agents/writer.py

draft_email(extracted_data, strategic_angle, feedback=None) -> str

Drafts a cold outreach email from ExtractedData + the strategic_angle
produced by analyzer.py. On a revision loop, `feedback` carries the
critic's notes from the previous attempt and must actually be
incorporated, not ignored.

Uses the raw `groq` client, same pattern as extractor.py and
analyzer.py.

Never raises: missing Groq config, API failure, or empty response fall
through to a safe, generic (but honest, non-hallucinated) email rather
than crashing the graph.
"""
from __future__ import annotations

import logging

from groq import Groq

from app.core.config import settings
from app.core.state import ExtractedData

logger = logging.getLogger(__name__)

MODEL = "openai/gpt-oss-120b"

_FALLBACK_EMAIL = (
    "Subject: Quick question about {company}\n\n"
    "Hi,\n\n"
    "I wanted to reach out and learn more about {company}'s current priorities. "
    "Would you be open to a brief conversation?\n\n"
    "Best,\n"
)

_client: Groq | None = None


def _get_client() -> Groq | None:
    global _client
    if _client is None and settings.GROQ_API_KEY:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


def _fallback_email(extracted_data: ExtractedData) -> str:
    company = extracted_data.get("company_name") or "your company"
    return _FALLBACK_EMAIL.format(company=company)


def _build_prompt(extracted_data: ExtractedData, strategic_angle: str, feedback: str | None) -> str:
    company = extracted_data.get("company_name") or "the company"
    decision_makers = extracted_data.get("decision_makers", [])
    dm_line = f"{decision_makers[0].get('name', '')} ({decision_makers[0].get('title', '')})" if decision_makers else "the right contact"

    feedback_block = ""
    if feedback:
        feedback_block = f"""
This is a REVISION. A previous draft was reviewed and given this feedback
-- you must address it directly in this new draft, not just rephrase the
same email:
{feedback}
"""

    return f"""You are a B2B sales rep writing a short, personalized cold
outreach email to {dm_line} at {company}.

Strategic angle to lead with:
{strategic_angle}
{feedback_block}
Rules:
- Include a "Subject:" line first, then a blank line, then the email body.
- Keep the body under 150 words. No corporate filler, no "I hope this
  email finds you well."
- Reference the strategic angle specifically -- don't be generic.
- End with a soft, low-pressure call to action (e.g. asking for 15
  minutes), not a hard sell.
- Do not invent facts about the company beyond what's given above.

Respond with ONLY the email (subject line + body), nothing else.
"""


def draft_email(extracted_data: ExtractedData, strategic_angle: str, feedback: str | None = None) -> str:
    """
    Draft a cold outreach email. Never raises: falls back to a generic
    (but honest, non-hallucinated) email on missing Groq config, API
    failure, or empty response.
    """
    client = _get_client()
    if client is None:
        logger.warning("draft_email: Groq client not configured (missing GROQ_API_KEY)")
        return _fallback_email(extracted_data)

    prompt = _build_prompt(extracted_data, strategic_angle, feedback)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=400,
            reasoning_effort="low",
        )
        email = response.choices[0].message.content
    except Exception as exc:
        logger.warning("draft_email: Groq API call failed (%s)", exc)
        return _fallback_email(extracted_data)

    if not email or not email.strip():
        logger.warning("draft_email: Groq returned empty content")
        return _fallback_email(extracted_data)

    return email.strip()

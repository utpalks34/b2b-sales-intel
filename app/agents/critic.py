"""
app/agents/critic.py

critique_email(draft_email, extracted_data, strategic_angle) -> (score, feedback)

Scores a drafted outreach email against settings.CRITIC_SCORE_THRESHOLD
and returns feedback that draft_email() can incorporate on a revision
loop. Uses the raw `groq` client, same pattern as extractor.py,
analyzer.py, and writer.py.

Never raises: on missing Groq config, API failure, or an unparseable
response, returns a fallback (score=CRITIC_SCORE_THRESHOLD, i.e. a pass)
rather than blocking the pipeline or forcing wasted revision cycles on a
transient failure that has nothing to do with the email's actual quality.
"""
from __future__ import annotations

import json
import logging
import re

from groq import Groq

from app.core.config import settings
from app.core.state import ExtractedData

logger = logging.getLogger(__name__)

MODEL = "openai/gpt-oss-120b"

_client: Groq | None = None


def _get_client() -> Groq | None:
    global _client
    if _client is None and settings.GROQ_API_KEY:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


def _fallback_result(reason: str) -> tuple[float, str]:
    logger.warning("critique_email: %s -- passing through with neutral feedback", reason)
    return settings.CRITIC_SCORE_THRESHOLD, "Critique unavailable; email passed through without review."


def _build_prompt(draft_email: str, extracted_data: ExtractedData, strategic_angle: str) -> str:
    company = extracted_data.get("company_name") or "the company"

    return f"""You are a critical B2B sales email reviewer. Evaluate the
DRAFT EMAIL below, written for {company}, against these criteria:

1. Does it specifically use this strategic angle: "{strategic_angle}"?
   (Not just mention the company generically.)
2. Does it avoid inventing facts not implied by the angle?
3. Is the tone natural, not spammy or full of corporate filler?
4. Is there a clear, low-pressure call to action?
5. Is it reasonably concise (roughly under 150 words)?

DRAFT EMAIL:
{draft_email}

Respond with ONLY a JSON object (no markdown fences, no commentary) in
exactly this shape:

{{
  "score": 0.0,
  "feedback": "string"
}}

Rules:
- score: your 0.0-1.0 estimate of how well the email meets ALL the
  criteria above. Be genuinely critical -- a generic or spammy-sounding
  email should score low even if it's well-written prose.
- feedback: 1-3 concrete, actionable sentences on what to fix. If the
  score is high, briefly say what's working. This feedback will be given
  directly to whoever rewrites the email, so be specific, not vague.
"""


def _try_parse_json(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    return None


def critique_email(draft_email: str, extracted_data: ExtractedData, strategic_angle: str) -> tuple[float, str]:
    """
    Score `draft_email` and return (score, feedback). Never raises:
    falls back to a neutral pass-through result on missing config, API
    failure, or an unparseable response.
    """
    client = _get_client()
    if client is None:
        return _fallback_result("Groq client not configured (missing GROQ_API_KEY)")

    prompt = _build_prompt(draft_email, extracted_data, strategic_angle)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=300,
            reasoning_effort="low",
        )
        raw_text = response.choices[0].message.content
    except Exception as exc:
        return _fallback_result(f"Groq API call failed ({exc})")

    if not raw_text or not raw_text.strip():
        return _fallback_result("Groq returned empty content")

    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    parsed = _try_parse_json(text)

    if parsed is None:
        return _fallback_result("model response had no parseable JSON object")

    try:
        score = float(parsed.get("score", settings.CRITIC_SCORE_THRESHOLD))
        feedback = str(parsed.get("feedback", ""))
    except (TypeError, ValueError):
        return _fallback_result("model response had unexpected shape")

    score = max(0.0, min(1.0, score))  # clamp to valid range
    return score, feedback

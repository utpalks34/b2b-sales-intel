"""
app/agents/extractor.py

extract_data(sources) -> ExtractedData via Groq (Llama 3.3 70B).

Takes the SourceDocs research_domain() produced and asks the model to
pull out decision-makers, pain points, and recent signals as structured
JSON, plus a confidence score for how well-supported the extraction is.

Never raises: a Groq API failure, a malformed/non-JSON response, or an
empty source list all fall through to a low-confidence, mostly-empty
ExtractedData rather than blowing up the caller -- the downstream DB
write step should always be able to call this and get *something* back.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

from groq import Groq

from app.core.config import settings
from app.core.state import ExtractedData, SourceDoc

logger = logging.getLogger(__name__)

MODEL = "openai/gpt-oss-120b"
MAX_CHARS_PER_SOURCE = 3000     # keep the prompt within a reasonable token budget
MAX_SOURCES_IN_PROMPT = 5

_client: Groq | None = None


def _get_client() -> Groq | None:
    global _client
    if _client is None and settings.GROQ_API_KEY:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


def _empty_result(company_name: str = "") -> ExtractedData:
    return ExtractedData(
        company_name=company_name,
        decision_makers=[],
        pain_points=[],
        recent_signals=[],
        confidence=0.0,
    )


def _guess_company_name(sources: list[SourceDoc]) -> str:
    """Crude fallback if the model doesn't return a company_name: derive
    something readable from the first source's domain."""
    if not sources:
        return ""
    host = urlparse(sources[0]["url"]).netloc.removeprefix("www.")
    return host.split(".")[0].capitalize() if host else ""


def _build_prompt(sources: list[SourceDoc]) -> str:
    chunks = []
    for i, s in enumerate(sources[:MAX_SOURCES_IN_PROMPT], start=1):
        content = s["content"][:MAX_CHARS_PER_SOURCE]
        chunks.append(f"--- Source {i} ({s['source_type']}, {s['url']}) ---\n{content}")
    sources_block = "\n\n".join(chunks)

    return f"""You are a B2B sales research analyst. Based ONLY on the source
material below, extract structured information about this company.

{sources_block}

Respond with ONLY a JSON object (no markdown fences, no commentary) in
exactly this shape:

{{
  "company_name": "string",
  "decision_makers": [{{"name": "string", "title": "string"}}],
  "pain_points": ["string", ...],
  "recent_signals": ["string", ...],
  "confidence": 0.0
}}

Rules:
- decision_makers: only named individuals with a clear title (exec,
  founder, VP, director, etc). Omit if none are clearly identifiable.
- pain_points: challenges or problems the company appears to be facing,
  inferred from the sources -- not generic industry pain points.
- recent_signals: concrete recent events (funding, hires, product
  launches, layoffs, expansion, etc) found in the sources.
- confidence: your own 0.0-1.0 estimate of how well-supported this
  extraction is by the sources given. Low source count or vague/old
  content should pull this down.
- If the sources don't support a field, use an empty list/string --
  never invent information not present in the sources.
"""


def _try_parse_json(text: str) -> dict | None:
    """Attempt json.loads(); if that fails, fall back to extracting the
    first {...} block (handles the model adding prose before/after a
    fenced block despite instructions not to). Returns None if nothing
    parses to a dict."""
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


def _parse_response(raw_text: str, fallback_company_name: str) -> ExtractedData:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)  # strip fences if the model added them anyway

    parsed = _try_parse_json(text)
    if parsed is None:
        logger.warning(
            "extract_data: model response had no parseable JSON object; raw: %.200s", text
        )
        return _empty_result(fallback_company_name)

    try:
        return ExtractedData(
            company_name=str(parsed.get("company_name") or fallback_company_name),
            decision_makers=[
                {"name": str(dm.get("name", "")), "title": str(dm.get("title", ""))}
                for dm in parsed.get("decision_makers", [])
                if isinstance(dm, dict)
            ],
            pain_points=[str(p) for p in parsed.get("pain_points", [])],
            recent_signals=[str(s) for s in parsed.get("recent_signals", [])],
            confidence=float(parsed.get("confidence", 0.0)),
        )
    except (TypeError, ValueError) as exc:
        logger.warning("extract_data: model response had unexpected shape (%s)", exc)
        return _empty_result(fallback_company_name)


def extract_data(sources: list[SourceDoc]) -> ExtractedData:
    """
    Extract decision-makers, pain points, and recent signals from
    `sources` via Groq. Returns a low-confidence, mostly-empty
    ExtractedData (never raises) if sources is empty, Groq isn't
    configured, the API call fails, or the response can't be parsed.
    """
    fallback_name = _guess_company_name(sources)

    if not sources:
        logger.warning("extract_data: called with no sources")
        return _empty_result(fallback_name)

    client = _get_client()
    if client is None:
        logger.warning("extract_data: Groq client not configured (missing GROQ_API_KEY)")
        return _empty_result(fallback_name)

    prompt = _build_prompt(sources)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1200,
            reasoning_effort="low",
        )
        raw_text = response.choices[0].message.content
    except Exception as exc:
        logger.warning("extract_data: Groq API call failed (%s)", exc)
        return _empty_result(fallback_name)

    if not raw_text:
        logger.warning("extract_data: Groq returned empty content")
        return _empty_result(fallback_name)

    return _parse_response(raw_text, fallback_name)
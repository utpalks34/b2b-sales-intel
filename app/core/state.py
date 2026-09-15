"""Core state schema for the LangGraph pipeline.
Frozen contract -- update here first, then propagate to any node/module
that depends on it.
"""
from typing import TypedDict, Literal, Optional


class SourceDoc(TypedDict):
    url: str
    title: str
    content: str
    source_type: Literal["news", "sec_filing", "blog", "company_site", "review_site"]
    scraped_via: Literal["tavily", "trafilatura", "beautifulsoup"]
    fetched_at: str


class ExtractedData(TypedDict):
    company_name: str
    decision_makers: list[dict]
    pain_points: list[str]
    recent_signals: list[str]
    confidence: float


class PipelineState(TypedDict):
    run_id: str
    domain: str
    raw_sources: list[SourceDoc]
    extracted_data: Optional[ExtractedData]
    strategic_angle: Optional[str]        # output of analyzer_node
    draft_email: Optional[str]
    critic_score: Optional[float]
    critic_feedback: Optional[str]
    revision_count: int
    human_decision: Optional[Literal["approved", "rejected", "edited"]]
    final_email: Optional[str]
    error_log: list[str]
    updated_at: str

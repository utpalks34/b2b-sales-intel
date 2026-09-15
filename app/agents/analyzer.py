"""Reasoning step: given extracted facts, identify the single biggest
operational weakness of the target company relevant to our product.
Output feeds the Writer as `strategic_angle` -- the Writer must use it,
and the Critic checks that it did.
"""
from app.core.state import ExtractedData


def analyze_strategic_angle(extracted_data: ExtractedData) -> str:
    """TODO: implement ChatGroq reasoning call over extracted_data."""
    raise NotImplementedError

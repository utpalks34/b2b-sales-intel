---
name: langgraph-node
description: Use when adding or modifying a node in the pipeline's LangGraph StateGraph. Ensures consistent state typing and error handling.
---

- Every node function takes PipelineState and returns a partial state update (dict) -- never mutate in place.
- Wrap external calls (LLM, DB) in try/except; on failure append to error_log and return state unchanged rather than raising.
- Never add a new state field without updating app/core/state.py first.
- Keep node functions in app/agents/, one file per agent (researcher, extractor, analyzer, writer, critic).

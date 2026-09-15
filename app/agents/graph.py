"""Wires researcher -> extractor -> analyzer -> writer -> critic ->
human_review -> finalize into a LangGraph StateGraph, with a Postgres
checkpointer and an interrupt before finalize for human-in-the-loop approval.
"""
from langgraph.graph import StateGraph
from app.core.state import PipelineState

# TODO:
#  1. define each node function (call into app/agents/*.py)
#  2. graph.add_node(...) for each
#  3. graph.add_conditional_edges("critic", route_after_critic,
#         {"revise": "writer", "review": "finalize"})
#  4. compiled = graph.compile(checkpointer=get_checkpointer(),
#         interrupt_before=["finalize"])

graph = StateGraph(PipelineState)
compiled = None  # replace once wired up

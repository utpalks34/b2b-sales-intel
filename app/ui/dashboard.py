"""Streamlit human-review UI. Run with: streamlit run app/ui/dashboard.py
Polls GET /research/{run_id}/drafts, posts to the decision endpoint.
"""
import httpx
import streamlit as st

st.title("NeuroLeads AI -- Draft Review")
# TODO: poll API via httpx, show extracted_data + strategic_angle + draft +
# critic_feedback, with Approve / Edit / Reject buttons calling the decision
# endpoint.

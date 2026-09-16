"""
app/ui/streamlit_app.py

Streamlit frontend for the B2B Sales Intelligence Pipeline. Thin client:
all real logic lives behind the FastAPI layer (app/api/main.py) -- this
file only calls that API over HTTP and renders the result.

Run with: streamlit run app/ui/streamlit_app.py
Requires the API running separately: uvicorn app.api.main:app --reload
"""
import os

import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="B2B Sales Intelligence Pipeline", layout="wide")
st.title("B2B Sales Intelligence Pipeline")

if "run_ids" not in st.session_state:
    st.session_state.run_ids = []  # list of (run_id, domain)


def _start_runs(domains: list[str]) -> None:
    try:
        resp = requests.post(f"{API_BASE_URL}/runs", json={"domains": domains}, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        st.error(f"Failed to start runs: {exc}")
        return
    data = resp.json()
    for run in data.get("runs", []):
        st.session_state.run_ids.append((run["run_id"], run["domain"]))


def _get_status(run_id: str) -> dict | None:
    try:
        resp = requests.get(f"{API_BASE_URL}/runs/{run_id}", timeout=15)
    except requests.RequestException as exc:
        st.error(f"Failed to fetch status for {run_id}: {exc}")
        return None
    if resp.status_code == 404:
        st.error(f"Unknown run_id: {run_id}")
        return None
    resp.raise_for_status()
    return resp.json()


def _submit_decision(run_id: str, decision: str, edited_email: str | None) -> dict | None:
    payload = {"decision": decision}
    if edited_email is not None:
        payload["edited_email"] = edited_email
    try:
        resp = requests.post(f"{API_BASE_URL}/runs/{run_id}/decision", json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        st.error(f"Failed to submit decision for {run_id}: {exc}")
        return None
    return resp.json()


st.subheader("Start new research")
domains_text = st.text_area("Domains (one per line)", placeholder="seismic.com\nstripe.com")
if st.button("Start Research"):
    domains = [d.strip() for d in domains_text.splitlines() if d.strip()]
    if not domains:
        st.warning("Enter at least one domain.")
    else:
        _start_runs(domains)
        st.rerun()

st.divider()

st.subheader("Runs")
if st.button("Refresh all"):
    st.rerun()

if not st.session_state.run_ids:
    st.info("No runs started yet.")

for run_id, domain in st.session_state.run_ids:
    status = _get_status(run_id)
    if status is None:
        continue

    with st.expander(f"{domain} -- {status['status']}", expanded=(status["status"] == "awaiting_review")):
        st.caption(f"run_id: {run_id}")

        if status["status"] == "running":
            st.info("Research in progress...")

        elif status["status"] == "failed":
            st.error("This run failed.")
            for err in status.get("error_log", []):
                st.text(err)

        elif status["status"] == "awaiting_review":
            st.write(f"**Strategic angle:** {status.get('strategic_angle') or '(none)'}")
            st.write(f"**Critic score:** {status.get('critic_score')}")
            st.write(f"**Critic feedback:** {status.get('critic_feedback') or '(none)'}")
            st.text_area("Draft email", value=status.get("draft_email") or "", height=200, key=f"draft_{run_id}", disabled=True)

            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("Approve", key=f"approve_{run_id}"):
                    _submit_decision(run_id, "approved", None)
                    st.rerun()
            with col2:
                if st.button("Reject", key=f"reject_{run_id}"):
                    _submit_decision(run_id, "rejected", None)
                    st.rerun()
            with col3:
                edited = st.text_area("Edit email", value=status.get("draft_email") or "", key=f"edit_{run_id}", height=150)
                if st.button("Submit Edit", key=f"submit_edit_{run_id}"):
                    _submit_decision(run_id, "edited", edited)
                    st.rerun()

        elif status["status"] in ("completed", "rejected"):
            st.write(f"**Human decision:** {status.get('human_decision')}")
            if status.get("final_email"):
                st.text_area("Final email", value=status["final_email"], height=200, key=f"final_{run_id}", disabled=True)
            else:
                st.write("(No final email -- rejected.)")
            if status.get("error_log"):
                with st.expander("Warnings/errors during this run"):
                    for err in status["error_log"]:
                        st.text(err)

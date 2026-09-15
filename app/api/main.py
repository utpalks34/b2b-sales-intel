"""FastAPI app entrypoint. Run with: uvicorn app.api.main:app --reload"""
from fastapi import FastAPI
from app.api.routes import router

app = FastAPI(title="NeuroLeads AI Orchestrator")
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}

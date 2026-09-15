---
name: fastapi-endpoint
description: Use when adding an endpoint to app/api/routes.py. Ensures consistent request/response shape and background-task usage.
---

- Long-running work (anything touching the graph) goes through BackgroundTasks -- never block the request.
- Request/response models live in app/api/schemas.py, not inline.
- Every endpoint that touches a run_id validates it exists before proceeding.

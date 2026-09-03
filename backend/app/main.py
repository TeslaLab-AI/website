"""
Purpose:
Defines the TeslaLab FastAPI application.

Responsibilities:
- Expose GET / and GET /health so a running server can be verified immediately.
- Mount the GitHub App installation-start route.
"""

from fastapi import FastAPI

from app.github_install import router as github_install_router
from app.github_api import router as github_api_router

app = FastAPI(title="TeslaLab API")
app.include_router(github_install_router)
app.include_router(github_api_router)


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/health")
def health_check():
    return {"status": "ok", "message": "TeslaLab backend is healthy"}

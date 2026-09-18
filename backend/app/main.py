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
from app.scan_api import router as scan_api_router
from app.chat_api import router as chat_api_router
from app.fix_api import router as fix_api_router

app = FastAPI(title="TeslaLab API")
app.include_router(github_install_router)
app.include_router(github_api_router)
app.include_router(scan_api_router)
app.include_router(chat_api_router)
app.include_router(fix_api_router)


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "ok"}


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok", "message": "TeslaLab backend is healthy"}

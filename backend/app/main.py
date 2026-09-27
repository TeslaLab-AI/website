"""
Purpose:
Defines the TeslaLab FastAPI application.

Responsibilities:
- Expose GET / and GET /health so a running server can be verified immediately.
- Mount the GitHub App installation-start route.
"""
import logging
import sys
from pathlib import Path

# Configure unbuffered root logging streaming to stdout for Render/Docker/local consoles
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

_backend_root = Path(__file__).resolve().parents[1]
_repo_root = _backend_root.parent
for _p in (str(_backend_root), str(_repo_root)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.github_install import router as github_install_router
from app.github_api import router as github_api_router
from app.scan_api import router as scan_api_router
from app.chat_api import router as chat_api_router
from app.fix_api import router as fix_api_router
from app.session_api import router as session_api_router
from app.otp_api import router as otp_api_router

app = FastAPI(title="TeslaLab API")

# Allow requests from frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(github_install_router)
app.include_router(github_api_router)
app.include_router(scan_api_router)
app.include_router(chat_api_router)
app.include_router(fix_api_router)
app.include_router(session_api_router)
app.include_router(otp_api_router)


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "ok"}


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok", "message": "TeslaLab backend is healthy"}

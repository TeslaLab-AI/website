"""
Purpose:
Loads backend environment values used by the GitHub install-start flow.

Responsibilities:
- Read FASTAPI_STATE_SECRET, GitHub App slug, and Supabase URL/keys.
- Fail at request time if required values are missing.
- Never expose the GitHub App private key.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def state_secret() -> str:
    return _require("FASTAPI_STATE_SECRET")


def github_app_slug() -> str:
    return _require("GITHUB_APP_NAME")


def supabase_url() -> str:
    return _require("SUPABASE_URL").rstrip("/")


def supabase_publishable_key() -> str:
    return _require("SUPABASE_PUBLISHABLE_KEY")

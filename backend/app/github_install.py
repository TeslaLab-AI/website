"""
Purpose:
Starts GitHub App installation for an authenticated TeslaLab workspace.

Responsibilities:
- Authenticate the caller from a Supabase access token.
- Resolve workspace membership on the server (ignore any client workspace id).
- Issue a short-lived HMAC-signed state bound to user and workspace.
- Redirect to the configured GitHub App installation URL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from json import JSONDecodeError
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import RedirectResponse

from app.config import (
    github_app_slug,
    state_secret,
    supabase_publishable_key,
    supabase_url,
)

STATE_TTL_SECONDS = 600

router = APIRouter()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_install_state(*, user_id: str, workspace_id: str, secret: str) -> str:
    payload = json.dumps(
        {
            "uid": user_id,
            "wid": workspace_id,
            "exp": int(time.time()) + STATE_TTL_SECONDS,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    body = _b64url(payload)
    signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _json_get(url: str, headers: dict[str, str]) -> tuple[int, object | None]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, None
    except (URLError, JSONDecodeError, TimeoutError):
        return 503, None


def _authenticated_user_id(access_token: str) -> str:
    status, body = _json_get(
        f"{supabase_url()}/auth/v1/user",
        {
            "Authorization": f"Bearer {access_token}",
            "apikey": supabase_publishable_key(),
        },
    )
    if status != 200 or not isinstance(body, dict) or not body.get("id"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(body["id"])


def _workspace_id_for_user(access_token: str) -> str:
    query = urlencode({"select": "workspace_id", "order": "created_at.asc", "limit": "1"})
    status, body = _json_get(
        f"{supabase_url()}/rest/v1/workspace_members?{query}",
        {
            "Authorization": f"Bearer {access_token}",
            "apikey": supabase_publishable_key(),
        },
    )
    if status == 401:
        raise HTTPException(status_code=401, detail="Authentication required")
    if status != 200 or not isinstance(body, list) or not body:
        raise HTTPException(status_code=400, detail="No workspace found")
    workspace_id = body[0].get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="No workspace found")
    return str(workspace_id)


@router.post("/api/github/install/start")
def start_github_install(authorization: str | None = Header(default=None)) -> RedirectResponse:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    access_token = authorization.split(" ", 1)[1].strip()
    if not access_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        secret = state_secret()
        app_slug = github_app_slug()
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail="Server configuration is incomplete") from error

    user_id = _authenticated_user_id(access_token)
    workspace_id = _workspace_id_for_user(access_token)
    state = sign_install_state(user_id=user_id, workspace_id=workspace_id, secret=secret)

    install_url = (
        f"https://github.com/apps/{quote(app_slug, safe='')}/installations/new"
        f"?state={quote(state, safe='')}"
    )
    return RedirectResponse(url=install_url, status_code=302)

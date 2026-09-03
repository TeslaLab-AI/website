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

from pydantic import BaseModel
from fastapi import APIRouter, Header, HTTPException, Body
from fastapi.responses import RedirectResponse

from app.config import (
    github_app_slug,
    state_secret,
    supabase_publishable_key,
    supabase_service_role_key,
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


def verify_install_state(state: str, secret: str) -> dict:
    try:
        body, signature = state.rsplit(".", 1)
        expected_signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("Invalid signature")
            
        # Add padding if needed for base64
        padded = body + "=" * (4 - len(body) % 4) if len(body) % 4 != 0 else body
        payload_bytes = base64.urlsafe_b64decode(padded)
        payload = json.loads(payload_bytes.decode("utf-8"))
        
        if payload.get("exp", 0) < int(time.time()):
            raise ValueError("State expired")
            
        return payload
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid or expired state")


def _json_post(url: str, headers: dict[str, str], payload: dict) -> tuple[int, object | None]:
    request = Request(url, headers={**headers, "Content-Type": "application/json"}, method="POST", data=json.dumps(payload).encode("utf-8"))
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8").strip()
            return response.status, json.loads(body) if body else None
    except HTTPError as error:
        try:
            body = error.read().decode("utf-8").strip()
            return error.code, json.loads(body) if body else None
        except:
            return error.code, None
    except (URLError, JSONDecodeError, TimeoutError):
        return 503, None


def _json_get(url: str, headers: dict[str, str]) -> tuple[int, object | None]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8").strip()
            return response.status, json.loads(body) if body else None
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
        print(f"workspace lookup failed: status={status}, body={body}")
        raise HTTPException(status_code=400, detail="No workspace found")
    workspace_id = body[0].get("workspace_id")
    if not workspace_id:
        print(f"workspace lookup missing workspace_id: status={status}, body={body}")
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


class CallbackRequest(BaseModel):
    installation_id: str
    state: str
    setup_action: str | None = None


@router.post("/api/github/callback")
def github_callback(request: CallbackRequest, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    access_token = authorization.split(" ", 1)[1].strip()
    if not access_token:
        raise HTTPException(status_code=401, detail="Authentication required")
        
    try:
        secret = state_secret()
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail="Server configuration is incomplete") from error

    import logging
    logger = logging.getLogger("github_install")

    setup_action = getattr(request, 'setup_action', 'unknown')
    logger.info(f"Processing GitHub callback: setup_action={setup_action}, installation_id={request.installation_id}")

    # 1. Validate the signed state
    try:
        payload = verify_install_state(request.state, secret)
    except Exception as e:
        logger.warning(f"State verification failed: {e}")
        raise

    state_uid = payload.get("uid")
    state_wid = payload.get("wid")
    
    # 2. Authenticate the caller and verify identity matches state
    user_id = _authenticated_user_id(access_token)
    if user_id != state_uid:
        logger.warning("State identity mismatch")
        raise HTTPException(status_code=403, detail="State identity mismatch")
        
    # Verify the workspace is still bound to the user
    workspace_id = _workspace_id_for_user(access_token)
    if workspace_id != state_wid:
        logger.warning("Workspace mismatch")
        raise HTTPException(status_code=403, detail="Workspace mismatch")
        
    # 3. Verify the installation_id belongs to our GitHub App
    from app.github_api import verify_installation
    try:
        installation_id = int(request.installation_id)
    except ValueError:
        logger.warning("Invalid installation_id format")
        raise HTTPException(status_code=400, detail="Invalid installation_id")
        
    if not verify_installation(installation_id):
        logger.warning(f"GitHub App verification failed for installation_id={installation_id}")
        raise HTTPException(status_code=403, detail="Invalid GitHub installation")
        
    # 4. Persist the installation using Service Role key
    # UPSERT to allow overriding/re-installing
    status, body = _json_post(
        f"{supabase_url()}/rest/v1/github_installations?on_conflict=github_installation_id",
        headers={
            "Authorization": f"Bearer {supabase_service_role_key()}",
            "apikey": supabase_service_role_key(),
            "Prefer": "resolution=merge-duplicates"
        },
        payload={
            "workspace_id": workspace_id,
            "github_installation_id": installation_id
        }
    )
    if status not in (200, 201, 204):
        logger.error(f"Failed to persist installation. Status: {status}, Body: {body}")
        raise HTTPException(status_code=500, detail="Failed to persist installation")
        
    logger.info("Successfully bound GitHub installation")
    return {"status": "success"}


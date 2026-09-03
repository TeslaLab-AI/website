"""
Purpose:
Common helpers for interacting with GitHub API and managing GitHub App authentication.

Responsibilities:
- Generate GitHub App JWTs using PyJWT and cryptography.
- Fetch installation access tokens.
- Verify GitHub installations.
- Fetch available repositories for an installation.
"""

from __future__ import annotations

import time
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt
from fastapi import APIRouter, Header, HTTPException, Body
from pydantic import BaseModel

from app.config import (
    github_app_id, 
    github_app_private_key, 
    supabase_url, 
    supabase_service_role_key,
    supabase_publishable_key
)
from app.github_install import _json_get, _authenticated_user_id, _workspace_id_for_user

router = APIRouter()

def _json_request(url: str, headers: dict[str, str], method: str = "GET", data: bytes | None = None) -> tuple[int, object | None]:
    request = Request(url, headers=headers, method=method, data=data)
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
    except (URLError, json.JSONDecodeError, TimeoutError):
        return 503, None

def _json_post(url: str, headers: dict[str, str], payload: dict) -> tuple[int, object | None]:
    data = json.dumps(payload).encode("utf-8")
    headers = {**headers, "Content-Type": "application/json"}
    return _json_request(url, headers, method="POST", data=data)

def get_github_jwt() -> str:
    """Generates a short-lived JWT for GitHub App authentication."""
    app_id = github_app_id()
    private_key = github_app_private_key()
    
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": app_id
    }
    
    encoded = jwt.encode(payload, private_key, algorithm="RS256")
    return encoded


def verify_installation(installation_id: int) -> bool:
    """Verifies that an installation ID exists and belongs to this GitHub App."""
    app_jwt = get_github_jwt()
    status, _ = _json_request(
        f"https://api.github.com/app/installations/{installation_id}",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github.v3+json"
        }
    )
    return status == 200


def get_installation_token(installation_id: int) -> str:
    """Fetches an installation access token."""
    app_jwt = get_github_jwt()
    status, body = _json_request(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github.v3+json"
        },
        method="POST"
    )
    if status == 404:
        raise HTTPException(status_code=404, detail="Installation not found on GitHub")
    if status != 201 or not isinstance(body, dict) or "token" not in body:
        raise HTTPException(status_code=500, detail="Failed to acquire GitHub installation token")
    return body["token"]


def get_workspace_installation(workspace_id: str) -> dict | None:
    from urllib.parse import urlencode
    query = urlencode({"select": "id,github_installation_id", "workspace_id": f"eq.{workspace_id}"})
    status, body = _json_request(
        f"{supabase_url()}/rest/v1/github_installations?{query}",
        headers={
            "Authorization": f"Bearer {supabase_service_role_key()}",
            "apikey": supabase_service_role_key(),
        }
    )
    if status == 200 and isinstance(body, list) and len(body) > 0:
        return {
            "id": body[0]["id"],
            "github_installation_id": int(body[0]["github_installation_id"])
        }
    return None


@router.get("/api/github/repositories/available")
def get_available_repositories(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    access_token = authorization.split(" ", 1)[1].strip()

    # Verify user and workspace
    _ = _authenticated_user_id(access_token)
    workspace_id = _workspace_id_for_user(access_token)

    # Get installation ID for workspace
    installation = get_workspace_installation(workspace_id)
    if not installation:
        raise HTTPException(status_code=400, detail="No GitHub installation found for workspace")

    installation_id = installation["github_installation_id"]

    # Fetch available repos from GitHub
    try:
        token = get_installation_token(installation_id)
    except HTTPException as e:
        if e.status_code == 404:
            # Installation was uninstalled on GitHub's side. Delete it from our DB to reset the UI.
            _json_request(
                f"{supabase_url()}/rest/v1/github_installations?github_installation_id=eq.{installation_id}",
                headers={
                    "Authorization": f"Bearer {supabase_service_role_key()}",
                    "apikey": supabase_service_role_key(),
                },
                method="DELETE"
            )
        raise e

    status, body = _json_request(
        "https://api.github.com/installation/repositories?per_page=100",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }
    )
    if status != 200 or not isinstance(body, dict) or "repositories" not in body:
        raise HTTPException(status_code=500, detail="Failed to fetch repositories from GitHub")
    
    repos = body["repositories"]
    # Return minimal safe metadata
    safe_repos = [
        {
            "id": r["id"],
            "owner": r["owner"]["login"],
            "name": r["name"],
            "default_branch": r["default_branch"],
            "full_name": r["full_name"],
            "private": r["private"],
        }
        for r in repos
    ]
    
    total_count = body.get("total_count", len(safe_repos))
    return {
        "repositories": safe_repos,
        "has_more": total_count > len(safe_repos)
    }


class SelectRepoRequest(BaseModel):
    github_repo_id: int
    owner: str
    name: str
    default_branch: str


@router.post("/api/github/repositories/select")
def select_repository(request: SelectRepoRequest, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    access_token = authorization.split(" ", 1)[1].strip()

    _ = _authenticated_user_id(access_token)
    workspace_id = _workspace_id_for_user(access_token)

    installation = get_workspace_installation(workspace_id)
    if not installation:
        raise HTTPException(status_code=400, detail="No GitHub installation found for workspace")
        
    inst_uuid = installation["id"]
    github_inst_id = installation["github_installation_id"]

    # Verify that the repository actually belongs to the installation
    # by fetching it from GitHub API
    token = get_installation_token(github_inst_id)
    status, body = _json_request(
        f"https://api.github.com/repositories/{request.github_repo_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }
    )
    if status != 200:
        raise HTTPException(status_code=403, detail="Repository not found or not accessible by this installation")

    # The repo is valid and belongs to the installation. Insert/update it in the DB using service role.
    status, body = _json_post(
        f"{supabase_url()}/rest/v1/repositories?on_conflict=workspace_id,github_repo_id",
        headers={
            "Authorization": f"Bearer {supabase_service_role_key()}",
            "apikey": supabase_service_role_key(),
            "Prefer": "resolution=merge-duplicates"
        },
        payload={
            "workspace_id": workspace_id,
            "github_installation_id": inst_uuid,
            "github_repo_id": request.github_repo_id,
            "owner": request.owner,
            "name": request.name,
            "default_branch": request.default_branch,
            "status": "selected"
        }
    )
    if status not in (200, 201, 204):
        raise HTTPException(status_code=500, detail="Failed to persist repository selection")
        
    return {"status": "success"}

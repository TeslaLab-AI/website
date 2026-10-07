"""Vercel adapter: deploys a GitHub repo branch to Vercel and reports status/logs.

Flow for deploy():
    1. ensure a Vercel project exists (one per tenant+project, name derived from a hash)
    2. upsert env vars on that project (encrypted; values are never logged)
    3. create a git deployment (POST /v13/deployments with gitSource)

Tenant isolation: every deployment is tagged with meta {teamlabTenant, teamlabProject}.
status/logs/rollback re-read that tag and answer DeploymentNotFound when it does not
match the caller's tenant (same answer as "does not exist", so IDs cannot be probed).

Verify against current Vercel docs on first real run (endpoint versions change):
    POST /v13/deployments            create (gitSource: type, org, repo, ref)
    GET  /v13/deployments/{id}       readyState, url, alias, meta
    GET  /v3/deployments/{id}/events build logs
    GET  /v9/projects/{name}  /  POST /v11/projects   ensure project
    POST /v10/projects/{id}/env?upsert=true           env vars
    POST /v10/projects/{id}/promote/{deploymentId}    rollback (promote older deploy)
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterator, Optional

import httpx

from .log_masking import mask_secrets
from .adapters.base import (
    DeploymentAdapter,
    DeploymentError,
    DeploymentNotFound,
    DeployResult,
    DeployStatus,
    LogEntry,
)

API = "https://api.vercel.com"
TENANT_TAG = "teamlabTenant"
PROJECT_TAG = "teamlabProject"

_STATE_MAP = {
    "QUEUED": DeployStatus.QUEUED,
    "INITIALIZING": DeployStatus.QUEUED,
    "BUILDING": DeployStatus.BUILDING,
    "READY": DeployStatus.READY,
    "ERROR": DeployStatus.FAILED,
    "CANCELED": DeployStatus.FAILED,
}
_REPO_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def parse_github_url(repo_url: str) -> tuple[str, str]:
    match = _REPO_URL.match((repo_url or "").strip())
    if not match:
        raise DeploymentError("Only https://github.com/<org>/<repo> repositories are supported")
    return match.group(1), match.group(2)


def vercel_project_name(tenant_id: str, project_id: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{project_id}".encode()).hexdigest()[:20]
    return f"tl-{digest}"


class VercelAdapter(DeploymentAdapter):
    def __init__(
        self,
        token: str,
        team_id: Optional[str] = None,
        *,
        client: Optional[httpx.Client] = None,
        framework: Optional[str] = "nextjs",
        target: str = "production",
        timeout: float = 30.0,
    ) -> None:
        if not token:
            raise ValueError("Vercel token is required")
        self._token = token  # never log this
        self._team_id = team_id
        self._framework = framework
        self._target = target
        self._client = client or httpx.Client(timeout=timeout)

    def __repr__(self) -> str:
        return "VercelAdapter(token=***)"

    # -- HTTP helper ------------------------------------------------------
    def _request(self, method: str, path: str, *, params=None, json=None, ok_404: bool = False):
        query = dict(params or {})
        if self._team_id:
            query["teamId"] = self._team_id
        try:
            response = self._client.request(
                method, f"{API}{path}", params=query, json=json,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError as exc:
            raise DeploymentError(f"Could not reach Vercel: {type(exc).__name__}") from None
        if response.status_code == 404:
            if ok_404:
                return None
            raise DeploymentNotFound("Not found")
        if response.status_code in (401, 403):
            raise DeploymentError("Vercel rejected the token (check scope and team)")
        if response.status_code == 429 or response.status_code >= 500:
            raise DeploymentError(f"Vercel temporary error ({response.status_code})")
        if response.status_code >= 400:
            raise DeploymentError(f"Vercel error {response.status_code}: {mask_secrets(response.text)[:300]}")
        return response.json() if response.content else {}

    @staticmethod
    def _check_ids(tenant_id: str, project_id: str) -> None:
        for value, label in ((tenant_id, "tenant_id"), (project_id, "project_id")):
            if not isinstance(value, str) or not _ID.match(value):
                raise ValueError(f"Invalid {label}")

    # -- mapping ----------------------------------------------------------
    @staticmethod
    def _to_result(data: dict) -> DeployResult:
        state = (data.get("readyState") or data.get("status") or "QUEUED").upper()
        status = _STATE_MAP.get(state, DeployStatus.BUILDING)
        aliases = data.get("alias") or []
        host = aliases[0] if aliases else data.get("url")  # alias is public; raw URL may be protected
        error = None
        if status == DeployStatus.FAILED:
            error = mask_secrets(
                (data.get("errorMessage") or (data.get("error") or {}).get("message") or f"Vercel state {state}")
            )[:1000]
        return DeployResult(
            deployment_id=data.get("id") or data.get("uid") or "",
            status=status,
            url=f"https://{host}" if host else None,
            error=error,
        )

    def _get_owned(self, tenant_id: str, deployment_id: str) -> dict:
        if not isinstance(deployment_id, str) or not _ID.match(deployment_id):
            raise DeploymentNotFound("Not found")
        data = self._request("GET", f"/v13/deployments/{deployment_id}")
        meta = data.get("meta") or {}
        if meta.get(TENANT_TAG) != tenant_id:
            raise DeploymentNotFound("Not found")
        return data

    # -- interface --------------------------------------------------------
    def deploy(self, tenant_id, project_id, repo_url, branch, env_vars) -> DeployResult:
        self._check_ids(tenant_id, project_id)
        org, repo = parse_github_url(repo_url)
        name = vercel_project_name(tenant_id, project_id)

        if self._request("GET", f"/v9/projects/{name}", ok_404=True) is None:
            body = {"name": name, "gitRepository": {"type": "github", "repo": f"{org}/{repo}"}}
            if self._framework:
                body["framework"] = self._framework
            self._request("POST", "/v11/projects", json=body)

        if env_vars:
            self._request(
                "POST", f"/v10/projects/{name}/env", params={"upsert": "true"},
                json=[
                    {"key": k, "value": v, "type": "encrypted", "target": ["production", "preview"]}
                    for k, v in env_vars.items()
                ],
            )

        data = self._request(
            "POST", "/v13/deployments", params={"forceNew": "1", "skipAutoDetectionConfirmation": "1"},
            json={
                "name": name, "project": name, "target": self._target,
                "gitSource": {"type": "github", "org": org, "repo": repo, "ref": branch},
                "meta": {TENANT_TAG: tenant_id, PROJECT_TAG: project_id},
            },
        )
        return self._to_result(data)

    def status(self, tenant_id, deployment_id) -> DeployResult:
        return self._to_result(self._get_owned(tenant_id, deployment_id))

    def logs(self, tenant_id, deployment_id) -> Iterator[LogEntry]:
        owned = self._get_owned(tenant_id, deployment_id)
        project_id = (owned.get("meta") or {}).get(PROJECT_TAG, "")
        events = self._request(
            "GET", f"/v3/deployments/{deployment_id}/events",
            params={"builds": "1", "direction": "forward", "limit": "-1"},
        ) or []
        for event in events:
            text = event.get("text") or (event.get("payload") or {}).get("text")
            if not text:
                continue
            kind = event.get("type", "")
            created = event.get("created") or (event.get("payload") or {}).get("date")
            when = (
                datetime.fromtimestamp(created / 1000, tz=timezone.utc)
                if isinstance(created, (int, float)) else datetime.now(timezone.utc)
            )
            yield LogEntry(
                project_id=project_id,
                level="error" if kind in ("stderr", "error") else "info",
                source="build",
                message=mask_secrets(text),
                timestamp=when,
            )

    def rollback(self, tenant_id, project_id, to_deployment_id) -> DeployResult:
        self._check_ids(tenant_id, project_id)
        target = self._get_owned(tenant_id, to_deployment_id)
        if (target.get("meta") or {}).get(PROJECT_TAG) != project_id:
            raise DeploymentNotFound("Not found")
        if _STATE_MAP.get((target.get("readyState") or "").upper()) != DeployStatus.READY:
            raise DeploymentError("Can only roll back to a deployment that finished successfully")
        name = vercel_project_name(tenant_id, project_id)
        self._request("POST", f"/v10/projects/{name}/promote/{to_deployment_id}")
        result = self._to_result(target)
        return DeployResult(result.deployment_id, DeployStatus.ROLLED_BACK, result.url)

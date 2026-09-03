"""
Purpose:
Handles repository analysis and scanning logic.

Responsibilities:
- Provide an endpoint to trigger a new repository scan.
- Provide an endpoint to fetch the latest scan and its findings.
- Run a simulated background task that mimics a time-consuming code analysis,
  inserting mock findings into the database when finished.
"""

from __future__ import annotations

import asyncio
import uuid
import random
import json
from typing import List, Dict, Any

from fastapi import APIRouter, Header, HTTPException, BackgroundTasks
from pydantic import BaseModel

from app.config import supabase_url, supabase_service_role_key
from app.github_api import _json_post, _json_request
from app.github_install import _authenticated_user_id, _workspace_id_for_user

router = APIRouter()


async def perform_simulated_scan(scan_id: str):
    """
    Simulates a repository scan by waiting for a short duration and then inserting
    mock findings across all categories.
    """
    await asyncio.sleep(3)  # Simulate processing time
    
    findings = [
        # Bugs
        {"category": "bugs", "severity": "high", "title": "Null pointer exception possible", "description": "Variable 'user' may be null when accessing 'user.id'.", "file_path": "src/controllers/userController.ts", "line_number": 42},
        {"category": "bugs", "severity": "medium", "title": "Memory leak in event listener", "description": "Event listener on 'scroll' is not removed on component unmount.", "file_path": "src/components/Header.tsx", "line_number": 115},
        
        # Dependencies
        {"category": "dependencies", "severity": "critical", "title": "Outdated version of lodash", "description": "Lodash v4.17.15 has a known prototype pollution vulnerability. Upgrade to ^4.17.21.", "file_path": "package.json", "line_number": 23},
        {"category": "dependencies", "severity": "low", "title": "Unused dependency 'moment'", "description": "Package 'moment' is installed but not imported anywhere.", "file_path": "package.json", "line_number": 25},
        
        # Security
        {"category": "security", "severity": "critical", "title": "Hardcoded JWT secret", "description": "A hardcoded secret key was found in the configuration file.", "file_path": "backend/config/default.json", "line_number": 8},
        {"category": "security", "severity": "high", "title": "SQL Injection vulnerability", "description": "Raw SQL query uses string concatenation instead of parameterized queries.", "file_path": "backend/services/db.js", "line_number": 56},
        
        # Testing
        {"category": "testing", "severity": "medium", "title": "Missing unit tests for authentication", "description": "The AuthService class has 0% test coverage.", "file_path": "src/services/AuthService.ts", "line_number": 1},
        {"category": "testing", "severity": "low", "title": "Flaky test in e2e suite", "description": "The login test frequently fails due to missing await on DOM element resolution.", "file_path": "tests/e2e/login.spec.ts", "line_number": 18},
    ]

    # Insert findings
    headers = {
        "Authorization": f"Bearer {supabase_service_role_key()}",
        "apikey": supabase_service_role_key(),
    }
    
    for finding in findings:
        payload = {
            "scan_id": scan_id,
            "category": finding["category"],
            "severity": finding["severity"],
            "title": finding["title"],
            "description": finding["description"],
            "file_path": finding["file_path"],
            "line_number": finding["line_number"]
        }
        _json_post(f"{supabase_url()}/rest/v1/scan_findings", headers, payload)
        
    # Mark scan as completed
    patch_headers = {
        **headers,
        "Content-Type": "application/json"
    }
    _json_request(
        f"{supabase_url()}/rest/v1/scans?id=eq.{scan_id}",
        patch_headers,
        method="PATCH",
        data=json.dumps({"status": "completed", "completed_at": "now()"}).encode("utf-8")
    )


class StartScanRequest(BaseModel):
    repository_id: str


@router.post("/api/github/scan/start")
def start_scan(request: StartScanRequest, background_tasks: BackgroundTasks, authorization: str | None = Header(default=None)):
    # 1. Validate the authorization header exists and follows the Bearer schema
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # 2. Extract the raw JWT token string
    access_token = authorization.split(" ", 1)[1].strip()

    # 3. Decode the JWT to find out which workspace the user belongs to
    workspace_id = _workspace_id_for_user(access_token)

    # 4. Define headers for communicating with the Supabase REST API using the service role key
    # (since the backend acts as a privileged admin over the database)
    headers = {
        "Authorization": f"Bearer {supabase_service_role_key()}",
        "apikey": supabase_service_role_key(),
    }
    
    # 5. Security Check: Verify that the requested repository actually belongs to the user's workspace
    status, body = _json_request(
        f"{supabase_url()}/rest/v1/repositories?id=eq.{request.repository_id}&workspace_id=eq.{workspace_id}&select=id",
        headers
    )
    if status != 200 or not isinstance(body, list) or len(body) == 0:
        raise HTTPException(status_code=404, detail="Repository not found in workspace")

    # 6. Generate a unique ID for this new scan
    scan_id = str(uuid.uuid4())
    
    # 7. Insert the initial scan record into the database with an 'in_progress' status
    status, body = _json_post(
        f"{supabase_url()}/rest/v1/scans",
        headers,
        payload={
            "id": scan_id,
            "repository_id": request.repository_id,
            "workspace_id": workspace_id,
            "status": "in_progress"
        }
    )
    if status not in (200, 201, 204):
        raise HTTPException(status_code=500, detail="Failed to create scan record")

    # 8. Dispatch the heavy analysis work to a background task so we can return a response immediately
    background_tasks.add_task(perform_simulated_scan, scan_id)

    # 9. Return the scan ID so the frontend can start polling for updates
    return {"status": "success", "scan_id": scan_id}


@router.get("/api/github/scan/{repository_id}/latest")
def get_latest_scan(repository_id: str, authorization: str | None = Header(default=None)):
    # 1. Validate authentication token
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    access_token = authorization.split(" ", 1)[1].strip()

    # 2. Extract workspace ID
    workspace_id = _workspace_id_for_user(access_token)
    headers = {
        "Authorization": f"Bearer {supabase_service_role_key()}",
        "apikey": supabase_service_role_key(),
    }

    # 3. Query the database for the most recent scan belonging to this repository
    status, body = _json_request(
        f"{supabase_url()}/rest/v1/scans?repository_id=eq.{repository_id}&workspace_id=eq.{workspace_id}&order=started_at.desc&limit=1",
        headers
    )
    
    # If no scans exist, return early
    if status != 200 or not isinstance(body, list) or len(body) == 0:
        return {"scan": None, "findings": []}
        
    latest_scan = body[0]
    scan_id = latest_scan["id"]
    
    findings = []
    # 4. If the scan has finished running, fetch all associated findings from the scan_findings table
    if latest_scan["status"] == "completed":
        status, body = _json_request(
            f"{supabase_url()}/rest/v1/scan_findings?scan_id=eq.{scan_id}",
            headers
        )
        if status == 200 and isinstance(body, list):
            findings = body

    # 5. Return both the scan metadata and its findings
    return {
        "scan": latest_scan,
        "findings": findings
    }

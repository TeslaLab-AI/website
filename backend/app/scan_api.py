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
from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, Header, HTTPException, BackgroundTasks
from pydantic import BaseModel

from app.config import supabase_url, supabase_service_role_key
from app.github_api import _json_post, _json_request, get_workspace_installation, get_installation_token
from app.github_install import _authenticated_user_id, _workspace_id_for_user
from app.ingestion.github_downloader import download_and_extract_repo
from app.ingestion.file_discovery import discover_files, chunk_file_content
from app.ingestion.embeddings import generate_embeddings
from app.analysis.semgrep_runner import run_semgrep
from app.analysis.dependency_analyzer import analyze_dependencies

router = APIRouter()

# Global dict to track live scan progress
# scan_progress_state[scan_id] = {
#     "phase": "initializing", # initializing, ingesting, analyzing, finalizing, completed, failed
#     "progress": 0, # 0-100
#     "logs": [{"timestamp": "...", "message": "..."}],
# }
scan_progress_state: Dict[str, Any] = {}

def update_progress(scan_id: str, phase: str, progress: int, message: str):
    """Helper to update the in-memory scan progress and keep a rolling log of messages."""
    if scan_id not in scan_progress_state:
        scan_progress_state[scan_id] = {
            "phase": "initializing",
            "progress": 0,
            "logs": []
        }
    
    state = scan_progress_state[scan_id]
    state["phase"] = phase
    state["progress"] = progress
    
    # Add new log entry
    timestamp = datetime.utcnow().isoformat() + "Z"
    state["logs"].append({"timestamp": timestamp, "message": message})
    
    # Keep only the last 100 logs to prevent memory bloat
    if len(state["logs"]) > 100:
        state["logs"] = state["logs"][-100:]
    
    # Also print to stdout for backend visibility
    print(f"[Scan {scan_id[:8]}] {message}")


def perform_real_scan(scan_id: str, repository_id: str, workspace_id: str, owner: str, repo: str, branch: str, token: str):
    """
    Real ingestion pipeline:
    1. Download repo tarball
    2. Discover files (respecting .gitignore)
    3. Chunk files
    4. Generate embeddings for chunks
    5. Save to pgvector
    """
    headers = {
        "Authorization": f"Bearer {supabase_service_role_key()}",
        "apikey": supabase_service_role_key(),
    }
    
    try:
        # Phase 1: Ingestion
        update_progress(scan_id, "ingesting", 10, f"Downloading repository tarball for {owner}/{repo} @ {branch}...")
        repo_root = download_and_extract_repo(owner, repo, token, branch)
        
        update_progress(scan_id, "ingesting", 20, "Discovering source code files...")
        files = discover_files(repo_root)
        
        update_progress(scan_id, "ingesting", 30, f"Found {len(files)} files. Chunking content...")
        all_chunks = []
        for f in files:
            chunks = chunk_file_content(f)
            # Add file path to each chunk
            for c in chunks:
                c["file_path"] = f.replace(repo_root, "").lstrip("/\\")
            all_chunks.extend(chunks)
            
        update_progress(scan_id, "ingesting", 40, f"Discovered {len(files)} files, produced {len(all_chunks)} chunks.")
        
        # Phase 3: Embeddings & Storage (renaming to Analyzing phase for UI simplicity)
        if all_chunks:
            texts = [c["content"] for c in all_chunks]
            update_progress(scan_id, "analyzing", 50, "Generating AI embeddings for code chunks...")
            embeddings = generate_embeddings(texts)
            
            update_progress(scan_id, "analyzing", 60, "Saving snapshot and chunks to vector database...")
            # 1. Create snapshot
            # For this simple implementation, we just use the branch name as the commit_sha placeholder
            # A more advanced version would use the GitHub API to get the latest commit SHA for the branch.
            commit_sha = f"{branch}-latest"
            snapshot_id = str(uuid.uuid4())
            _json_post(
                f"{supabase_url()}/rest/v1/repository_snapshots?on_conflict=repository_id,commit_sha",
                headers,
                payload={
                    "id": snapshot_id,
                    "repository_id": repository_id,
                    "workspace_id": workspace_id,
                    "commit_sha": commit_sha
                }
            )
            
            # 2. Insert chunks
            for chunk, emb in zip(all_chunks, embeddings):
                _json_post(
                    f"{supabase_url()}/rest/v1/code_chunks",
                    headers,
                    payload={
                        "snapshot_id": snapshot_id,
                        "file_path": chunk["file_path"],
                        "content": chunk["content"],
                        "language": chunk["language"],
                        "embedding": emb
                    }
                )
                
        # Phase 2: Static & Dependency Analysis
        update_progress(scan_id, "analyzing", 75, "Running static code analysis (Semgrep)...")
        semgrep_findings = run_semgrep(repo_root)
        
        update_progress(scan_id, "analyzing", 85, "Running dependency vulnerability analysis...")
        dependency_findings = analyze_dependencies(repo_root)
        
        all_findings = semgrep_findings + dependency_findings
        
        # Ensure we always have at least one finding to show the scan completed
        if not all_findings:
            all_findings = [
                {"category": "testing", "severity": "low", "title": "Scan Completed", "description": f"Successfully ingested {len(files)} files and found 0 critical issues.", "file_path": "N/A", "line_number": 0},
            ]
            
        update_progress(scan_id, "finalizing", 95, f"Generated {len(all_findings)} total findings. Persisting to database...")
            
        for finding in all_findings:
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
        update_progress(scan_id, "completed", 100, "Scan completed successfully.")
        patch_headers = {**headers, "Content-Type": "application/json"}
        _json_request(
            f"{supabase_url()}/rest/v1/scans?id=eq.{scan_id}",
            patch_headers,
            method="PATCH",
            data=json.dumps({"status": "completed", "completed_at": "now()"}).encode("utf-8")
        )
        
    except Exception as e:
        error_msg = str(e)
        update_progress(scan_id, "failed", 100, f"Error during scan: {error_msg}")
        patch_headers = {**headers, "Content-Type": "application/json"}
        _json_request(
            f"{supabase_url()}/rest/v1/scans?id=eq.{scan_id}",
            patch_headers,
            method="PATCH",
            data=json.dumps({"status": "failed", "completed_at": "now()"}).encode("utf-8")
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
        f"{supabase_url()}/rest/v1/repositories?id=eq.{request.repository_id}&workspace_id=eq.{workspace_id}&select=*",
        headers
    )
    if status != 200 or not isinstance(body, list) or len(body) == 0:
        raise HTTPException(status_code=404, detail="Repository not found in workspace")
        
    repo = body[0]
    owner = repo["owner"]
    name = repo["name"]
    branch = repo["default_branch"]
    
    # 5b. Get installation token
    installation = get_workspace_installation(workspace_id)
    if not installation:
        raise HTTPException(status_code=400, detail="No GitHub installation found")
        
    token = get_installation_token(installation["github_installation_id"])

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
    # Initialize the progress state immediately before returning
    update_progress(scan_id, "initializing", 5, f"Initializing scan for {owner}/{name} on branch {branch}...")
    background_tasks.add_task(perform_real_scan, scan_id, request.repository_id, workspace_id, owner, name, branch, token)

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


@router.get("/api/github/scan/{scan_id}/progress")
def get_scan_progress(scan_id: str, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
        
    if scan_id not in scan_progress_state:
        # Wait a moment for initialization or it might be a stale request
        return {
            "phase": "unknown",
            "progress": 0,
            "logs": [{"timestamp": datetime.utcnow().isoformat() + "Z", "message": "Waiting for scan to initialize or scan not found in current session..."}]
        }
        
    return scan_progress_state[scan_id]

from fastapi import APIRouter, Header, HTTPException, BackgroundTasks
from pydantic import BaseModel
import openai
import base64
import uuid
import json

from app.config import supabase_url, supabase_service_role_key
from app.github_api import _json_request, _json_post, get_workspace_installation, get_installation_token
from app.github_install import _workspace_id_for_user
from app.agents.agent_1 import pipeline_event_bus as event_bus
from app.agents.pipeline import run_pipeline

router = APIRouter()
client = openai.OpenAI()

class FixRequest(BaseModel):
    repository_id: str
    finding_id: str

class FixResponse(BaseModel):
    pr_url: str
    explanation: str

from typing import Any

def _github_request(url: str, token: str, method: str = "GET", payload: dict | None = None) -> tuple[int, Any]:
    import urllib.request
    import urllib.error
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TeslaLab-Security-Scanner"
    }
    
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        
    req = urllib.request.Request(url, headers=headers, method=method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        try:
            body = error.read().decode("utf-8")
            return error.code, json.loads(body) if body else None
        except Exception as e:
            print(f"[_github_request] Failed to parse HTTPError body for {url.split('?')[0]}: {e}")
            return error.code, None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"[_github_request] Network/JSON error for {url.split('?')[0]}: {e}")
        return 503, None
    except Exception as e:
        print(f"[_github_request] Unexpected error for {url.split('?')[0]}: {e}")
        return 500, None

@router.post("/api/github/fix", response_model=FixResponse)
def generate_pr_fix(request: FixRequest, authorization: str | None = Header(default=None)):
    # 1. Auth & Validation
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    access_token = authorization.split(" ", 1)[1].strip()
    workspace_id = _workspace_id_for_user(access_token)

    db_headers = {
        "Authorization": f"Bearer {supabase_service_role_key()}",
        "apikey": supabase_service_role_key(),
    }
    
    # 2. Get Repository info
    r_status, r_body = _json_request(
        f"{supabase_url()}/rest/v1/repositories?id=eq.{request.repository_id}&workspace_id=eq.{workspace_id}",
        db_headers
    )
    if r_status != 200 or not isinstance(r_body, list) or len(r_body) == 0 or not isinstance(r_body[0], dict):
        raise HTTPException(status_code=404, detail="Repository not found")
    repo = r_body[0]
    owner, name, default_branch = repo["owner"], repo["name"], repo["default_branch"]

    # 3. Get Finding info
    f_status, f_body = _json_request(
        f"{supabase_url()}/rest/v1/scan_findings?id=eq.{request.finding_id}",
        db_headers
    )
    if f_status != 200 or not isinstance(f_body, list) or len(f_body) == 0 or not isinstance(f_body[0], dict):
        raise HTTPException(status_code=404, detail="Finding not found")
    finding = f_body[0]
    file_path = finding.get("file_path")
    if not file_path or str(file_path).strip().lower() in ("", "n/a", "null", "none"):
        raise HTTPException(status_code=400, detail="This finding is not fixable because it has no valid source file.")

    # 4. Get GitHub Installation Token with explicit write permissions for fix operations
    installation = get_workspace_installation(workspace_id)
    if not installation:
        raise HTTPException(status_code=400, detail="No GitHub installation found")
    token = get_installation_token(installation["github_installation_id"])

    # 5. Fetch File from GitHub
    c_status, c_body = _github_request(f"https://api.github.com/repos/{owner}/{name}/contents/{file_path}", token)
    if c_status != 200 or not isinstance(c_body, dict) or "content" not in c_body:
        raise HTTPException(status_code=404, detail=f"File {file_path} not found on GitHub")
    
    original_content = base64.b64decode(c_body["content"]).decode("utf-8")
    blob_sha = c_body["sha"]

    # 6. Ask OpenAI for the fix
    system_prompt = (
        "You are an expert Security Engineer. I will provide you with a source file that contains a bug or vulnerability. "
        "I will also provide the scanner's finding details. "
        "You must output a JSON object containing two fields:\n"
        "1. 'explanation': A short markdown string explaining what was fixed.\n"
        "2. 'fixed_code': The ENTIRE file content with the bug fixed. DO NOT truncate the file or use placeholders like '...rest of code...'. Return the complete, runnable file content."
    )
    
    user_prompt = f"""
Scanner Finding: {finding['title']}
Severity: {finding['severity']}
Line: {finding['line_number']}
Description: {finding['description']}

Original File Content ({file_path}):
{original_content}
"""

    try:
        chat_res = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )
        ai_response = json.loads(chat_res.choices[0].message.content or "{}")
        explanation = ai_response.get("explanation", "Automated fix generated by AI.")
        fixed_code = ai_response.get("fixed_code", original_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate fix via AI: {str(e)}")

    if fixed_code.strip() == original_content.strip():
        with open("fix_debug.json", "w") as f:
            json.dump({
                "original": original_content,
                "ai_returned": fixed_code,
                "full_ai_response": chat_res.choices[0].message.content
            }, f)
        raise HTTPException(status_code=400, detail="AI could not determine a fix for this file.")

    try:
        # 7. Create a new branch
        branch_name = f"teslalab-fix-{uuid.uuid4().hex[:8]}"
        
        # Get latest commit of default branch
        ref_status, ref_body = _github_request(f"https://api.github.com/repos/{owner}/{name}/git/ref/heads/{default_branch}", token)
        if ref_status != 200 or not isinstance(ref_body, dict) or "object" not in ref_body:
            raise HTTPException(status_code=500, detail=f"Failed to get default branch ref. Status: {ref_status}")
        base_sha = ref_body["object"]["sha"]
        
        # Create the branch
        b_status, b_body = _github_request(
            f"https://api.github.com/repos/{owner}/{name}/git/refs", 
            token, 
            method="POST", 
            payload={"ref": f"refs/heads/{branch_name}", "sha": base_sha}
        )
        if b_status != 201:
            raise HTTPException(status_code=500, detail=f"Failed to create new branch. Status: {b_status}, Body: {b_body}")

        # 8. Update the file on the new branch
        update_payload = {
            "message": f"Fix: {finding['title']}",
            "content": base64.b64encode(fixed_code.encode("utf-8")).decode("utf-8"),
            "sha": blob_sha,
            "branch": branch_name
        }
        u_status, u_body = _github_request(
            f"https://api.github.com/repos/{owner}/{name}/contents/{file_path}", 
            token, 
            method="PUT", 
            payload=update_payload
        )
        if u_status not in (200, 201):
            raise HTTPException(status_code=500, detail=f"Failed to commit the fix to the new branch. Status: {u_status}, Body: {u_body}")

        # 9. Create a Pull Request
        pr_payload = {
            "title": f"\U0001f6e0\ufe0f Security Fix: {finding['title']}",
            "head": branch_name,
            "base": default_branch,
            "body": f"### Automated Fix by TeslaLab AI Scanner\n\n**Issue**: {finding['title']}\n**Severity**: {finding['severity'].upper()}\n**File**: `{file_path}`\n\n**AI Explanation**:\n{explanation}"
        }
        p_status, p_body = _github_request(
            f"https://api.github.com/repos/{owner}/{name}/pulls", 
            token, 
            method="POST", 
            payload=pr_payload
        )

        if p_status == 403:
            compare_url = f"https://github.com/{owner}/{name}/compare/{default_branch}...{branch_name}?expand=1"
            github_msg = p_body.get("message", "Resource not accessible by integration")
            raise HTTPException(
                status_code=403,
                detail=f"Fix committed to branch '{branch_name}', but GitHub denied PR creation (403): {github_msg}. Open PR: {compare_url} or enable 'Pull requests: Read and write' in App settings."
            )

        # 422 means a PR already exists for this head/base — fetch it and return it
        if p_status == 422:
            list_status, list_body = _github_request(
                f"https://api.github.com/repos/{owner}/{name}/pulls?head={owner}:{branch_name}&base={default_branch}&state=open",
                token
            )
            if list_status == 200 and isinstance(list_body, list) and len(list_body) > 0:
                return FixResponse(
                    pr_url=list_body[0]["html_url"],
                    explanation=explanation
                )
            raise HTTPException(status_code=500, detail=f"Failed to create Pull Request. Status: {p_status}, Body: {p_body}")

        if p_status != 201 or "html_url" not in p_body:
            raise HTTPException(status_code=500, detail=f"Failed to create Pull Request. Status: {p_status}, Body: {p_body}")

        return FixResponse(
            pr_url=p_body["html_url"],
            explanation=explanation
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        with open("fix_500.log", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        raise e


# ─────────────────────────────────────────────────────────────
# Agentic Fix Pipeline endpoints
# ─────────────────────────────────────────────────────────────

class AgenticFixRequest(BaseModel):
    repository_id: str
    finding_id: str


@router.post("/api/github/fix/agentic")
def start_agentic_fix(
    request: AgenticFixRequest,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
):
    """Start the multi-agent fix pipeline. Returns a run_id to poll for progress."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    access_token = authorization.split(" ", 1)[1].strip()
    workspace_id = _workspace_id_for_user(access_token)

    db_headers = {
        "Authorization": f"Bearer {supabase_service_role_key()}",
        "apikey": supabase_service_role_key(),
    }

    # Validate repository ownership
    r_status, r_body = _json_request(
        f"{supabase_url()}/rest/v1/repositories?id=eq.{request.repository_id}&workspace_id=eq.{workspace_id}",
        db_headers,
    )
    if r_status != 200 or not isinstance(r_body, list) or len(r_body) == 0 or not isinstance(r_body[0], dict):
        raise HTTPException(status_code=404, detail="Repository not found")
    repo = r_body[0]

    # Validate finding exists
    f_status, f_body = _json_request(
        f"{supabase_url()}/rest/v1/scan_findings?id=eq.{request.finding_id}",
        db_headers,
    )
    if f_status != 200 or not isinstance(f_body, list) or len(f_body) == 0 or not isinstance(f_body[0], dict):
        raise HTTPException(status_code=404, detail="Finding not found")
    finding = f_body[0]
    file_path = finding.get("file_path")
    if not file_path or str(file_path).strip().lower() in ("", "n/a", "null", "none"):
        raise HTTPException(status_code=400, detail="This finding is not fixable because it has no valid source file.")

    run_id = str(uuid.uuid4())
    event_bus.init_run(run_id, request.finding_id, request.repository_id)

    background_tasks.add_task(run_pipeline, run_id, finding, repo, workspace_id)

    return {"run_id": run_id, "status": "started"}


@router.get("/api/github/fix/agentic/{run_id}")
def get_agentic_fix_status(run_id: str, authorization: str | None = Header(default=None)):
    """Poll the current state of an agentic fix run."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    state = event_bus.get_run(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")

    return state

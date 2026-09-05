from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import openai
from typing import List, Dict, Any

from app.config import supabase_url, supabase_service_role_key
from app.github_api import _json_request, _json_post
from app.github_install import _workspace_id_for_user

router = APIRouter()
client = openai.OpenAI()

class ChatRequest(BaseModel):
    repository_id: str
    message: str

class ChatResponse(BaseModel):
    reply: str
    references: List[Dict[str, str]]

@router.post("/api/github/chat", response_model=ChatResponse)
def chat_with_repo(request: ChatRequest, authorization: str | None = Header(default=None)):
    # 1. Validate auth
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    access_token = authorization.split(" ", 1)[1].strip()
    workspace_id = _workspace_id_for_user(access_token)

    headers = {
        "Authorization": f"Bearer {supabase_service_role_key()}",
        "apikey": supabase_service_role_key(),
    }
    
    # 2. Verify repository belongs to workspace
    status, body = _json_request(
        f"{supabase_url()}/rest/v1/repositories?id=eq.{request.repository_id}&workspace_id=eq.{workspace_id}&select=*",
        headers
    )
    if status != 200 or not isinstance(body, list) or len(body) == 0:
        raise HTTPException(status_code=404, detail="Repository not found in workspace")

    # 3. Generate embedding for the user's query
    try:
        embed_res = client.embeddings.create(
            input=[request.message],
            model="text-embedding-3-small"
        )
        query_embedding = embed_res.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate embedding: {str(e)}")

    # 4. Search Supabase via RPC for Code Context
    status, chunks = _json_post(
        f"{supabase_url()}/rest/v1/rpc/match_code_chunks",
        headers,
        payload={
            "query_embedding": query_embedding,
            "match_threshold": 0.2, # Adjust based on sensitivity
            "match_count": 5,       # Get top 5 most relevant semantic chunks
            "p_repository_id": request.repository_id
        }
    )
    
    if status != 200 or not isinstance(chunks, list):
        raise HTTPException(status_code=500, detail=f"Supabase RPC search failed: {chunks}")

    # 4.5 Fetch Latest Scan Findings (Semgrep/Dependencies)
    findings_text = ""
    # Get latest completed scan
    s_status, scans = _json_request(
        f"{supabase_url()}/rest/v1/scans?repository_id=eq.{request.repository_id}&status=eq.completed&order=started_at.desc&limit=1",
        headers
    )
    if s_status == 200 and isinstance(scans, list) and len(scans) > 0:
        latest_scan_id = scans[0]["id"]
        # Get findings for this scan
        f_status, findings = _json_request(
            f"{supabase_url()}/rest/v1/scan_findings?scan_id=eq.{latest_scan_id}",
            headers
        )
        if f_status == 200 and isinstance(findings, list) and len(findings) > 0:
            findings_text = "\n\n--- SECURITY & BUG FINDINGS (from Semgrep/Scanner) ---\n"
            for f in findings:
                findings_text += f"- [{f['severity'].upper()}] {f['title']} in {f['file_path']}:{f['line_number']} - {f['description']}\n"

    # 5. Build context for the LLM
    context_text = ""
    references = []
    
    for i, chunk in enumerate(chunks):
        file_path = chunk.get("file_path", "unknown")
        content = chunk.get("content", "")
        # Add to prompt context
        context_text += f"\n\n--- File: {file_path} (Snippet {i+1}) ---\n"
        context_text += content
        
        # Keep track of unique references to show to the user
        if not any(r["file_path"] == file_path for r in references):
            references.append({"file_path": file_path})

    # 6. Call LLM (gpt-4o-mini)
    system_prompt = (
        "You are an expert Code Intelligence AI and Security Scanner Assistant. "
        "You help developers understand their codebase AND the security vulnerabilities found in it. "
        "Use the provided code context snippets and security findings to answer the user's question accurately. "
        "If the user asks about issues, bugs, or vulnerabilities, prioritize reading the SECURITY & BUG FINDINGS. "
        "If the answer cannot be found in the context or findings, say so gracefully. "
        "Format code snippets in markdown."
    )
    
    user_prompt = f"User Question:\n{request.message}\n\nRepository Context:{context_text}{findings_text}"
    
    try:
        chat_res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3
        )
        reply = chat_res.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate AI reply: {str(e)}")

    # 7. Return the reply and references
    return ChatResponse(
        reply=reply,
        references=references
    )

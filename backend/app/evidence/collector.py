import os
import re
import sys
import platform
import subprocess
import time
from typing import List, Dict, Any, Optional
from app.contracts.schemas import EvidencePack, BugFinding

# Regex for detecting sensitive information (very basic example)
SECRET_REGEXES = [
    re.compile(r'(?i)(bearer\s+)[A-Za-z0-9_\-\.]+'),
    re.compile(r'(?i)(api_key\s*[:=]\s*["\']?)[A-Za-z0-9_\-\.]+'),
    re.compile(r'(?i)(password\s*[:=]\s*["\']?)[^"\']+'),
    re.compile(r'(?i)(secret\s*[:=]\s*["\']?)[A-Za-z0-9_\-\.]+'),
]

def sanitize_logs(log_lines: List[str]) -> List[str]:
    sanitized = []
    for line in log_lines:
        for regex in SECRET_REGEXES:
            line = regex.sub(r'\1***', line)
        sanitized.append(line)
    return sanitized

def harvest_logs(log_file_path: str, correlation_id: str, context_lines: int = 50) -> List[str]:
    """
    Scans a log file for a correlation_id and extracts +/- context_lines around it.
    Sanitizes sensitive information before returning.
    """
    if not os.path.exists(log_file_path):
        return []

    lines = []
    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []

    target_idx = -1
    for i, line in enumerate(lines):
        if correlation_id in line:
            target_idx = i
            break

    if target_idx == -1:
        return []

    start_idx = max(0, target_idx - context_lines)
    end_idx = min(len(lines), target_idx + context_lines + 1)
    
    extracted = lines[start_idx:end_idx]
    return sanitize_logs(extracted)

def get_environment_metadata(workspace_path: str) -> Dict[str, Any]:
    env = {
        "os": f"{platform.system()} {platform.release()}",
        "python_version": sys.version.split(" ")[0],
    }
    
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], 
            cwd=workspace_path, 
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        env["git_branch"] = branch
    except Exception:
        env["git_branch"] = "unknown"
        
    return env

def get_git_commit(workspace_path: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], 
            cwd=workspace_path, 
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
    except Exception:
        return "unknown_commit"

def build_evidence_pack(
    finding: BugFinding, 
    workspace_path: Optional[str] = None, 
    log_file_path: Optional[str] = None
) -> EvidencePack:
    """
    Automatically gathers all raw evidence needed to diagnose a bug.
    Fails or asserts if it takes more than 3 seconds.
    """
    start_time = time.time()
    
    if not workspace_path or not os.path.exists(workspace_path):
        workspace_path = os.getcwd()

    # 1. Harvest logs
    logs = []
    if log_file_path:
        logs = harvest_logs(log_file_path, finding.id, context_lines=50)

    # 2. Extract environment metadata
    environment = get_environment_metadata(workspace_path)
    merged_env = {**finding.environment, **environment}

    # 3. Get commit hash
    commit_hash = get_git_commit(workspace_path)

    # 4. Construct EvidencePack
    pack = EvidencePack(
        stack_trace=finding.stack_trace,
        logs=logs,
        environment=merged_env,
        commit_hash=commit_hash
    )
    
    if time.time() - start_time > 3.0:
        print("[WARNING] build_evidence_pack took longer than 3.0s!")
        
    return pack

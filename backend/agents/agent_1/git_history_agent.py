import os
import subprocess
import logging
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from app.contracts.schemas import GitContext
from app.agents.agent_2.router.router import default_router

logger = logging.getLogger(__name__)

class IntentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(..., description="A 1-sentence summary of the original developer intent based on the commit message and diff.")

class GitHistoryAgent:
    """
    Agent 1 (Diagnosis) - Git History Intelligence.
    Extracts git blame information for culprit lines and infers original intent.
    """
    
    def __init__(self, temperature: float = 0.0):
        self.temperature = temperature

    def run(self, file_path: str, line_number: int, workspace_path: str) -> Optional[GitContext]:
        """
        Executes git blame, fetches the commit, and summarizes intent.
        """
        logger.info(f"Running Git History Intelligence on {file_path}:{line_number} in {workspace_path}")
        
        try:
            # Step 1: Run git blame
            blame_cmd = ["git", "blame", "-L", f"{line_number},{line_number}", "--porcelain", file_path]
            blame_res = subprocess.run(blame_cmd, cwd=workspace_path, capture_output=True, text=True, check=True)
            blame_lines = blame_res.stdout.strip().split("\n")
            
            if not blame_lines:
                logger.warning("No blame output found.")
                return None
                
            # Parse porcelain output
            commit_hash = blame_lines[0].split()[0]
            
            # If the code is uncommitted (00000000...)
            if commit_hash.startswith("00000000"):
                return GitContext(
                    introducing_commit="Uncommitted",
                    author="Local Changes",
                    date="Now",
                    commit_message="Uncommitted working tree changes.",
                    original_intent_summary="Code has not been committed yet, likely an ongoing local modification."
                )

            author = "Unknown"
            date = "Unknown"
            summary_msg = ""
            
            for line in blame_lines[1:]:
                if line.startswith("author "):
                    author = line.split(" ", 1)[1]
                elif line.startswith("summary "):
                    summary_msg = line.split(" ", 1)[1]

            # Step 2: Run git show to get date and full diff
            show_meta_cmd = ["git", "show", "-s", "--format=%ai", commit_hash]
            show_meta_res = subprocess.run(show_meta_cmd, cwd=workspace_path, capture_output=True, text=True, check=True)
            date = show_meta_res.stdout.strip()
            
            show_diff_cmd = ["git", "show", commit_hash]
            show_diff_res = subprocess.run(show_diff_cmd, cwd=workspace_path, capture_output=True, text=True, check=True)
            diff_text = show_diff_res.stdout.strip()
            
            # Step 3: Summarize Intent using Model Router
            system_prompt = (
                "You are an expert software archeologist. "
                "Your objective is to read a git commit (message and diff) and summarize the original intent of the developer. "
                "You must output exactly ONE sentence."
            )
            
            user_prompt = f"Commit Hash: {commit_hash}\nMessage: {summary_msg}\n\nDiff:\n{diff_text[:3000]}" # truncate diff if too large
            
            response = default_router.complete(
                task_type="diagnosis",  # Using generic or existing task type mapped in router
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                json_schema=IntentSummary,
                session_id="git-history",
            )
            
            if response.parsed:
                if isinstance(response.parsed, dict):
                    intent_summary = response.parsed.get("summary", "Failed to parse intent.")
                else:
                    intent_summary = getattr(response.parsed, "summary", "Failed to parse intent.")
            else:
                intent_summary = "Failed to parse intent."
            
            # Step 4: Return GitContext
            return GitContext(
                introducing_commit=commit_hash,
                author=author,
                date=date,
                commit_message=summary_msg,
                original_intent_summary=intent_summary
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Git command failed: {e.stderr}")
            return None
        except Exception as e:
            logger.error(f"Failed to extract Git context: {e}")
            return None

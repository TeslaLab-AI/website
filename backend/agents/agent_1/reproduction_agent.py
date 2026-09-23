import os
import uuid
import logging
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from app.contracts.schemas import BugFinding, RootCauseAnalysis, ReproductionResult
from app.agents.agent_2.router.router import default_router
from app.agents.agent_2.sandbox import SubprocessFallbackSandbox

logger = logging.getLogger(__name__)

class TestScript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script_code: str = Field(..., description="The complete, executable pytest script.")

class ReproductionAgent:
    """
    Agent 1 (Diagnosis) - Reproduction Engine.
    Generates a minimal failing test case and verifies it in the sandbox.
    """
    
    def __init__(self, workspace_path: str, temperature: float = 0.0):
        self.workspace_path = workspace_path
        self.temperature = temperature

    def run(self, finding: BugFinding, rca: RootCauseAnalysis) -> Optional[ReproductionResult]:
        """
        Generates and verifies a reproduction test.
        """
        logger.info(f"Running Reproduction Engine for {finding.id} on {rca.file_path}")
        
        # Step 1: Generate the test script
        system_prompt = (
            "You are an expert Python SDET (Software Development Engineer in Test). "
            "Write a minimal, standalone `pytest` test script that reproduces the bug described below. "
            "The test MUST import the target file and execute the function/class to trigger the exact failure. "
            "Do NOT fix the bug in the test. The test MUST fail on the current buggy code. "
            "CRITICAL INSTRUCTION: Do NOT use `pytest.raises` or try/except blocks! "
            "The test must naturally crash and exit with a non-zero exit code due to the unhandled exception. "
            "Include all necessary imports and mock any external network calls if necessary."
        )
        
        user_prompt = f"Bug Finding:\n{finding.model_dump_json(indent=2)}\n\nRoot Cause Analysis:\n{rca.model_dump_json(indent=2)}"
        
        response = default_router.complete(
            task_type="diagnosis",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=self.temperature,
            json_schema=TestScript,
            session_id=finding.id,
        )
        
        if not response.parsed:
            logger.error("Failed to parse TestScript from LLM.")
            return None
            
        script_code = getattr(response.parsed, "script_code", None)
        if not script_code and isinstance(response.parsed, dict):
            script_code = response.parsed.get("script_code")
            
        if not script_code:
            logger.error("No script code generated.")
            return None

        # Step 2: Write to a unique file in the workspace
        test_filename = f"test_repro_{uuid.uuid4().hex[:8]}.py"
        test_filepath = os.path.join(self.workspace_path, test_filename)
        
        try:
            with open(test_filepath, "w", encoding="utf-8") as f:
                f.write(script_code)
                
            # Step 3: Execute in Sandbox
            sandbox = SubprocessFallbackSandbox()
            # Run pytest on the generated file using python -m pytest so current directory is in sys.path automatically
            import sys
            python_exe = sys.executable
            cmd = f'"{python_exe}" -m pytest {test_filename}'
            result = sandbox.execute_command(cmd=cmd, cwd=self.workspace_path, timeout=30)
            
            # Step 4: Verify Failure
            # Pytest returns 1 if tests failed (which is what we want for a reproduction test on buggy code)
            # It returns 0 if they pass (which means it didn't reproduce the bug)
            # It returns > 1 for internal errors
            
            # We want exit code to be 1 (test failed). If it is 1, it's a verified failure.
            is_verified_failure = (result.exit_code == 1)
            
            log_output = f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            
            logger.info(f"Reproduction test executed. Exit code: {result.exit_code}. Verified failure: {is_verified_failure}")
            
            return ReproductionResult(
                script_code=script_code,
                execution_log=log_output,
                exit_code=result.exit_code,
                is_verified_failure=is_verified_failure
            )
            
        except Exception as e:
            logger.error(f"Sandbox execution failed: {e}")
            return None
            
        finally:
            # Cleanup the temp test file
            if os.path.exists(test_filepath):
                try:
                    os.remove(test_filepath)
                except:
                    pass

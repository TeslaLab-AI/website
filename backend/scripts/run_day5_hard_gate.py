import os
import sys
import tempfile
import json
import logging
from typing import List, Dict, Any

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.agent_1.session_engine import create_session_graph
from app.contracts.schemas import SessionState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hard_gate")

import subprocess

def setup_workspace(tmp_dir: str):
    """Writes 5 distinct buggy files into the workspace and initializes git."""
    
    # Bug 1: DivByZero
    with open(os.path.join(tmp_dir, "bug1_math.py"), "w") as f:
        f.write("def calculate_ratio(a, b):\n    return a / b\n")
        
    # Bug 2: KeyError
    with open(os.path.join(tmp_dir, "bug2_parser.py"), "w") as f:
        f.write("def parse_payload(payload):\n    return payload['data']['user_id']\n")

    # Bug 3: TypeError
    with open(os.path.join(tmp_dir, "bug3_formatter.py"), "w") as f:
        f.write("def format_greeting(name, age):\n    return 'Hello ' + name + ', you are ' + age + ' years old'\n")

    # Bug 4: Concurrency Mock (Raises error explicitly)
    with open(os.path.join(tmp_dir, "bug4_async.py"), "w") as f:
        f.write("import time\ndef process_concurrently():\n    time.sleep(0.1)\n    raise RuntimeError('Race condition state corruption')\n")

    # Bug 5: IndexError (Data issue)
    with open(os.path.join(tmp_dir, "bug5_data.py"), "w") as f:
        f.write("def get_last_element(arr):\n    return arr[len(arr)]\n")
        
    # Initialize git repo and commit so GitHistoryAgent can run git blame
    subprocess.run(["git", "init"], cwd=tmp_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_dir, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial buggy commit"], cwd=tmp_dir, check=True)

def get_benchmarks(tmp_dir: str) -> List[Dict[str, Any]]:
    return [
        {
            "id": "bug-01",
            "title": "Division by zero in calculate_ratio",
            "description": "Calling calculate_ratio(10, 0) throws ZeroDivisionError.",
            "files_hint": ["bug1_math.py"],
            "environment": {}
        },
        {
            "id": "bug-02",
            "title": "KeyError in parse_payload",
            "description": "Calling parse_payload({'data': {}}) throws KeyError.",
            "files_hint": ["bug2_parser.py"],
            "environment": {}
        },
        {
            "id": "bug-03",
            "title": "TypeError in format_greeting",
            "description": "Calling format_greeting('Alice', 30) throws TypeError.",
            "files_hint": ["bug3_formatter.py"],
            "environment": {}
        },
        {
            "id": "bug-04",
            "title": "Concurrency RuntimeError in process_concurrently",
            "description": "Calling process_concurrently() crashes with RuntimeError.",
            "files_hint": ["bug4_async.py"],
            "environment": {}
        },
        {
            "id": "bug-05",
            "title": "IndexError in get_last_element",
            "description": "Calling get_last_element([1, 2, 3]) throws IndexError.",
            "files_hint": ["bug5_data.py"],
            "environment": {}
        }
    ]

def mock_triage(*args, **kwargs):
    from app.contracts.schemas import TriageReport, TriageSeverity
    return TriageReport(
        is_reproducible=True,
        subsystem="core",
        severity=TriageSeverity.P1,
        estimated_complexity="low",
        auto_fix_feasible=True,
        reason="Mocked for evaluation to ensure progression."
    )

def run_evaluation():
    from agents.agent_1.triage_agent import TriageAgent
    TriageAgent.run_triage = mock_triage
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        setup_workspace(tmp_dir)
        benchmarks = get_benchmarks(tmp_dir)
        
        graph = create_session_graph()
        if not graph:
            logger.error("Failed to compile SessionGraph")
            sys.exit(1)
            
        results = []
        passed = 0
        
        for idx, finding in enumerate(benchmarks):
            logger.info(f"\n{'='*50}\nStarting Benchmark {idx+1}/5: {finding['title']}\n{'='*50}")
            
            initial_state = {
                "session_id": finding["id"],
                "task_id": "task-eval",
                "workspace_id": tmp_dir, # Use tmp_dir as workspace so git/sandbox runs there
                "current_state": SessionState.CREATED.value,
                "history": [],
                "bug_finding": finding,
                "evidence_pack": {"commit_hash": "HEAD"}
            }
            
            final_state = None
            try:
                # Stream the state transitions
                for output in graph.stream(initial_state, {"recursion_limit": 20}):
                    for node_name, state in output.items():
                        logger.info(f"Transitioned to state: {state.get('current_state')} (Node: {node_name})")
                        final_state = state
                        
                        # Stop if we reach PLANNING or NEEDS_HUMAN
                        if state.get("current_state") in [SessionState.PLANNING.value, SessionState.NEEDS_HUMAN.value]:
                            break
                    if final_state and final_state.get("current_state") in [SessionState.PLANNING.value, SessionState.NEEDS_HUMAN.value]:
                        break
            except Exception as e:
                logger.error(f"Pipeline crashed for {finding['id']}: {e}")
                
            
            # Evaluate
            is_success = False
            repro_result = final_state.get("reproduction_result") if final_state else None
            
            if repro_result and repro_result.get("is_verified_failure"):
                is_success = True
                passed += 1
                logger.info(f"✅ PASS: {finding['id']} correctly generated verified reproduction.")
            else:
                logger.error(f"❌ FAIL: {finding['id']} failed to generate verified reproduction.")
                if repro_result:
                    logger.error(f"Exit code: {repro_result.get('exit_code')}")
                
            results.append({
                "id": finding["id"],
                "title": finding["title"],
                "passed": is_success,
                "final_state": final_state.get("current_state") if final_state else "CRASHED",
                "reproduction_script": repro_result.get("script_code") if repro_result else None,
                "execution_log": repro_result.get("execution_log") if repro_result else None
            })
            
        # Compile Report
        report = {
            "total_bugs": len(benchmarks),
            "passed_count": passed,
            "pass_rate": passed / len(benchmarks),
            "success": passed >= 4,
            "details": results
        }
        
        logger.info(f"\n{'='*50}\nHARD GATE EVALUATION COMPLETE\nPass Rate: {passed}/5\n{'='*50}")
        
        # Save to evidence dir
        evidence_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evidence_engineer_1")
        os.makedirs(evidence_dir, exist_ok=True)
        report_path = os.path.join(evidence_dir, "task15_report.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
            
        logger.info(f"Saved evaluation report to {report_path}")
        
        if passed >= 4:
            sys.exit(0)
        else:
            sys.exit(1)

if __name__ == "__main__":
    run_evaluation()

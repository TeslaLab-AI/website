import os
import json
import logging
from app.contracts.schemas import EvidencePack, BugFinding
from app.analysis.context_builder import build_context_pack
from app.tools.repo_tools import search_code, read_file_chunk, find_files_by_name
from app.evidence.collector import harvest_logs
from app.tools.security import SecurityException

# Setup logging to capture task 8 evidence
log_path = "evidence_engineer_1/task8_evidence.log"
logging.basicConfig(
    filename=log_path,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("app.tools.security")
logger.setLevel(logging.INFO)

workspace = os.path.abspath(os.path.dirname(__file__))

# TASK 7 EVIDENCE
log_file = "evidence_engineer_1/dummy_app.log"
evidence = EvidencePack(
    stack_trace="Error: crash\n    at src/auth/handler.ts:42:1",
    logs=harvest_logs(log_file, "FINDING-BUG-001"),
    environment={"os": "Windows", "python": "3.13"},
    commit_hash="abc1234"
)
with open("evidence_engineer_1/task7_evidence.json", "w") as f:
    f.write(evidence.model_dump_json(indent=2))

# TASK 8 EVIDENCE
try:
    search_code("def extract_ast_chunks", workspace_path=os.path.dirname(workspace))
except Exception as e:
    logging.error(f"search_code failed: {e}")

try:
    find_files_by_name("*.py", workspace_path=os.path.dirname(workspace))
except Exception as e:
    logging.error(f"find_files_by_name failed: {e}")

try:
    # Attempt path traversal
    read_file_chunk("../../etc/passwd", 1, 10, workspace_path=os.path.dirname(workspace))
except SecurityException as e:
    logging.warning(f"Path traversal blocked successfully: {e}")

# TASK 9 EVIDENCE
# We need to run it against the mock repo to get actual chunks
mock_repo_path = "evidence_engineer_1/mock_repo_evidence"
os.makedirs(os.path.join(mock_repo_path, "src/auth"), exist_ok=True)
with open(os.path.join(mock_repo_path, "src/auth/handler.ts"), "w") as f:
    f.write("""export function authenticate(req, res) {
    const token = req.headers.authorization;
    if (!token) throw new Error("Missing token");
    // LINE 42 is here
    const user = verify(token);
    return user;
}""")

pack = build_context_pack(evidence, mock_repo_path)
with open("evidence_engineer_1/task9_evidence.json", "w") as f:
    f.write(pack.model_dump_json(indent=2))

print("Evidence generation complete.")

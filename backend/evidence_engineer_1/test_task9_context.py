import os
import shutil
import pytest
from app.contracts.schemas import EvidencePack
from app.analysis.context_builder import build_context_pack, MAX_TOKEN_BUDGET

# Define mock files content
MOCK_FILES = {
    "src/auth/handler.ts": {
        "content": """
import { SessionCache } from '../cache/session';
// filler lines...
""" + "\n// filler\n" * 35 + """
export function authenticate(req, res) {
    const token = req.headers.authorization;
    if (!token) throw new Error("Missing token");
    // LINE 42 is here
    const user = verify(token);
    return user;
}
""",
        "target_line": 42,
        "target_func": "authenticate",
        "seeded_id": "FINDING-BUG-001"
    },
    "src/cache/session.ts": {
        "content": """
import Redis from 'redis';
// filler lines...
""" + "\n// filler\n" * 80 + """
export class SessionCache {
    constructor() { this.client = new Redis(); }
    // LINE 88 is here
    async getSession(id) {
        return this.client.get(id);
    }
}
""",
        "target_line": 88,
        "target_func": "SessionCache",
        "seeded_id": "FINDING-BUG-002"
    },
    "src/api/paginate.ts": {
        "content": """
// filler lines...
""" + "\n// filler\n" * 110 + """
export function paginateResults(items, page, pageSize) {
    // LINE 115 is here
    const start = (page - 1) * pageSize;
    return items.slice(start, start + pageSize);
}
""",
        "target_line": 115,
        "target_func": "paginateResults",
        "seeded_id": "FINDING-BUG-003"
    },
    "package.json": {
        "content": """
{
  "name": "mock-repo",
  "dependencies": {
    "lodash": "^4.17.20",
    "axios": "^0.21.1"
  }
}
""",
        "target_line": 4, # Just somewhere in the file
        "target_func": None, # JSON has no functions
        "seeded_id": "FINDING-DEP-001"
    },
    "src/crypto/jwt.ts": {
        "content": """
import jwt from 'jsonwebtoken';
// filler lines...
""" + "\n// filler\n" * 8 + """
export function signToken(payload) {
    // LINE 14 is here
    return jwt.sign(payload, "secret");
}
""",
        "target_line": 14,
        "target_func": "signToken",
        "seeded_id": "FINDING-SEC-001"
    }
}

@pytest.fixture(scope="module")
def mock_repo(tmp_path_factory):
    repo_path = tmp_path_factory.mktemp("mock_repo")
    for file_path, data in MOCK_FILES.items():
        abs_path = os.path.join(repo_path, file_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        
        # Dynamically determine target_line
        lines = data['content'].splitlines()
        for i, line in enumerate(lines):
            if "is here" in line:
                data['target_line'] = i + 1
                break
                
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(str(data.get('content', '')))
            
    # Create some noise files
    for i in range(10):
        p = os.path.join(repo_path, f"src/noise_{i}.ts")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w') as f:
            f.write("export function noise() { return 'noise'; }\n" * 50)
            
    return str(repo_path)

def test_context_builder_token_limits(mock_repo):
    # Test that token budget is respected even with a huge stack trace / context
    evidence = EvidencePack(
        stack_trace="src/noise_0.ts:1:1\nsrc/noise_1.ts:1:1\nsrc/noise_2.ts:1:1",
        logs=[],
        environment={},
        commit_hash="abc1234"
    )
    
    pack = build_context_pack(evidence, mock_repo)
    
    assert pack.total_tokens <= MAX_TOKEN_BUDGET
    assert len(pack.chunks) > 0

def test_context_builder_seeded_findings(mock_repo):
    for fp, data in MOCK_FILES.items():
        # Create an evidence pack that mimics what would be generated for this seeded bug
        # We inject the file path into the stack trace to simulate a crash at that location
        stack = f"Error: crash\n    at {fp}:{data['target_line']}:1"
        evidence = EvidencePack(
            stack_trace=stack,
            logs=[],
            environment={},
            commit_hash="mockhash"
        )
        
        pack = build_context_pack(evidence, mock_repo)
        
        # Verify token limit
        assert pack.total_tokens <= MAX_TOKEN_BUDGET
        
        # Verify target file and function are in the TOP 3 chunks
        top_3 = pack.chunks[:3]
        found = False
        for chunk in top_3:
            if chunk.file_path == fp:
                if data['target_func'] is None or chunk.function_name == data['target_func']:
                    # Also verify the chunk encapsulates the target line if it's a code file
                    if chunk.start_line <= data['target_line'] <= chunk.end_line:
                        found = True
                        break
                        
        assert found, f"Failed to find {data['target_func']} in top 3 chunks for {fp}"

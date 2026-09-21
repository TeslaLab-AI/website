import sys
import os

# Add backend to path for tests
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.ingestion.parsers import parse_sentry_payload, parse_github_issue, parse_freeform_text
from app.contracts.schemas import BugFinding

def test_sentry_parser():
    # 1. Standard Python Exception
    sentry_1 = {
        "event_id": "sentry-py-001",
        "title": "ValueError: Invalid configuration",
        "exception": {
            "values": [{
                "type": "ValueError",
                "value": "Invalid configuration",
                "stacktrace": {
                    "frames": [
                        {"filename": "app/main.py", "lineno": 10, "function": "startup", "context_line": "load_config()"},
                        {"filename": "app/config.py", "lineno": 25, "function": "load_config", "context_line": "raise ValueError('Invalid configuration')"}
                    ]
                }
            }]
        },
        "tags": {"env": "production"}
    }
    
    # 2. JS Type Error (Missing title, should fallback)
    sentry_2 = {
        "id": "sentry-js-002",
        "exception": {
            "values": [{
                "type": "TypeError",
                "value": "Cannot read property 'map' of undefined",
                "stacktrace": {
                    "frames": [
                        {"abs_path": "/app/src/components/List.jsx", "lineno": 45, "function": "renderList"}
                    ]
                }
            }]
        },
        "breadcrumbs": [{"message": "Clicked button", "category": "ui.click"}]
    }

    # 3. Native Crash without stacktrace
    sentry_3 = {
        "event_id": "sentry-native-003",
        "title": "EXC_BAD_ACCESS / KERN_INVALID_ADDRESS",
        "metadata": {"value": "Fatal Error: Segfault at 0x000"},
        "tags": {"os": "iOS 15"}
    }
    
    # 4. Unknown format
    sentry_4 = {
        "event_id": "sentry-unknown-004",
        "tags": {"env": "staging"}
    }

    s1 = parse_sentry_payload(sentry_1)
    s2 = parse_sentry_payload(sentry_2)
    s3 = parse_sentry_payload(sentry_3)
    s4 = parse_sentry_payload(sentry_4)

    assert isinstance(s1, BugFinding)
    assert s1.id == "sentry-py-001"
    assert "app/main.py" in s1.files_hint
    assert "app/config.py" in s1.files_hint
    assert "line 25" in s1.stack_trace

    assert isinstance(s2, BugFinding)
    assert s2.title == "TypeError"
    assert "/app/src/components/List.jsx" in s2.files_hint
    assert s2.environment.get("breadcrumbs") is not None

    assert isinstance(s3, BugFinding)
    assert s3.stack_trace is None
    assert s3.environment.get("tags", {}).get("os") == "iOS 15"
    
    assert isinstance(s4, BugFinding)
    assert s4.title == "Sentry Crash Report"
    
    print("[SUCCESS] Sentry Parser passed (4/4 tests)")

def test_github_parser():
    # 5. Issue with Python Traceback
    gh_1 = {
        "number": 101,
        "title": "Crash on startup",
        "body": "When I run the app, it crashes.\n\n```python\nTraceback (most recent call last):\n  File \"src/server.py\", line 50, in <module>\n    start_server()\n  File \"src/server.py\", line 20, in start_server\n    bind(port)\nValueError: Port in use\n```",
        "labels": [{"name": "bug"}, {"name": "p1"}]
    }
    
    # 6. Issue with Generic Error
    gh_2 = {
        "id": "gh-102",
        "title": "Cannot login",
        "body": "Login fails randomly.\n\n```\nError: Database connection failed\n  File \"db/connect.ts\", line 88\n```",
        "state": "open"
    }

    # 7. Issue without stacktrace
    gh_3 = {
        "number": 103,
        "title": "Typo in README",
        "body": "There is a typo on line 5.",
        "html_url": "https://github.com/repo/issues/103"
    }

    g1 = parse_github_issue(gh_1)
    g2 = parse_github_issue(gh_2)
    g3 = parse_github_issue(gh_3)

    assert isinstance(g1, BugFinding)
    assert g1.id == "101"
    assert "src/server.py" in g1.files_hint
    assert "line 50" in g1.stack_trace
    assert "bug" in g1.environment.get("labels")

    assert isinstance(g2, BugFinding)
    assert "db/connect.ts" in g2.files_hint
    assert g2.environment.get("state") == "open"

    assert isinstance(g3, BugFinding)
    assert g3.stack_trace is None
    
    print("[SUCCESS] GitHub Issue Parser passed (3/3 tests)")

def test_llm_parser():
    # 8. Unstructured email/text
    text_1 = "Hey team, the payment gateway is throwing a 500 error in production. It says 'StripeAPIError' around line 112 in stripe_client.py when I try to checkout. Can someone look into this?"
    
    # 9. Copy-pasted console output
    text_2 = "Found a bug:\n\n> node index.js\nUnhandledPromiseRejectionWarning: TypeError: Cannot read property 'id' of undefined\n    at mapUser (services/user.js:45:20)\n    at processTicksAndRejections (internal/process/task_queues.js:95:5)"
    
    # 10. Vague bug report
    text_3 = "The UI looks weird on mobile Safari when you open the modal."

    l1 = parse_freeform_text(text_1)
    l2 = parse_freeform_text(text_2)
    l3 = parse_freeform_text(text_3)

    assert isinstance(l1, BugFinding)
    assert "stripe_client.py" in str(l1.files_hint)
    
    assert isinstance(l2, BugFinding)
    assert "services/user.js" in str(l2.files_hint)
    assert l2.stack_trace is not None
    
    assert isinstance(l3, BugFinding)

    print("[SUCCESS] LLM Freeform Parser passed (3/3 tests)")

if __name__ == "__main__":
    print("Running Bug Ingestion Parser Tests...\n")
    test_sentry_parser()
    test_github_parser()
    test_llm_parser()
    print("\n[SUCCESS] All 10 inputs parsed perfectly into unified BugFinding schema!")

"""
Purpose:
Test fixtures and generators for Engineer 3 Day 1 tasks (Tasks 31–33).

Includes:
- Mock repository generator with dependency graphs (client -> checkout -> billing)
- Seeded SQL injection fixture (CWE-89)
- Seeded secret token fixture (CWE-798)
- Pre-generated unified git diff fixtures (clean fix vs regression-introducing fix)
"""

from __future__ import annotations

import os
import tempfile


# Seeded code snippets for security tests
SEEDED_SQL_INJECTION_CODE = '''import sqlite3

def get_user_profile(db_path: str, username: str):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Insecure string interpolation causing SQL injection (CWE-89)
    query = f"SELECT id, username, email FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchone()
'''

SEEDED_SAFE_SQL_CODE = '''import sqlite3

def get_user_profile(db_path: str, username: str):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Parameterized query preventing SQL injection (CWE-89)
    query = "SELECT id, username, email FROM users WHERE username = ?"
    cursor.execute(query, (username,))
    return cursor.fetchone()
'''

SEEDED_SECRET_LEAK_CODE = '''import os

# Insecure hardcoded API token (CWE-798)
GITHUB_API_KEY = "ghp_FakeLiveGitHubSecretTokenABC1234567890"

def get_headers():
    return {"Authorization": f"Bearer {GITHUB_API_KEY}"}
'''


SAMPLE_DIFF_CLEAN = """--- a/src/payment/client.py
+++ b/src/payment/client.py
@@ -1,3 +1,3 @@
 def format_amount(cents: int) -> str:
-    return str(cents)
+    return f"${cents / 100:.2f}"
"""

SAMPLE_DIFF_WITH_SQLI = """--- a/src/auth/service.py
+++ b/src/auth/service.py
@@ -10,3 +10,4 @@
 def query_account(user_id):
+    cursor.execute(f"SELECT * FROM accounts WHERE id = '{user_id}'")
     return cursor.fetchall()
"""

SAMPLE_DIFF_WITH_SECRET = """--- a/src/config.py
+++ b/src/config.py
@@ -5,2 +5,3 @@
+AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
"""


def create_mock_repo(tmp_dir: str) -> dict[str, str]:
    """
    Creates a mock Python repository with clear module dependencies:
    - src/payment/client.py
    - src/payment/checkout.py (imports client)
    - src/payment/billing.py (imports client and checkout)
    - src/utils/helpers.py (unrelated utility)
    - tests/test_client.py
    - tests/test_checkout.py
    - tests/test_billing.py
    - tests/test_helpers.py
    """
    os.makedirs(os.path.join(tmp_dir, "src", "payment"), exist_ok=True)
    os.makedirs(os.path.join(tmp_dir, "src", "utils"), exist_ok=True)
    os.makedirs(os.path.join(tmp_dir, "tests"), exist_ok=True)

    paths = {
        "client": os.path.join(tmp_dir, "src", "payment", "client.py"),
        "checkout": os.path.join(tmp_dir, "src", "payment", "checkout.py"),
        "billing": os.path.join(tmp_dir, "src", "payment", "billing.py"),
        "helpers": os.path.join(tmp_dir, "src", "utils", "helpers.py"),
        "test_client": os.path.join(tmp_dir, "tests", "test_client.py"),
        "test_checkout": os.path.join(tmp_dir, "tests", "test_checkout.py"),
        "test_billing": os.path.join(tmp_dir, "tests", "test_billing.py"),
        "test_helpers": os.path.join(tmp_dir, "tests", "test_helpers.py"),
    }

    with open(paths["client"], "w", encoding="utf-8") as f:
        f.write("def calculate_fee(amount: float) -> float:\n    return amount * 0.02\n")

    with open(paths["checkout"], "w", encoding="utf-8") as f:
        f.write("from src.payment.client import calculate_fee\n\ndef process_cart(total: float) -> float:\n    return total + calculate_fee(total)\n")

    with open(paths["billing"], "w", encoding="utf-8") as f:
        f.write("from src.payment.checkout import process_cart\n\ndef create_invoice(total: float) -> str:\n    final = process_cart(total)\n    return f'Invoice: {final}'\n")

    with open(paths["helpers"], "w", encoding="utf-8") as f:
        f.write("def slugify(text: str) -> str:\n    return text.strip().lower().replace(' ', '-')\n")

    with open(paths["test_client"], "w", encoding="utf-8") as f:
        f.write("from src.payment.client import calculate_fee\n\ndef test_calculate_fee():\n    assert calculate_fee(100.0) == 2.0\n")

    with open(paths["test_checkout"], "w", encoding="utf-8") as f:
        f.write("from src.payment.checkout import process_cart\n\ndef test_process_cart():\n    assert process_cart(100.0) == 102.0\n")

    with open(paths["test_billing"], "w", encoding="utf-8") as f:
        f.write("from src.payment.billing import create_invoice\n\ndef test_create_invoice():\n    assert 'Invoice: 102.0' in create_invoice(100.0)\n")

    with open(paths["test_helpers"], "w", encoding="utf-8") as f:
        f.write("from src.utils.helpers import slugify\n\ndef test_slugify():\n    assert slugify('Hello World') == 'hello-world'\n")

    return paths

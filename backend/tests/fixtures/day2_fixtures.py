"""
Purpose:
Test fixtures and scenarios for Engineer 3 Day 2 deliverables (Tasks 34–36).

Includes:
- Multi-Signal Validation scenarios (1 clean passing fix, 5 distinct broken fixes)
- Seeded benchmark bugs for Task 35 (Self-Healing Repair Agent)
- Circuit breaker fixtures for Task 36 (Autonomous Loop)
"""

from __future__ import annotations

import os
import tempfile


# ─────────────────────────────────────────────────────────────────────────────
# 1. Multi-Signal Validation Scenarios (Task 34 / AC-E3-D2-01)
# ─────────────────────────────────────────────────────────────────────────────

CLEAN_PASSING_DIFF = """--- a/src/payment/client.py
+++ b/src/payment/client.py
@@ -1,2 +1,3 @@
 def calculate_fee(amount: float) -> float:
+    if amount <= 0.0:
+        return 0.0
     return amount * 0.02
"""

# Broken Scenario 1: Fails Requirements Check (modifies unrelated file, misses payment client)
DIFF_FAILING_REQUIREMENTS = """--- a/src/utils/logger.py
+++ b/src/utils/logger.py
@@ -1,2 +1,3 @@
 def log_message(msg: str) -> None:
+    # Unrelated change that fails the task requirements
     print(f"LOG: {msg}")
"""

# Broken Scenario 2: Fails Diff Quality Check (bloated diff exceeding line count limits)
DIFF_FAILING_DIFF_QUALITY = """--- a/src/payment/client.py
+++ b/src/payment/client.py
@@ -1,2 +1,165 @@
 def calculate_fee(amount: float) -> float:
""" + "".join(f"+    # Bloated unnecessary comment line {i}\n" for i in range(165)) + """+    return amount * 0.02\n"""

# Broken Scenario 3: Fails Repro Test (applies no-op or wrong calculation, so repro test still fails)
DIFF_FAILING_REPRO_TEST = """--- a/src/payment/client.py
+++ b/src/payment/client.py
@@ -1,2 +1,3 @@
 def calculate_fee(amount: float) -> float:
+    # Wrong fix: repro test requires fee(0.0) == 0.0, but this returns -1.0
+    return -1.0
"""

# Broken Scenario 4: Fails Regression Test (fixes client but breaks cart calculation in checkout.py)
DIFF_FAILING_REGRESSION = """--- a/src/payment/checkout.py
+++ b/src/payment/checkout.py
@@ -1,4 +1,4 @@
 from src.payment.client import calculate_fee
 
 def process_cart(total: float) -> float:
-    return total + calculate_fee(total)
+    # Injected regression: breaks cart total calculation
+    return 0.0
"""

# Broken Scenario 5: Fails Security Scan (introduces unparameterized SQL execution CWE-89)
DIFF_FAILING_SECURITY = """--- a/src/payment/client.py
+++ b/src/payment/client.py
@@ -1,3 +1,4 @@
 def calculate_fee(amount: float) -> float:
+    cursor.execute(f"SELECT fee_rate FROM rates WHERE tier = '{amount}'")
     return amount * 0.02
"""


# ─────────────────────────────────────────────────────────────────────────────
# 2. Benchmark Bug Seeders for Repair Agent (Task 35 / AC-E3-D2-02)
# ─────────────────────────────────────────────────────────────────────────────

def setup_repair_benchmark_repo(tmp_dir: str) -> dict[str, str]:
    """
    Sets up a benchmark repository with an off-by-one fault in pagination logic.
    Reproduction test initially FAILS. Repair agent must analyze diagnostic and fix it.
    """
    src_dir = os.path.join(tmp_dir, "src", "catalog")
    test_dir = os.path.join(tmp_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    items_file = os.path.join(src_dir, "paginate.py")
    test_repro_file = os.path.join(test_dir, "test_repro_pagination.py")
    test_reg_file = os.path.join(test_dir, "test_regression_catalog.py")

    # Buggy code: off-by-one error (page_size - 1 instead of page_size)
    with open(items_file, "w", encoding="utf-8") as f:
        f.write("""def paginate_items(items: list, page: int, page_size: int) -> list:
    # BUG: Off-by-one boundary error in slice
    start = (page - 1) * page_size
    end = start + (page_size - 1)
    return items[start:end]
""")

    # Repro test: asserts that requesting page_size 5 returns exactly 5 items
    with open(test_repro_file, "w", encoding="utf-8") as f:
        f.write("""from src.catalog.paginate import paginate_items

def test_repro_exact_page_size():
    data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    result = paginate_items(data, page=1, page_size=5)
    # Fails initially because buggy code returns only 4 items!
    assert len(result) == 5, f"Expected 5 items, got {len(result)}"
""")

    # Regression test: asserts first element is correctly retrieved
    with open(test_reg_file, "w", encoding="utf-8") as f:
        f.write("""from src.catalog.paginate import paginate_items

def test_regression_first_element():
    data = ['a', 'b', 'c']
    result = paginate_items(data, page=1, page_size=2)
    assert result[0] == 'a'
""")

    return {
        "paginate": items_file,
        "test_repro": test_repro_file,
        "test_regression": test_reg_file,
    }


def setup_bug2_zero_fee_repo(tmp_dir: str) -> dict[str, str]:
    """Benchmark Bug 2: Missing zero-fee guardrail."""
    src_dir = os.path.join(tmp_dir, "src", "payment")
    test_dir = os.path.join(tmp_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    client_file = os.path.join(src_dir, "client.py")
    test_repro = os.path.join(test_dir, "test_repro_zero_fee.py")
    test_reg = os.path.join(test_dir, "test_regression_payment.py")

    with open(client_file, "w", encoding="utf-8") as f:
        f.write("""def calculate_fee(amount: float) -> float:
    # Bug: fails to return 0.0 for zero/negative values
    return -1.0 if amount <= 0.0 else amount * 0.02
""")

    with open(test_repro, "w", encoding="utf-8") as f:
        f.write("""from src.payment.client import calculate_fee

def test_zero_amount_fee():
    assert calculate_fee(0.0) == 0.0, "Expected fee 0.0 for zero amount"
""")

    with open(test_reg, "w", encoding="utf-8") as f:
        f.write("""from src.payment.client import calculate_fee

def test_positive_fee():
    assert calculate_fee(100.0) == 2.0
""")

    return {
        "source": client_file,
        "test_repro": test_repro,
        "test_regression": test_reg,
    }


def setup_bug3_security_sqli_repo(tmp_dir: str) -> dict[str, str]:
    """Benchmark Bug 3: SQL Injection CWE-89 in query constructor."""
    src_dir = os.path.join(tmp_dir, "src", "payment")
    test_dir = os.path.join(tmp_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    client_file = os.path.join(src_dir, "client.py")
    test_reg = os.path.join(test_dir, "test_regression_payment.py")

    with open(client_file, "w", encoding="utf-8") as f:
        f.write("""def calculate_fee(amount: float) -> float:
    cursor.execute(f"SELECT fee_rate FROM rates WHERE tier = '{amount}'")
    return amount * 0.02
""")

    with open(test_reg, "w", encoding="utf-8") as f:
        f.write("""from src.payment.client import calculate_fee

def test_positive_fee():
    assert True
""")

    return {
        "source": client_file,
        "test_repro": "",
        "test_regression": test_reg,
    }


def setup_bug4_inverted_boolean_repo(tmp_dir: str) -> dict[str, str]:
    """Benchmark Bug 4: Inverted boolean check in token validator."""
    src_dir = os.path.join(tmp_dir, "src", "auth")
    test_dir = os.path.join(tmp_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    validator_file = os.path.join(src_dir, "validator.py")
    test_repro = os.path.join(test_dir, "test_repro_auth.py")
    test_reg = os.path.join(test_dir, "test_regression_auth.py")

    with open(validator_file, "w", encoding="utf-8") as f:
        f.write("""def validate_token(token: str) -> bool:
    # Bug: inverted condition returns False for valid tokens
    if not token or len(token) < 8:
        return True
    return False
""")

    with open(test_repro, "w", encoding="utf-8") as f:
        f.write("""from src.auth.validator import validate_token

def test_valid_token():
    assert validate_token("long_valid_token_123") is True, "Valid token must return True"
""")

    with open(test_reg, "w", encoding="utf-8") as f:
        f.write("""from src.auth.validator import validate_token

def test_empty_token():
    # Empty token will fail with current bug
    pass
""")

    return {
        "source": validator_file,
        "test_repro": test_repro,
        "test_regression": test_reg,
    }


def setup_bug5_string_sanitizer_repo(tmp_dir: str) -> dict[str, str]:
    """Benchmark Bug 5: String sanitizer fails to hyphenate spaces."""
    src_dir = os.path.join(tmp_dir, "src", "utils")
    test_dir = os.path.join(tmp_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    sanitizer_file = os.path.join(src_dir, "sanitizer.py")
    test_repro = os.path.join(test_dir, "test_repro_sanitize.py")
    test_reg = os.path.join(test_dir, "test_regression_sanitize.py")

    with open(sanitizer_file, "w", encoding="utf-8") as f:
        f.write("""def sanitize_slug(text: str) -> str:
    # Bug: does not replace whitespace
    return text.strip().lower()
""")

    with open(test_repro, "w", encoding="utf-8") as f:
        f.write("""from src.utils.sanitizer import sanitize_slug

def test_slug_hyphens():
    assert sanitize_slug("Hello World") == "hello-world", "Spaces must be replaced by hyphens"
""")

    with open(test_reg, "w", encoding="utf-8") as f:
        f.write("""from src.utils.sanitizer import sanitize_slug

def test_simple_slug():
    assert sanitize_slug("simple") == "simple"
""")

    return {
        "source": sanitizer_file,
        "test_repro": test_repro,
        "test_regression": test_reg,
    }


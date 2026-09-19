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

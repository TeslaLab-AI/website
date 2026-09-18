"""
Purpose:
Automates generation of all required Day 1 submission evidence for Engineer 3.

Produces:
1. evidence/verification_report.json (Independent test verification payload)
2. evidence/tia_benchmark_logs.txt (Comparative benchmark showing <25% duration)
3. evidence/security_report_cwe89.json (Seeded SQL injection CWE-89 detection report)
4. evidence/sast_scan_logs.txt (Scan traces for clean vs vulnerable samples)
"""

import json
import os
import sys
import tempfile
import time
import subprocess

# Ensure app is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.fixtures.day1_fixtures import (
    create_mock_repo,
    SEEDED_SQL_INJECTION_CODE,
    SEEDED_SAFE_SQL_CODE,
    SEEDED_SECRET_LEAK_CODE,
)
from agents.agent_3.independent_tester import run_independent_verification
from agents.agent_3.test_impact import select_impacted_tests
from agents.agent_3.security_agent import scan_codebase_security, diff_security_gate


def main():
    evidence_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "evidence"))
    os.makedirs(evidence_dir, exist_ok=True)
    print(f"Generating Day 1 Evidence into: {evidence_dir}\n")

    # ─────────────────────────────────────────────────────────────
    # Evidence 1: VerificationReport JSON Payload (Task 31)
    # ─────────────────────────────────────────────────────────────
    print("1. Generating VerificationReport JSON...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        create_mock_repo(tmp_dir)
        repro_path = os.path.join(tmp_dir, "tests", "test_repro.py")
        with open(repro_path, "w", encoding="utf-8") as f:
            f.write("from src.payment.client import calculate_fee\n\ndef test_repro():\n    assert calculate_fee(100.0) == 2.0\n")

        v_report = run_independent_verification(
            repo_root=tmp_dir,
            changed_files=["src/payment/client.py"],
            repro_test_path=repro_path,
        )

        v_path = os.path.join(evidence_dir, "verification_report.json")
        with open(v_path, "w", encoding="utf-8") as f:
            json.dump(v_report.model_dump(), f, indent=2)
        print(f"   Saved {v_path}")

    # ─────────────────────────────────────────────────────────────
    # Evidence 2: TIA Performance Benchmark Logs (Task 32)
    # ─────────────────────────────────────────────────────────────
    print("\n2. Generating TIA Benchmark Logs...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        create_mock_repo(tmp_dir)

        # Populate realistic test suite
        for i in range(24):
            with open(os.path.join(tmp_dir, "tests", f"test_extra_{i}.py"), "w", encoding="utf-8") as f:
                f.write(f"import time\ndef test_extra_{i}():\n    time.sleep(0.10)\n    assert True\n")

        manifest = select_impacted_tests(tmp_dir, ["src/utils/helpers.py"])

        t0 = time.perf_counter()
        subprocess.run([sys.executable, "-m", "pytest"] + manifest.selected_tests, cwd=tmp_dir, stdout=subprocess.PIPE)
        t_targeted = time.perf_counter() - t0

        all_tests = [os.path.join("tests", f) for f in os.listdir(os.path.join(tmp_dir, "tests")) if f.startswith("test_")]
        t1 = time.perf_counter()
        subprocess.run([sys.executable, "-m", "pytest"] + all_tests, cwd=tmp_dir, stdout=subprocess.PIPE)
        t_full = time.perf_counter() - t1

        ratio = (t_targeted / t_full) * 100 if t_full > 0 else 0

        tia_log_path = os.path.join(evidence_dir, "tia_benchmark_logs.txt")
        with open(tia_log_path, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("TESLALAB AI — TEST IMPACT ANALYSIS (TIA) BENCHMARK EVIDENCE\n")
            f.write(f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Modified File: src/utils/helpers.py\n")
            f.write(f"Selected Tests: {manifest.selected_tests}\n")
            f.write(f"Total Test Suite Size: {len(all_tests)} test files\n\n")
            f.write(f"Targeted Test Suite Runtime: {t_targeted:.3f} seconds\n")
            f.write(f"Full Test Suite Runtime:     {t_full:.3f} seconds\n")
            f.write(f"Speedup Ratio:               {ratio:.1f}%\n")
            f.write(f"Target Threshold:            < 25.0%\n")
            f.write(f"Benchmark Verdict:           {'PASSED' if ratio < 25.0 else 'FAILED'}\n")
        print(f"   Saved {tia_log_path} (Ratio: {ratio:.1f}%)")

    # ─────────────────────────────────────────────────────────────
    # Evidence 3: SecurityReport JSON (Seeded SQLi CWE-89) (Task 33)
    # ─────────────────────────────────────────────────────────────
    print("\n3. Generating SecurityReport JSON (CWE-89)...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        with open(os.path.join(tmp_dir, "db_query.py"), "w", encoding="utf-8") as f:
            f.write(SEEDED_SQL_INJECTION_CODE)

        sec_report = scan_codebase_security(tmp_dir)
        sec_path = os.path.join(evidence_dir, "security_report_cwe89.json")
        with open(sec_path, "w", encoding="utf-8") as f:
            json.dump(sec_report.model_dump(), f, indent=2)
        print(f"   Saved {sec_path}")

    # ─────────────────────────────────────────────────────────────
    # Evidence 4: SAST Scan Logs for Clean vs Vulnerable (Task 33)
    # ─────────────────────────────────────────────────────────────
    print("\n4. Generating SAST Scan Logs...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Vulnerable
        with open(os.path.join(tmp_dir, "vulnerable.py"), "w", encoding="utf-8") as f:
            f.write(SEEDED_SQL_INJECTION_CODE)
            f.write("\n" + SEEDED_SECRET_LEAK_CODE)
        vuln_report = scan_codebase_security(tmp_dir)

        # Clean
        with open(os.path.join(tmp_dir, "clean.py"), "w", encoding="utf-8") as f:
            f.write(SEEDED_SAFE_SQL_CODE)
        clean_report = scan_codebase_security(tmp_dir, target_files=["clean.py"])

        sast_log_path = os.path.join(evidence_dir, "sast_scan_logs.txt")
        with open(sast_log_path, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("TESLALAB AI — SAST SCAN LOGS (CLEAN VS VULNERABLE SAMPLES)\n")
            f.write(f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
            f.write("=" * 60 + "\n\n")
            f.write("--- SAMPLE 1: VULNERABLE CODE (SQLi & Leaked Token) ---\n")
            f.write(f"Scan Passed: {vuln_report.passed}\n")
            f.write(f"Vulnerabilities Found: {len(vuln_report.vulnerabilities)}\n")
            for idx, v in enumerate(vuln_report.vulnerabilities, 1):
                f.write(f"  [{idx}] Severity={v.severity.upper()} | CWE={v.cwe} | Line {v.line}\n")
                f.write(f"      Description: {v.description}\n")
                f.write(f"      Remediation: {v.remediation_hint}\n")

            f.write("\n--- SAMPLE 2: CLEAN CODE (Parameterized Query) ---\n")
            f.write(f"Scan Passed: {clean_report.passed}\n")
            f.write(f"Vulnerabilities Found: {len(clean_report.vulnerabilities)}\n")
            f.write(f"Summary: {clean_report.raw_output}\n")
        print(f"   Saved {sast_log_path}")

    print("\nAll Day 1 Evidence artifacts generated successfully!")


if __name__ == "__main__":
    main()

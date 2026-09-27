"""
TeslaLab AI — Engineer 1: Diagnosis & Foundation Lead
Script: generate_engineer1_evidence.py

Generates authoritative evidence artifacts for Engineer 1:
1. evidence/serialization_test_output.log (Contract serialization evidence)
2. evidence/ingestion_idempotency_log.txt (Finding ingestion & deduplication trace)
3. evidence/session_state_machine_audit_log.json (13-state machine progression & event log)
4. evidence/invalid_transition_guard_trace.txt (Illegal state jump rejection traces)
"""

import os
import sys

backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from scripts.generate_day1_evidence import generate_engineer_1_evidence

if __name__ == "__main__":
    evidence_dir = os.path.join(backend_root, "evidence")
    os.makedirs(evidence_dir, exist_ok=True)
    generate_engineer_1_evidence(evidence_dir)
    print("[SUCCESS] Engineer 1 Evidence Generated Successfully!")

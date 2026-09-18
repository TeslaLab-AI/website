"""
Purpose:
Task 33: Security Agent and Diff Security Gate.
Provides static application security testing (SAST), secret detection,
and diff-level security gating to prevent introducing new vulnerabilities.

Acceptance Criteria:
- AC-E3-D1-03: Execute Security Agent on seeded SQL injection defect;
  assert detection with exact CWE-89 classification and remediation advice.
- Diff Security Gate: Rejects patches introducing new High or Critical vulnerabilities.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
from typing import List, Tuple, Optional

try:
    from .verification_models import VulnFinding, SecurityReport
except (ImportError, ValueError):
    from agents.agent_3.verification_models import VulnFinding, SecurityReport


# Common CWE Identifiers
CWE_SQLI = "CWE-89"          # SQL Injection
CWE_HARDCODED_SECRET = "CWE-798"  # Use of Hard-coded Credentials
CWE_CODE_INJECTION = "CWE-95"      # Eval / Exec Injection
CWE_PATH_TRAVERSAL = "CWE-22"      # Path Traversal


# Secret Detection Regex Patterns
SECRET_PATTERNS = [
    (re.compile(r"ghp_[A-Za-z0-9_]{30,}"), "GitHub Personal Access Token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID"),
    (re.compile(r"(?i)(?:aws_secret_access_key|secret_key|api_key|token)\s*=\s*['\"][A-Za-z0-9/+=_-]{16,}['\"]"), "Hardcoded Secret Token"),
    (re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP)?\s*PRIVATE KEY-----"), "Private Cryptographic Key"),
]


SQL_KEYWORDS = {"select", "insert", "update", "delete", "drop", "alter", "from", "where"}


def _is_sql_string(text: str) -> bool:
    """Checks if text contains SQL commands."""
    words = set(re.findall(r"\w+", text.lower()))
    return len(words.intersection(SQL_KEYWORDS)) >= 2


class SecurityASTVisitor(ast.NodeVisitor):
    """
    Parses Python AST to detect dangerous security patterns:
    - Formatted string SQL queries in variables or execute() calls (CWE-89)
    - eval() / exec() usage (CWE-95)
    """

    def __init__(self, rel_path: str, source_lines: List[str]):
        self.rel_path = rel_path
        self.source_lines = source_lines
        self.findings: List[VulnFinding] = []
        self.dynamic_sql_vars: dict[str, int] = {}  # var_name -> line_no

    def visit_Assign(self, node: ast.Assign):
        # Detect: query = f"SELECT ... WHERE username = '{username}'"
        val = node.value
        is_dynamic_sql = False

        if isinstance(val, ast.JoinedStr):
            # Inspect string parts of the f-string
            joined_text = "".join(p.value for p in val.values if isinstance(p, ast.Constant) and isinstance(p.value, str))
            if _is_sql_string(joined_text):
                is_dynamic_sql = True
        elif isinstance(val, ast.BinOp) and isinstance(val.op, (ast.Mod, ast.Add)):
            if isinstance(val.left, ast.Constant) and isinstance(val.left.value, str) and _is_sql_string(val.left.value):
                is_dynamic_sql = True
        elif isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute) and val.func.attr == "format":
            if isinstance(val.func.value, ast.Constant) and isinstance(val.func.value.value, str) and _is_sql_string(val.func.value.value):
                is_dynamic_sql = True

        if is_dynamic_sql:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.dynamic_sql_vars[target.id] = getattr(node, "lineno", 1)

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        func_name = ""
        if isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            func_name = node.func.id

        # 1. Detect SQL Injection in cursor.execute(...)
        if func_name == "execute" and node.args:
            first_arg = node.args[0]
            is_sqli = False
            line_no = getattr(node, "lineno", 1)

            # Case A: execute(query) where query is a tracked dynamic SQL string
            if isinstance(first_arg, ast.Name) and first_arg.id in self.dynamic_sql_vars:
                is_sqli = True
                line_no = self.dynamic_sql_vars[first_arg.id]

            # Case B: execute(f"SELECT ...") directly
            elif isinstance(first_arg, ast.JoinedStr):
                joined_text = "".join(p.value for p in first_arg.values if isinstance(p, ast.Constant) and isinstance(p.value, str))
                if _is_sql_string(joined_text) or len(first_arg.values) > 1:
                    is_sqli = True

            # Case C: execute("SELECT ... %s" % var) or execute("SELECT ... " + var)
            elif isinstance(first_arg, ast.BinOp) and isinstance(first_arg.op, (ast.Mod, ast.Add)):
                is_sqli = True
            elif isinstance(first_arg, ast.Call) and isinstance(first_arg.func, ast.Attribute) and first_arg.func.attr == "format":
                is_sqli = True

            if is_sqli:
                self.findings.append(
                    VulnFinding(
                        severity="critical",
                        cwe=CWE_SQLI,
                        file=self.rel_path,
                        line=line_no,
                        description="Improper Neutralization of Special Elements used in an SQL Command ('SQL Injection')",
                        remediation_hint="Use parameterized queries with placeholder bindings (e.g. cursor.execute('SELECT ... WHERE col = ?', (val,))) instead of string formatting or concatenation.",
                    )
                )

        # 2. Detect Code Injection: eval() or exec()
        if func_name in ("eval", "exec"):
            line_no = getattr(node, "lineno", 1)
            self.findings.append(
                VulnFinding(
                    severity="critical",
                    cwe=CWE_CODE_INJECTION,
                    file=self.rel_path,
                    line=line_no,
                    description=f"Use of dangerous dynamic execution function '{func_name}' ('Code Injection')",
                    remediation_hint=f"Avoid using {func_name}(). Use safer alternatives like ast.literal_eval() or explicit parsers.",
                )
            )

        self.generic_visit(node)


def scan_file_for_secrets(rel_path: str, content: str) -> List[VulnFinding]:
    """Scans text content for hardcoded secrets and credentials (CWE-798)."""
    findings: List[VulnFinding] = []
    lines = content.splitlines()

    for idx, line in enumerate(lines, 1):
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(
                    VulnFinding(
                        severity="high",
                        cwe=CWE_HARDCODED_SECRET,
                        file=rel_path,
                        line=idx,
                        description=f"Hardcoded credential detected: {label}",
                        remediation_hint="Never hardcode credentials or secrets in source code. Store them in environment variables or a secrets manager.",
                    )
                )
    return findings


def scan_file_security(repo_root: str, rel_path: str) -> List[VulnFinding]:
    """Scans a single file for security vulnerabilities and hardcoded secrets."""
    abs_path = os.path.join(repo_root, rel_path)
    if not os.path.exists(abs_path):
        return []

    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as fp:
            content = fp.read()
    except Exception:
        return []

    findings: List[VulnFinding] = []

    # 1. Run Secret Scanner on all files
    findings.extend(scan_file_for_secrets(rel_path, content))

    # 2. Run AST SAST on Python files
    if rel_path.endswith(".py"):
        try:
            tree = ast.parse(content, filename=rel_path)
            visitor = SecurityASTVisitor(rel_path, content.splitlines())
            visitor.visit(tree)
            findings.extend(visitor.findings)
        except Exception:
            pass

    return findings


def scan_codebase_security(repo_root: str, target_files: Optional[List[str]] = None) -> SecurityReport:
    """
    Scans repository files (or a targeted subset) for vulnerabilities.
    Returns a comprehensive SecurityReport.
    """
    files_to_scan: List[str] = []
    if target_files is not None:
        files_to_scan = [f.replace("\\", "/").lstrip("./") for f in target_files]
    else:
        for root, _, files in os.walk(repo_root):
            if ".venv" in root or "__pycache__" in root or ".pytest_cache" in root:
                continue
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), repo_root).replace("\\", "/")
                files_to_scan.append(rel)

    all_vulns: List[VulnFinding] = []
    for rel_f in files_to_scan:
        all_vulns.extend(scan_file_security(repo_root, rel_f))

    # Passed is True if no critical or high severity vulnerabilities exist
    has_blocking_vulns = any(v.severity in ("critical", "high") for v in all_vulns)
    passed = not has_blocking_vulns

    raw_summary = f"Scanned {len(files_to_scan)} files. Found {len(all_vulns)} vulnerabilities."

    return SecurityReport(
        passed=passed,
        vulnerabilities=all_vulns,
        raw_output=raw_summary,
    )


def diff_security_gate(repo_root: str, diff_text: str, baseline_report: Optional[SecurityReport] = None) -> SecurityReport:
    """
    Diff Security Gate:
    1. Scans modified files and newly introduced lines in the git diff.
    2. Compares against baseline report (if provided).
    3. Rejects diffs introducing new high/critical vulnerabilities immediately.
    """
    new_vulns: List[VulnFinding] = []
    resolved_vulns: List[VulnFinding] = []

    # Extract changed files and added lines from unified diff
    current_file = ""
    added_lines_by_file: dict[str, list[tuple[int, str]]] = {}
    current_line_no = 0

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip().replace("\\", "/")
            added_lines_by_file[current_file] = []
            current_line_no = 0
        elif line.startswith("@@"):
            # e.g. @@ -10,3 +10,4 @@ -> extract line 10
            match = re.search(r"\+(\d+)", line)
            if match:
                current_line_no = int(match.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            code_line = line[1:]
            if current_file:
                added_lines_by_file[current_file].append((current_line_no, code_line))
            current_line_no += 1
        elif not line.startswith("-"):
            current_line_no += 1

    # Scan the added lines in diff for secrets and code vulnerabilities
    for rel_path, added_items in added_lines_by_file.items():
        for line_no, code_line in added_items:
            # Check secrets in added lines
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(code_line):
                    new_vulns.append(
                        VulnFinding(
                            severity="high",
                            cwe=CWE_HARDCODED_SECRET,
                            file=rel_path,
                            line=line_no,
                            description=f"Diff introduces hardcoded credential: {label}",
                            remediation_hint="Remove secret from diff; use environment variables.",
                        )
                    )

            # Check SQL injection in added lines
            if "execute(" in code_line and ("f\"" in code_line or "f'" in code_line or " % " in code_line):
                new_vulns.append(
                    VulnFinding(
                        severity="critical",
                        cwe=CWE_SQLI,
                        file=rel_path,
                        line=line_no,
                        description="Diff introduces unparameterized SQL execution ('SQL Injection')",
                        remediation_hint="Use parameterized queries instead of string interpolation.",
                    )
                )

    # Re-scan affected files in repository worktree
    post_scan = scan_codebase_security(repo_root, target_files=list(added_lines_by_file.keys()))
    for v in post_scan.vulnerabilities:
        if v not in new_vulns:
            # Check if this vuln was already in baseline
            is_new = True
            if baseline_report:
                for b_v in baseline_report.vulnerabilities:
                    if b_v.cwe == v.cwe and b_v.file == v.file and b_v.line == v.line:
                        is_new = False
                        break
            if is_new:
                new_vulns.append(v)

    # Check for resolved vulnerabilities
    if baseline_report:
        for b_v in baseline_report.vulnerabilities:
            still_present = any(v.cwe == b_v.cwe and v.file == b_v.file for v in post_scan.vulnerabilities)
            if not still_present:
                resolved_vulns.append(b_v)

    # Security Gate: Reject diff if ANY new high/critical vulnerabilities exist
    has_new_blocking = any(v.severity in ("critical", "high") for v in new_vulns)
    gate_passed = not has_new_blocking

    status_msg = "Diff Security Gate PASSED." if gate_passed else f"Diff Security Gate REJECTED: {len(new_vulns)} new vulnerability detected."

    return SecurityReport(
        passed=gate_passed,
        vulnerabilities=post_scan.vulnerabilities,
        new_vulnerabilities=new_vulns,
        resolved_vulnerabilities=resolved_vulns,
        raw_output=status_msg,
    )

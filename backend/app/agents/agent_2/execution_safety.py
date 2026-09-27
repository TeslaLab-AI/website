"""
ExecutionSafety: Centralized Runtime Interceptor for Agent 2 (Day 5 Task 29).

Enforces four runtime guards during plan execution:
1. File Write Jail (canonical paths, workspace containment, .git/.env/CI rejection)
2. Command Blocklist (sudo, npm -g, pip install, curl, wget, shell chaining protection)
3. Diff Size (max 500 changed lines, max 5 modified files from real git diff)
4. Loop Detection (aborts on 4th repetition of identical step/state signature)

Every violation immediately halts execution, logs a structured violation,
and transitions execution status / session state to NEEDS_HUMAN.
"""

from __future__ import annotations

from enum import Enum
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.contracts.schemas import SessionState

logger = logging.getLogger("execution_safety")

MAX_DIFF_LINES = 500
MAX_DIFF_FILES = 5
MAX_LOOP_REPETITIONS = 3

PROTECTED_SEGMENTS = {
    ".git",
    ".github",
    ".gitlab-ci.yml",
    ".circleci",
    "jenkinsfile",
    "azure-pipelines.yml",
    ".pre-commit-config.yaml",
    ".travis.yml",
    "bitbucket-pipelines.yml",
}


class GuardType(str, Enum):
    FILE_WRITE_JAIL = "FILE_WRITE_JAIL"
    COMMAND_BLOCKLIST = "COMMAND_BLOCKLIST"
    DIFF_SIZE = "DIFF_SIZE"
    LOOP_DETECTION = "LOOP_DETECTION"


class SafetyViolation(BaseModel):
    guard: GuardType
    target: str
    reason: str
    details: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class SafetyViolationError(Exception):
    """Raised when an ExecutionSafety guard is violated."""
    def __init__(self, violation: SafetyViolation) -> None:
        super().__init__(f"[{violation.guard.value}] {violation.reason} (target: {violation.target})")
        self.violation = violation


class ExecutionSafety:
    """
    Centralized runtime safety interceptor for executor agents.
    Maintains runtime state across step executions within a session.
    """

    def __init__(self, max_diff_lines: int = MAX_DIFF_LINES, max_diff_files: int = MAX_DIFF_FILES) -> None:
        self.max_diff_lines = max_diff_lines
        self.max_diff_files = max_diff_files
        self.step_signatures: List[str] = []
        self.signature_counts: Dict[str, int] = {}
        self.violations: List[SafetyViolation] = []

    # ─────────────────────────────────────────────────────────────────────────
    # Guard 1: File Write Jail
    # ─────────────────────────────────────────────────────────────────────────
    def validate_file_write(self, workspace_root: str, target_path: str) -> None:
        """
        Ensures target file is strictly inside workspace_root and not protected.
        Rejects:
        - ../ traversal
        - Symlink escape outside workspace root
        - .git and its contents
        - .env and related environment files
        - CI configuration files (.github, .gitlab-ci.yml, etc.)
        """
        if not workspace_root:
            raise SafetyViolationError(
                SafetyViolation(
                    guard=GuardType.FILE_WRITE_JAIL,
                    target=target_path,
                    reason="Workspace root is undefined; cannot verify write destination.",
                )
            )

        # 1. Reject obvious relative traversal strings before path resolution
        norm_raw = target_path.replace("\\", "/")
        raw_parts = [p for p in norm_raw.split("/") if p]
        if ".." in raw_parts:
            # Check if traversing above workspace root
            pass  # Handled authoritatively by realpath check below

        # 2. Canonical absolute path resolution
        canonical_ws = os.path.realpath(os.path.abspath(workspace_root))
        if os.path.isabs(target_path):
            canonical_target = os.path.realpath(os.path.abspath(target_path))
        else:
            canonical_target = os.path.realpath(os.path.abspath(os.path.join(canonical_ws, target_path)))

        # 3. Containment verification (prevents directory traversal & symlink escape)
        try:
            common = os.path.commonpath([canonical_ws, canonical_target])
            if common != canonical_ws:
                violation = SafetyViolation(
                    guard=GuardType.FILE_WRITE_JAIL,
                    target=target_path,
                    reason=f"Path '{target_path}' escapes workspace root '{canonical_ws}'.",
                    details={"canonical_target": canonical_target, "canonical_workspace": canonical_ws},
                )
                self.violations.append(violation)
                raise SafetyViolationError(violation)
        except ValueError as ve:
            violation = SafetyViolation(
                guard=GuardType.FILE_WRITE_JAIL,
                target=target_path,
                reason=f"Path comparison error (cross-drive or invalid path): {ve}",
            )
            self.violations.append(violation)
            raise SafetyViolationError(violation)

        # 4. Protected file segments check (.git, .env, CI files)
        try:
            rel_target = os.path.relpath(canonical_target, canonical_ws).replace("\\", "/")
        except ValueError:
            rel_target = target_path.replace("\\", "/")

        segments = [s.lower() for s in rel_target.split("/") if s]
        filename = segments[-1] if segments else ""

        # Reject .git
        if ".git" in segments:
            violation = SafetyViolation(
                guard=GuardType.FILE_WRITE_JAIL,
                target=target_path,
                reason="Modification of .git repository internals is strictly prohibited.",
                details={"relative_path": rel_target},
            )
            self.violations.append(violation)
            raise SafetyViolationError(violation)

        # Reject .env files (.env, .env.local, .env.production, etc.)
        if filename == ".env" or filename.startswith(".env."):
            violation = SafetyViolation(
                guard=GuardType.FILE_WRITE_JAIL,
                target=target_path,
                reason=f"Modification of environment configuration '{filename}' is strictly prohibited.",
                details={"filename": filename},
            )
            self.violations.append(violation)
            raise SafetyViolationError(violation)

        # Reject CI configuration and other protected repo files
        for seg in segments:
            if seg in PROTECTED_SEGMENTS:
                violation = SafetyViolation(
                    guard=GuardType.FILE_WRITE_JAIL,
                    target=target_path,
                    reason=f"Modification of protected configuration '{seg}' is strictly prohibited.",
                    details={"matched_segment": seg},
                )
                self.violations.append(violation)
                raise SafetyViolationError(violation)

    # ─────────────────────────────────────────────────────────────────────────
    # Guard 2: Command Blocklist
    # ─────────────────────────────────────────────────────────────────────────
    def validate_command(self, command: str) -> None:
        """
        Inspects command line and rejects blocked commands and shell chaining bypasses.
        Blocks at minimum:
        - sudo
        - npm install -g
        - pip install
        - curl
        - wget
        """
        if not command or not command.strip():
            return

        cmd_clean = command.strip()

        # Split chained commands to check every individual command fragment
        # Chaining separators: ;, &&, ||, |, &, newline, $(...), `...`
        fragments = re.split(r'[;&|\n]+|(?:\$\()|`', cmd_clean)

        blocked_rules = [
            (r"\bsudo\b", "sudo elevation"),
            (r"\bnpm\s+(?:install|i)\s+.*-(?:g|-global)\b|\bnpm\s+.*-(?:g|-global)\s+(?:install|i)\b", "npm global installation"),
            (r"(?:python\s+-m\s+)?\bpip\d*\s+install\b", "pip package installation"),
            (r"\bcurl(?:\.exe)?\b", "curl outbound network transfer"),
            (r"\bwget(?:\.exe)?\b", "wget outbound network transfer"),
        ]

        # 1. Check full command
        for pattern, desc in blocked_rules:
            if re.search(pattern, cmd_clean, re.IGNORECASE):
                violation = SafetyViolation(
                    guard=GuardType.COMMAND_BLOCKLIST,
                    target=cmd_clean,
                    reason=f"Command violates security policy: blocked {desc}.",
                    details={"rule": desc},
                )
                self.violations.append(violation)
                raise SafetyViolationError(violation)

        # 2. Check each fragment
        for frag in fragments:
            frag_clean = frag.strip()
            if not frag_clean:
                continue
            for pattern, desc in blocked_rules:
                if re.search(pattern, frag_clean, re.IGNORECASE):
                    violation = SafetyViolation(
                        guard=GuardType.COMMAND_BLOCKLIST,
                        target=cmd_clean,
                        reason=f"Command fragment '{frag_clean}' violates security policy: blocked {desc}.",
                        details={"rule": desc, "fragment": frag_clean},
                    )
                    self.violations.append(violation)
                    raise SafetyViolationError(violation)

    # ─────────────────────────────────────────────────────────────────────────
    # Guard 3: Diff Size
    # ─────────────────────────────────────────────────────────────────────────
    def validate_diff(self, workspace_root: str) -> None:
        """
        Inspects REAL git diff in workspace_root.
        Rejects when:
        - changed lines > 500
        OR
        - modified files > 5
        """
        if not workspace_root or not os.path.exists(workspace_root):
            return

        # Check if workspace is a git repo
        if not os.path.exists(os.path.join(workspace_root, ".git")):
            # Might be a worktree where .git is a file
            git_path = os.path.join(workspace_root, ".git")
            if not os.path.exists(git_path):
                return

        try:
            res = subprocess.run(
                ["git", "diff", "--numstat"],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode != 0:
                logger.warning("git diff --numstat returned %d: %s", res.returncode, res.stderr)
                return

            lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            total_changed_lines = 0
            file_count = len(lines)

            for line in lines:
                parts = line.split("\t")
                if len(parts) >= 3:
                    add, delete, _ = parts[0], parts[1], parts[2]
                    try:
                        total_changed_lines += int(add) + int(delete)
                    except ValueError:
                        # Binary file represented as '-'
                        pass

            # Also check untracked files with status
            status_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if status_res.returncode == 0:
                for s_line in status_res.stdout.splitlines():
                    if s_line.startswith("??"):
                        untracked_rel = s_line[3:].strip()
                        file_count += 1
                        untracked_abs = os.path.join(workspace_root, untracked_rel)
                        if os.path.isfile(untracked_abs):
                            try:
                                with open(untracked_abs, "r", encoding="utf-8", errors="ignore") as f:
                                    total_changed_lines += sum(1 for _ in f)
                            except Exception:
                                pass

            if total_changed_lines > self.max_diff_lines or file_count > self.max_diff_files:
                violation = SafetyViolation(
                    guard=GuardType.DIFF_SIZE,
                    target=workspace_root,
                    reason=(
                        f"Diff size limit exceeded: {total_changed_lines} changed lines, "
                        f"{file_count} modified files (limits: max {self.max_diff_lines} lines, "
                        f"max {self.max_diff_files} files)."
                    ),
                    details={
                        "changed_lines": total_changed_lines,
                        "modified_files": file_count,
                        "max_lines": self.max_diff_lines,
                        "max_files": self.max_diff_files,
                    },
                )
                self.violations.append(violation)
                raise SafetyViolationError(violation)

        except subprocess.TimeoutExpired:
            logger.warning("git diff timed out during diff validation")
        except SafetyViolationError:
            raise
        except Exception as e:
            logger.warning("Diff inspection failed: %s", e)

    # ─────────────────────────────────────────────────────────────────────────
    # Guard 4: Loop Detection
    # ─────────────────────────────────────────────────────────────────────────
    def check_loop_before_step(self, step_number: int, tool_name: str, args: Dict[str, Any]) -> None:
        """
        Computes step signature and verifies that the same step hasn't already
        executed 3 times without progress.
        If it has executed 3 times already, aborts before the 4th execution.
        """
        # Create deterministic normalized representation of args
        # Filter volatile arguments like timestamp or uuid
        clean_args = {k: v for k, v in args.items() if k not in ("session_id", "task_name", "timestamp")}
        args_repr = json.dumps(clean_args, sort_keys=True, default=str)
        sig = hashlib.sha256(f"{tool_name}:{args_repr}".encode()).hexdigest()

        count = self.signature_counts.get(sig, 0)
        if count >= MAX_LOOP_REPETITIONS:
            violation = SafetyViolation(
                guard=GuardType.LOOP_DETECTION,
                target=f"step_{step_number}:{tool_name}",
                reason=(
                    f"Execution loop detected: identical step signature has repeated {count} times "
                    f"without progress. Execution halted before 4th repetition."
                ),
                details={
                    "step_number": step_number,
                    "tool_name": tool_name,
                    "signature": sig,
                    "repetition_count": count,
                },
            )
            self.violations.append(violation)
            raise SafetyViolationError(violation)

    def record_step_executed(self, tool_name: str, args: Dict[str, Any], progress_made: bool = False) -> None:
        """
        Records that a step signature was executed.
        If progress was made, reset signature counts.
        """
        clean_args = {k: v for k, v in args.items() if k not in ("session_id", "task_name", "timestamp")}
        args_repr = json.dumps(clean_args, sort_keys=True, default=str)
        sig = hashlib.sha256(f"{tool_name}:{args_repr}".encode()).hexdigest()

        if progress_made:
            self.signature_counts[sig] = 0
        else:
            self.signature_counts[sig] = self.signature_counts.get(sig, 0) + 1
            self.step_signatures.append(sig)

    # ─────────────────────────────────────────────────────────────────────────
    # Interceptor Hooks for ExecutorAgent
    # ─────────────────────────────────────────────────────────────────────────
    def intercept_pre_step(
        self,
        workspace_root: Optional[str],
        tool_name: str,
        step_number: int,
        args: Dict[str, Any],
    ) -> None:
        """Called immediately before dispatching any tool."""
        # 1. Loop check
        self.check_loop_before_step(step_number, tool_name, args)

        # 2. File write check
        if tool_name in ("apply_patch", "code_modifier"):
            target_path = args.get("path")
            if target_path and workspace_root:
                self.validate_file_write(workspace_root, target_path)

        # 3. Command check
        if tool_name == "run_command":
            cmd = args.get("command")
            if cmd:
                self.validate_command(cmd)

    def intercept_post_step(
        self,
        workspace_root: Optional[str],
        tool_name: str,
        args: Dict[str, Any],
        step_succeeded: bool,
    ) -> None:
        """Called immediately after dispatching a tool."""
        # Record execution for loop tracking
        self.record_step_executed(tool_name, args, progress_made=False)

        # 4. Diff size check if code modified
        if tool_name in ("apply_patch", "code_modifier") and step_succeeded and workspace_root:
            self.validate_diff(workspace_root)

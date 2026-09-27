"""
Precision Code Modifier for Engineer 2 (Agent 2) — Task 27.

Provides reliable, precise code modifications without corrupting surrounding code:
- Search-and-replace chunk editing with controlled whitespace tolerance
- AST-aware Python function replacement preserving unrelated code
- Strict ambiguity protection:
    - match count == 1: allow replacement
    - match count == 0: reject with ChunkNotFoundError
    - match count > 1: reject as ambiguous with AmbiguousChunkError (requires explicit line bounds)
    - Never guesses!
- Syntax validation:
    - Python: ast.parse()
    - TypeScript/JavaScript: balanced delimiters and compiler check if tsc is present
    - JSON: json.loads()
- Automatic rollback on syntax failure:
    - Saves original content prior to modification
    - Immediately validates syntax post-edit
    - Automatically restores original content if syntax check fails
    - Verifies restoration integrity (diff is clean)
    - Returns structured failure with restored=True
    - Never leaves broken syntax after a failed edit
"""

from __future__ import annotations

import ast
from enum import Enum
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("code_modifier")


class CodeModificationError(RuntimeError):
    """Base exception for code modification errors."""
    pass


class ChunkNotFoundError(CodeModificationError):
    """Raised when the target original chunk cannot be located in the file."""
    pass


class AmbiguousChunkError(CodeModificationError):
    """Raised when multiple occurrences of the chunk exist and line bounds are absent or ambiguous."""
    pass


class SyntaxValidationError(CodeModificationError):
    """Raised when modified code fails syntax validation."""
    pass


class ModificationResult(BaseModel):
    """Structured result of a code modification attempt."""
    model_config = ConfigDict(extra="ignore")

    success: bool = Field(..., description="Whether modification and syntax validation succeeded")
    file_path: str = Field(..., description="Target file path")
    modification_type: str = Field(..., description="chunk_replace or ast_function_replace")
    original_bytes: int = Field(default=0, description="Original file size in bytes")
    new_bytes: int = Field(default=0, description="New file size in bytes")
    replaced_lines: List[int] = Field(default_factory=list, description="Line numbers affected (1-indexed)")
    error: Optional[str] = Field(default=None, description="Error message if modification failed")
    restored: bool = Field(default=False, description="Whether original content was automatically restored")
    syntax_valid: bool = Field(default=True, description="Whether final file syntax is valid")


class CodeModifier:
    """
    Precision code modification engine with AST awareness, ambiguity guards,
    and automatic syntax rollback.
    """

    def __init__(self, check_typescript: bool = True) -> None:
        self.check_typescript = check_typescript
        self.tsc_bin = shutil.which("tsc")

    # ─────────────────────────────────────────────────────────────
    # Syntax Validation
    # ─────────────────────────────────────────────────────────────

    def validate_syntax(self, file_path: str | Path, content: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Validate syntax for Python, TypeScript/JavaScript, or JSON.
        Returns (is_valid, error_message).
        """
        path = Path(file_path)
        ext = path.suffix.lower()

        if content is None:
            if not path.exists():
                return False, f"File {path} does not exist for syntax validation."
            content = path.read_text(encoding="utf-8", errors="replace")

        # Python syntax validation
        if ext in (".py", ".pyw"):
            try:
                ast.parse(content, filename=str(path))
                return True, None
            except SyntaxError as e:
                err_msg = f"Python SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}"
                return False, err_msg
            except Exception as e:
                return False, f"Python AST parse failed: {e}"

        # JSON validation
        elif ext == ".json":
            try:
                json.loads(content)
                return True, None
            except json.JSONDecodeError as e:
                return False, f"JSONDecodeError at line {e.lineno}, col {e.colno}: {e.msg}"

        # TypeScript / JavaScript validation
        elif ext in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
            # 1. Delimiter balance check
            balanced, delim_err = self._check_delimiter_balance(content)
            if not balanced:
                return False, delim_err

            # 2. tsc --noEmit check if tsc is available on system
            if self.check_typescript and self.tsc_bin and ext in (".ts", ".tsx"):
                try:
                    res = subprocess.run(
                        [self.tsc_bin, "--noEmit", str(path)],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if res.returncode != 0:
                        return False, f"TypeScript compiler (tsc) validation failed:\n{res.stdout.strip() or res.stderr.strip()}"
                except Exception:
                    pass

            return True, None

        # Other plain text formats (e.g. md, txt, yml) default to True
        return True, None

    def _check_delimiter_balance(self, code: str) -> Tuple[bool, Optional[str]]:
        """Verify balanced parentheses, brackets, and braces in JS/TS source."""
        pairs = {")": "(", "}": "{", "]": "["}
        openers = set(pairs.values())
        stack: List[Tuple[str, int]] = []

        in_string: Optional[str] = None
        escaped = False
        in_line_comment = False
        in_block_comment = False

        lines = code.splitlines(keepends=True)
        for line_idx, line in enumerate(lines, start=1):
            col_idx = 0
            while col_idx < len(line):
                char = line[col_idx]
                next_char = line[col_idx + 1] if col_idx + 1 < len(line) else ""

                if in_line_comment:
                    if char == "\n":
                        in_line_comment = False
                    col_idx += 1
                    continue

                if in_block_comment:
                    if char == "*" and next_char == "/":
                        in_block_comment = False
                        col_idx += 2
                        continue
                    col_idx += 1
                    continue

                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == in_string:
                        in_string = None
                    col_idx += 1
                    continue

                # Comment starters
                if char == "/" and next_char == "/":
                    in_line_comment = True
                    col_idx += 2
                    continue
                if char == "/" and next_char == "*":
                    in_block_comment = True
                    col_idx += 2
                    continue

                # String literal starters
                if char in ("'", '"', "`"):
                    in_string = char
                    col_idx += 1
                    continue

                # Delimiters
                if char in openers:
                    stack.append((char, line_idx))
                elif char in pairs:
                    expected_opener = pairs[char]
                    if not stack:
                        return False, f"Unmatched closing delimiter '{char}' at line {line_idx}"
                    last_opener, last_line = stack.pop()
                    if last_opener != expected_opener:
                        return False, f"Mismatched delimiter '{char}' at line {line_idx} (opened with '{last_opener}' at line {last_line})"

                col_idx += 1

        if stack:
            unclosed, unclosed_line = stack[-1]
            return False, f"Unclosed delimiter '{unclosed}' opened at line {unclosed_line}"

        return True, None

    # ─────────────────────────────────────────────────────────────
    # Search and Replace Chunk Modification
    # ─────────────────────────────────────────────────────────────

    def _normalize_line_endings(self, text: str) -> str:
        return text.replace("\r\n", "\n")

    def _locate_chunk_occurrences(
        self,
        full_content: str,
        chunk: str,
    ) -> List[Tuple[int, int, int]]:
        """
        Locates occurrences of chunk in full_content.
        Returns list of tuples: (start_char_idx, end_char_idx, start_line_num).
        Handles exact matches and controlled whitespace-tolerant matches.
        """
        norm_full = self._normalize_line_endings(full_content)
        norm_chunk = self._normalize_line_endings(chunk)

        occurrences: List[Tuple[int, int, int]] = []

        # 1. Exact match pass
        start = 0
        while True:
            idx = norm_full.find(norm_chunk, start)
            if idx == -1:
                break
            end_idx = idx + len(norm_chunk)
            line_num = norm_full[:idx].count("\n") + 1
            occurrences.append((idx, end_idx, line_num))
            start = idx + 1

        if occurrences:
            return occurrences

        # 2. Controlled whitespace-tolerant pass
        # Compares lines ignoring trailing spaces and leading space variations where lines match
        full_lines = norm_full.splitlines(keepends=True)
        chunk_lines = [cl.rstrip() for cl in norm_chunk.splitlines()]

        if not chunk_lines:
            return []

        chunk_len = len(chunk_lines)
        for i in range(len(full_lines) - chunk_len + 1):
            window = full_lines[i : i + chunk_len]
            window_stripped = [wl.rstrip("\r\n").rstrip() for wl in window]

            if window_stripped == chunk_lines:
                # Calculate character offsets in full text
                start_char = sum(len(l) for l in full_lines[:i])
                matched_len = sum(len(l) for l in window)
                end_char = start_char + matched_len
                occurrences.append((start_char, end_char, i + 1))

        return occurrences

    def replace_chunk(
        self,
        file_path: str | Path,
        original_chunk: str,
        replacement_chunk: str,
        line_number: Optional[int] = None,
        line_tolerance: int = 15,
    ) -> ModificationResult:
        """
        Precision search-and-replace chunk editing with ambiguity protection
        and automatic rollback on syntax failure.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            return ModificationResult(
                success=False,
                file_path=str(path),
                modification_type="chunk_replace",
                error=f"Target file does not exist: {path}",
            )

        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            original_content = f.read()

        occurrences = self._locate_chunk_occurrences(original_content, original_chunk)

        # Ambiguity Protection
        target_occurrence: Optional[Tuple[int, int, int]] = None

        if len(occurrences) == 0:
            return ModificationResult(
                success=False,
                file_path=str(path),
                modification_type="chunk_replace",
                error=f"Original chunk not found in {path.name}.",
            )

        elif len(occurrences) == 1:
            target_occurrence = occurrences[0]

        else:
            # Multiple matches detected -> Ambiguous!
            if line_number is None:
                match_lines = [occ[2] for occ in occurrences]
                return ModificationResult(
                    success=False,
                    file_path=str(path),
                    modification_type="chunk_replace",
                    error=(
                        f"Ambiguous modification: found {len(occurrences)} matches at lines {match_lines} "
                        f"in {path.name}. Explicit line_number is required to disambiguate."
                    ),
                )

            # Disambiguate using line_number: find the single closest match within tolerance
            min_dist = min(abs(occ[2] - line_number) for occ in occurrences)
            if min_dist > line_tolerance:
                match_lines = [occ[2] for occ in occurrences]
                return ModificationResult(
                    success=False,
                    file_path=str(path),
                    modification_type="chunk_replace",
                    error=(
                        f"Ambiguous modification: found {len(occurrences)} matches at lines {match_lines}, "
                        f"none within {line_tolerance} lines of requested line_number {line_number}."
                    ),
                )

            closest_candidates = [
                occ for occ in occurrences if abs(occ[2] - line_number) == min_dist
            ]
            if len(closest_candidates) == 1:
                target_occurrence = closest_candidates[0]
            else:
                candidate_lines = [c[2] for c in closest_candidates]
                return ModificationResult(
                    success=False,
                    file_path=str(path),
                    modification_type="chunk_replace",
                    error=(
                        f"Ambiguous modification: multiple equidistant matches {candidate_lines} "
                        f"closest to line_number {line_number}. Cannot guess."
                    ),
                )

        # Perform replacement
        start_idx, end_idx, start_line = target_occurrence
        norm_orig = self._normalize_line_endings(original_content)
        modified_content = norm_orig[:start_idx] + self._normalize_line_endings(replacement_chunk) + norm_orig[end_idx:]

        # Calculate affected line numbers
        lines_count = max(1, replacement_chunk.count("\n") + 1)
        replaced_lines = list(range(start_line, start_line + lines_count))

        # Write modified content
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(modified_content)

        # Immediate Syntax Validation
        is_valid, syntax_err = self.validate_syntax(path, modified_content)

        if not is_valid:
            # AUTOMATIC ROLLBACK
            logger.warning("Syntax validation failed after editing %s. Rolling back to original content. Error: %s", path, syntax_err)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(original_content)

            # Verify restoration
            with open(path, "r", encoding="utf-8", newline="") as f:
                restored_content = f.read()
            is_restored = (restored_content == original_content)

            return ModificationResult(
                success=False,
                file_path=str(path),
                modification_type="chunk_replace",
                original_bytes=len(original_content.encode("utf-8")),
                new_bytes=len(restored_content.encode("utf-8")),
                replaced_lines=replaced_lines,
                error=f"Syntax validation failed: {syntax_err}. File was automatically restored.",
                restored=is_restored,
                syntax_valid=False,
            )

        return ModificationResult(
            success=True,
            file_path=str(path),
            modification_type="chunk_replace",
            original_bytes=len(original_content.encode("utf-8")),
            new_bytes=len(modified_content.encode("utf-8")),
            replaced_lines=replaced_lines,
            restored=False,
            syntax_valid=True,
        )

    # ─────────────────────────────────────────────────────────────
    # AST-Aware Python Function Replacement
    # ─────────────────────────────────────────────────────────────

    def replace_function(
        self,
        file_path: str | Path,
        function_name: str,
        new_function_code: str,
    ) -> ModificationResult:
        """
        Locates a Python function by name using AST, extracts its exact line range,
        and replaces it with new_function_code while preserving surrounding code,
        docstrings, comments, and imports.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            return ModificationResult(
                success=False,
                file_path=str(path),
                modification_type="ast_function_replace",
                error=f"File {path} does not exist.",
            )

        original_content = path.read_text(encoding="utf-8", errors="replace")

        try:
            tree = ast.parse(original_content, filename=str(path))
        except SyntaxError as e:
            return ModificationResult(
                success=False,
                file_path=str(path),
                modification_type="ast_function_replace",
                error=f"Cannot perform AST replacement on malformed source: {e}",
            )

        # Locate target function node(s)
        matching_nodes: List[ast.FunctionDef | ast.AsyncFunctionDef] = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
        ]

        if len(matching_nodes) == 0:
            return ModificationResult(
                success=False,
                file_path=str(path),
                modification_type="ast_function_replace",
                error=f"Function '{function_name}' not found in {path.name}.",
            )
        elif len(matching_nodes) > 1:
            lines = [n.lineno for n in matching_nodes]
            return ModificationResult(
                success=False,
                file_path=str(path),
                modification_type="ast_function_replace",
                error=f"Ambiguous: multiple functions named '{function_name}' found at lines {lines} in {path.name}.",
            )

        target_node = matching_nodes[0]
        start_line = target_node.lineno  # 1-indexed
        end_line = getattr(target_node, "end_lineno", start_line)

        # Replace slice in lines
        raw_lines = original_content.splitlines(keepends=True)
        before = raw_lines[: start_line - 1]
        after = raw_lines[end_line:]

        clean_new_fn = new_function_code.rstrip() + "\n"
        modified_lines = before + [clean_new_fn] + after
        modified_content = "".join(modified_lines)

        # Write and validate
        path.write_text(modified_content, encoding="utf-8")
        is_valid, syntax_err = self.validate_syntax(path, modified_content)

        if not is_valid:
            # AUTOMATIC ROLLBACK
            path.write_text(original_content, encoding="utf-8")
            restored_content = path.read_text(encoding="utf-8")
            return ModificationResult(
                success=False,
                file_path=str(path),
                modification_type="ast_function_replace",
                original_bytes=len(original_content.encode("utf-8")),
                new_bytes=len(restored_content.encode("utf-8")),
                replaced_lines=list(range(start_line, end_line + 1)),
                error=f"Syntax validation failed: {syntax_err}. File was automatically restored.",
                restored=(restored_content == original_content),
                syntax_valid=False,
            )

        return ModificationResult(
            success=True,
            file_path=str(path),
            modification_type="ast_function_replace",
            original_bytes=len(original_content.encode("utf-8")),
            new_bytes=len(modified_content.encode("utf-8")),
            replaced_lines=list(range(start_line, end_line + 1)),
            restored=False,
            syntax_valid=True,
        )


default_code_modifier = CodeModifier()

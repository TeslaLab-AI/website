"""Turn deployment/build logs into structured failures with a recovery hint.

    failure = primary_failure(log_text)
    failure.kind       -> FailureKind.MISSING_ENV
    failure.category   -> "Environment"  (same names as the Maintenance Engine's classifier)
    failure.recovery   -> Recovery.SET_ENV
    failure.fix_owner  -> "user" | "deploy" | "build"  (who can fix it)
    failure.variables  -> ("DATABASE_URL",)

fix_owner tells the pipeline who acts next:
  "deploy" - the Deployment Engine fixes it by changing config (no code edit)
  "user"   - needs a value only the user has (e.g. a secret)
  "build"  - needs a code change, so it goes to the Build Engine's fix loop

Safety: logs can be huge and can contain secrets, so input is size-capped, every
line is length-capped (keeps regexes fast), and evidence is masked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional

from .env_detector import BUILTIN_NAMES, BUILTIN_PREFIXES
from .log_masking import mask_secrets

MAX_LOG_CHARS = 400_000
MAX_LINE_CHARS = 2000
MAX_EVIDENCE_CHARS = 300
MAX_VARIABLES = 20


class FailureKind(str, Enum):
    MISSING_ENV = "MISSING_ENV"
    NODE_VERSION = "NODE_VERSION"
    BUILD_SCRIPT = "BUILD_SCRIPT"
    OUTPUT_DIRECTORY = "OUTPUT_DIRECTORY"
    DEPENDENCY = "DEPENDENCY"
    DATABASE = "DATABASE"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    PORT = "PORT"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class Recovery(str, Enum):
    SET_ENV = "SET_ENV"
    SET_NODE_VERSION = "SET_NODE_VERSION"
    SET_OUTPUT_DIRECTORY = "SET_OUTPUT_DIRECTORY"
    USE_FALLBACK_BUILD_COMMAND = "USE_FALLBACK_BUILD_COMMAND"
    FIX_DEPENDENCIES = "FIX_DEPENDENCIES"
    FIX_CODE = "FIX_CODE"
    CHECK_DATABASE = "CHECK_DATABASE"
    FIX_PORT = "FIX_PORT"
    RAISE_RESOURCES = "RAISE_RESOURCES"
    RETRY = "RETRY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class Failure:
    kind: FailureKind
    category: str  # Syntax | Dependency | Runtime | Database | Environment
    severity: Severity
    summary: str
    hint: str
    evidence: str  # the matching log line, masked
    recovery: Recovery
    fix_owner: str  # "deploy" | "user" | "build"
    variables: tuple[str, ...] = ()
    detail: str = ""  # e.g. required Node major, module name, file:line


@dataclass(frozen=True)
class _Rule:
    kind: FailureKind
    category: str
    recovery: Recovery
    fix_owner: str
    hint: str
    patterns: tuple[re.Pattern, ...]
    severity: Severity = Severity.BLOCKER


def _p(*patterns: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p) for p in patterns)


# Order = priority: the first rules are the most likely ROOT causes.
_RULES: tuple[_Rule, ...] = (
    _Rule(
        FailureKind.MISSING_ENV, "Environment", Recovery.SET_ENV, "user",
        "Add the missing environment variables to the project's secrets, then redeploy.",
        _p(
            r"(?i)environment variables?[^\n]{0,40}(?:not found|missing|not set|is required|are required|undefined|not defined)",
            r"(?i)(?:missing|undefined|invalid|required|unset)[^\n]{0,30}environment variables?",
            r"(?i)process\.env\.[A-Z0-9_]+ (?:is|was) (?:undefined|not defined|missing)",
            r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+ (?:is|are) (?:not set|required|missing|undefined|not defined)\b",
            r"(?i)\bsupabase(?:url|key) is required",
        ),
    ),
    _Rule(
        FailureKind.NODE_VERSION, "Environment", Recovery.SET_NODE_VERSION, "deploy",
        "Set node_version in deploy.json (and engines.node in package.json) to a supported version.",
        _p(
            r"(?i)the engine [\"']?node[\"']? is incompatible",
            r"(?i)you are using node(?:\.js)?[^\n]{0,80}required",
            r"(?i)node(?:\.js)? version[^\n]{0,30}(?:discontinued|not supported|no longer supported|must be upgraded)",
            r"(?i)requires node(?:\.js)?[^\n]{0,20}[><=^~]+\s*\d+",
        ),
    ),
    _Rule(
        FailureKind.BUILD_SCRIPT, "Environment", Recovery.USE_FALLBACK_BUILD_COMMAND, "deploy",
        "package.json has no 'build' script. Use 'npx next build' or add the script.",
        _p(
            r"(?i)missing script:?\s*[\"']?build",
            r"(?i)command [\"']?build[\"']? not found",
            r"(?i)no script (?:named|called) [\"']?build",
        ),
    ),
    _Rule(
        FailureKind.OUTPUT_DIRECTORY, "Environment", Recovery.SET_OUTPUT_DIRECTORY, "deploy",
        "The build did not produce the configured output directory. Set output_directory in deploy.json (.next for Next.js).",
        _p(r"(?i)no output directory named [\"']?([^\"'\n]{1,80})[\"']? found"),
    ),
    _Rule(
        FailureKind.DEPENDENCY, "Dependency", Recovery.FIX_DEPENDENCIES, "build",
        "A package or import could not be resolved. Install the dependency or fix the import path.",
        _p(
            r"Module not found: (?:Error: )?Can't resolve ['\"]([^'\"\n]{1,120})['\"]",
            r"(?i)cannot find module ['\"]([^'\"\n]{1,120})['\"]",
            r"(?i)npm (?:error|err!) (?:code )?(?:E404|ERESOLVE|ETARGET|notarget)\b",
            r"(?i)unable to resolve dependency tree",
            r"(?i)npm (?:error|err!) 404 not found",
        ),
    ),
    _Rule(
        FailureKind.DATABASE, "Database", Recovery.CHECK_DATABASE, "user",
        "The database could not be reached or is missing tables. Check the connection URL and run migrations.",
        _p(
            r"(?i)can'?t reach database server",
            r"(?i)password authentication failed",
            r"(?i)econnrefused[^\n]{0,40}:5432",
            r"(?i)relation [\"'][^\"'\n]+[\"'] does not exist",
        ),
    ),
    _Rule(
        FailureKind.SYNTAX_ERROR, "Syntax", Recovery.FIX_CODE, "build",
        "The code has a syntax error. The Build Engine should fix the file shown.",
        _p(
            r"\bSyntaxError\b",
            r"(?i)parsing (?:ecmascript|javascript|typescript) source code failed",
            r"(?i)\bunexpected token\b",
            r"(?i)unterminated (?:string|template|regular expression)",
        ),
    ),
    _Rule(
        FailureKind.TYPE_ERROR, "Syntax", Recovery.FIX_CODE, "build",
        "TypeScript found a type error. The Build Engine should fix the file shown.",
        _p(r"(?m)^\s*Type error: ", r"\berror TS\d{4}\b"),
    ),
    _Rule(
        FailureKind.PORT, "Runtime", Recovery.FIX_PORT, "build",
        "The app must listen on the port given by the platform (process.env.PORT) and the port must be free.",
        _p(
            r"\bEADDRINUSE\b",
            r"(?i)address already in use",
            r"(?i)no open ports detected",
            r"(?i)failed to bind to \$?port",
        ),
    ),
    _Rule(
        FailureKind.OUT_OF_MEMORY, "Runtime", Recovery.RAISE_RESOURCES, "deploy",
        "The build ran out of memory. Increase the build memory limit or reduce the build size.",
        _p(
            r"(?i)javascript heap out of memory",
            r"(?i)reached heap limit",
            r"(?i)exit(?:ed with)? code 137\b",
            r"(?i)\bout of memory\b",
        ),
    ),
    _Rule(
        FailureKind.TIMEOUT, "Runtime", Recovery.RETRY, "deploy",
        "The build or deployment timed out. Retry; if it repeats, the build is too slow.",
        _p(
            r"(?i)build exceeded (?:the )?maximum (?:build )?(?:time|duration)",
            r"(?i)build timed out",
            r"(?i)deployment (?:has )?timed out",
            r"(?i)\bETIMEDOUT\b",
            r"(?i)timed out waiting for deployment",
        ),
        severity=Severity.MAJOR,
    ),
)

_VAR_NAME = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_BULLET_VAR = re.compile(r"^\s*[-*\u2022]?\s*([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b")
_NODE_REQUIREMENT = re.compile(r"[><=^~]=?\s*(\d+)")
_FILE_LINE = re.compile(r"((?:\./|/)?[\w@./\-\[\]()]{1,200}\.(?:tsx?|jsx?|mjs|cjs)):(\d+)(?::\d+)?")
_SUPABASE_VARS = {
    "supabaseurl": "NEXT_PUBLIC_SUPABASE_URL",
    "supabasekey": "NEXT_PUBLIC_SUPABASE_ANON_KEY",
}


def _is_builtin(name: str) -> bool:
    return name in BUILTIN_NAMES or name.startswith(BUILTIN_PREFIXES)


def _prepare(text: str) -> str:
    text = (text or "")[-MAX_LOG_CHARS:]
    return "\n".join(line[:MAX_LINE_CHARS] for line in text.splitlines())


def _line_bounds(text: str, match: re.Match) -> tuple[int, int]:
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    return start, (len(text) if end == -1 else end)


def _evidence(text: str, match: re.Match) -> str:
    start, end = _line_bounds(text, match)
    return mask_secrets(text[start:end].strip())[:MAX_EVIDENCE_CHARS]


def _env_variables(text: str, rule: _Rule) -> tuple[str, ...]:
    found: list[str] = []
    lines = text.split("\n")
    for pattern in rule.patterns:
        for match in pattern.finditer(text):
            start, end = _line_bounds(text, match)
            line = text[start:end]
            for name in _VAR_NAME.findall(line):
                found.append(name)
            lowered = line.lower()
            for key, var in _SUPABASE_VARS.items():
                if key in lowered:
                    found.append(var)
            # Variables listed on the lines after the message ("  - DATABASE_URL").
            line_no = text.count("\n", 0, start)
            for follow in lines[line_no + 1 : line_no + 9]:
                bullet = _BULLET_VAR.match(follow)
                if bullet:
                    found.append(bullet.group(1))
                elif follow.strip():
                    break
    unique: list[str] = []
    for name in found:
        if name not in unique and not _is_builtin(name):
            unique.append(name)
    return tuple(unique[:MAX_VARIABLES])


def _node_requirement(text: str, match: re.Match) -> str:
    start, end = _line_bounds(text, match)
    found = _NODE_REQUIREMENT.search(text[start:end])
    return found.group(1) if found else ""


def _file_line(text: str) -> str:
    found = _FILE_LINE.search(text)
    if not found:
        return ""
    path = found.group(1)
    while path.startswith("./"):
        path = path[2:]
    return f"{path}:{found.group(2)}"


def _summary(rule: _Rule, variables: tuple[str, ...], detail: str) -> str:
    kind = rule.kind
    if kind == FailureKind.MISSING_ENV:
        return "Missing environment variables: " + ", ".join(variables) if variables else "Missing environment variables"
    if kind == FailureKind.NODE_VERSION:
        return f"Unsupported Node.js version (needs {detail}+)" if detail else "Unsupported Node.js version"
    if kind == FailureKind.BUILD_SCRIPT:
        return "No 'build' script found"
    if kind == FailureKind.OUTPUT_DIRECTORY:
        return f"Output directory '{detail}' was not produced" if detail else "Output directory not found"
    if kind == FailureKind.DEPENDENCY:
        return f"Dependency problem: {detail}" if detail else "Dependency installation or resolution failed"
    if kind == FailureKind.DATABASE:
        return "Database connection or schema problem"
    if kind == FailureKind.SYNTAX_ERROR:
        return f"Syntax error in {detail}" if detail else "Syntax error in the code"
    if kind == FailureKind.TYPE_ERROR:
        return f"Type error in {detail}" if detail else "TypeScript type error"
    if kind == FailureKind.PORT:
        return "Port problem (in use, or the app is not listening on the platform's port)"
    if kind == FailureKind.OUT_OF_MEMORY:
        return "Build ran out of memory"
    return "Build or deployment timed out"


def classify_failures(log_text: str) -> list[Failure]:
    """Every failure found in the log, most likely root cause first."""
    text = _prepare(log_text)
    failures: list[Failure] = []
    for rule in _RULES:
        first: Optional[re.Match] = None
        for pattern in rule.patterns:
            found = pattern.search(text)
            if found and (first is None or found.start() < first.start()):
                first = found
        if first is None:
            continue

        variables: tuple[str, ...] = ()
        detail = ""
        if rule.kind == FailureKind.MISSING_ENV:
            variables = _env_variables(text, rule)
        elif rule.kind == FailureKind.NODE_VERSION:
            detail = _node_requirement(text, first)
        elif rule.kind == FailureKind.BUILD_SCRIPT:
            detail = "build"
        elif rule.kind in (FailureKind.OUTPUT_DIRECTORY, FailureKind.DEPENDENCY) and first.groups():
            detail = mask_secrets(first.group(1))
        elif rule.kind in (FailureKind.SYNTAX_ERROR, FailureKind.TYPE_ERROR):
            detail = _file_line(text)

        failures.append(
            Failure(
                kind=rule.kind,
                category=rule.category,
                severity=rule.severity,
                summary=_summary(rule, variables, detail),
                hint=rule.hint,
                evidence=_evidence(text, first),
                recovery=rule.recovery,
                fix_owner=rule.fix_owner,
                variables=variables,
                detail=detail,
            )
        )
    return failures


def _unknown_failure(text: str) -> Failure:
    evidence = ""
    for line in reversed(text.split("\n")):
        if re.search(r"(?i)\b(error|failed|fatal)\b", line):
            evidence = mask_secrets(line.strip())[:MAX_EVIDENCE_CHARS]
            break
    return Failure(
        kind=FailureKind.UNKNOWN,
        category="Runtime",
        severity=Severity.MAJOR,
        summary="Deployment failed for an unrecognized reason",
        hint="Review the deployment logs. This failure needs a human or a deeper analysis.",
        evidence=evidence,
        recovery=Recovery.ESCALATE,
        fix_owner="user",
    )


def primary_failure(log_text: str) -> Failure:
    """The most likely root cause, or an UNKNOWN failure if nothing matched."""
    failures = classify_failures(log_text)
    return failures[0] if failures else _unknown_failure(_prepare(log_text))


def missing_env_failure(names: Iterable[str]) -> Failure:
    """Failure for variables found missing BEFORE deploying (saves a wasted build)."""
    variables = tuple(sorted(set(names)))
    rule = _RULES[0]
    return Failure(
        kind=FailureKind.MISSING_ENV,
        category=rule.category,
        severity=Severity.BLOCKER,
        summary=_summary(rule, variables, ""),
        hint=rule.hint,
        evidence="",
        recovery=Recovery.SET_ENV,
        fix_owner="user",
        variables=variables,
    )


def timeout_failure(waited_seconds: float) -> Failure:
    rule = _RULES[-1]
    return Failure(
        kind=FailureKind.TIMEOUT,
        category=rule.category,
        severity=rule.severity,
        summary=f"Deployment did not finish within {int(waited_seconds)} seconds",
        hint=rule.hint,
        evidence="",
        recovery=Recovery.RETRY,
        fix_owner="deploy",
    )
import time

import pytest

from deployment.failure_classifier import (
    FailureKind,
    Recovery,
    Severity,
    classify_failures,
    missing_env_failure,
    primary_failure,
    timeout_failure,
)


# -- missing environment variables -------------------------------------------
def test_prisma_style_missing_variable():
    failure = primary_failure("Error: Environment variable not found: DATABASE_URL.")
    assert failure.kind == FailureKind.MISSING_ENV
    assert failure.category == "Environment"
    assert failure.variables == ("DATABASE_URL",)
    assert failure.recovery == Recovery.SET_ENV
    assert failure.fix_owner == "user"
    assert failure.severity == Severity.BLOCKER
    assert "DATABASE_URL" in failure.summary


def test_variables_listed_on_following_lines():
    log = "Error: Missing required environment variables:\n  - DATABASE_URL\n  - STRIPE_SECRET_KEY\nBuild failed"
    assert primary_failure(log).variables == ("DATABASE_URL", "STRIPE_SECRET_KEY")


def test_x_is_required_style():
    failure = primary_failure("Error: STRIPE_SECRET_KEY is required")
    assert failure.kind == FailureKind.MISSING_ENV
    assert failure.variables == ("STRIPE_SECRET_KEY",)


def test_supabase_client_error_maps_to_supabase_variables():
    failure = primary_failure("Error: supabaseUrl is required.")
    assert failure.kind == FailureKind.MISSING_ENV
    assert "NEXT_PUBLIC_SUPABASE_URL" in failure.variables


def test_platform_variables_are_not_reported_as_missing():
    failure = primary_failure("Invalid environment variables: NODE_ENV is required, MY_API_KEY is required")
    assert failure.variables == ("MY_API_KEY",)


# -- node version --------------------------------------------------------------
def test_engine_incompatible_with_required_version():
    log = 'npm error The engine "node" is incompatible with this module. Expected version ">=20.9.0". Got "18.17.0"'
    failure = primary_failure(log)
    assert failure.kind == FailureKind.NODE_VERSION
    assert failure.detail == "20"
    assert failure.recovery == Recovery.SET_NODE_VERSION
    assert failure.fix_owner == "deploy"


def test_nextjs_node_version_message():
    log = 'You are using Node.js 18.17.0. For Next.js, Node.js version ">=20.9.0" is required.'
    failure = primary_failure(log)
    assert failure.kind == FailureKind.NODE_VERSION and failure.detail == "20"


def test_discontinued_node_version_has_no_detail():
    failure = primary_failure('Error: Node.js Version "14.x" is discontinued and must be upgraded.')
    assert failure.kind == FailureKind.NODE_VERSION
    assert failure.detail == ""


# -- build script / output directory --------------------------------------------
@pytest.mark.parametrize("log", ['npm error Missing script: "build"', "npm ERR! missing script: build", 'error Command "build" not found.'])
def test_missing_build_script(log):
    failure = primary_failure(log)
    assert failure.kind == FailureKind.BUILD_SCRIPT
    assert failure.recovery == Recovery.USE_FALLBACK_BUILD_COMMAND
    assert failure.fix_owner == "deploy"


def test_missing_output_directory():
    failure = primary_failure('Error: No Output Directory named "public" found after the Build completed.')
    assert failure.kind == FailureKind.OUTPUT_DIRECTORY
    assert failure.detail == "public"
    assert failure.recovery == Recovery.SET_OUTPUT_DIRECTORY


# -- dependencies --------------------------------------------------------------
def test_module_not_found():
    failure = primary_failure("Module not found: Can't resolve 'framer-motion' in '/vercel/path0/app'")
    assert failure.kind == FailureKind.DEPENDENCY
    assert failure.detail == "framer-motion"
    assert failure.fix_owner == "build"
    assert failure.category == "Dependency"


@pytest.mark.parametrize("log", [
    "npm error code ERESOLVE\nnpm error ERESOLVE unable to resolve dependency tree",
    "npm error 404 Not Found - GET https://registry.npmjs.org/no-such-package",
    "Error: Cannot find module 'left-pad'",
])
def test_other_dependency_problems(log):
    assert primary_failure(log).kind == FailureKind.DEPENDENCY


# -- code errors ----------------------------------------------------------------
def test_type_error_with_file_and_line():
    log = "Failed to compile.\n\n./app/page.tsx:12:5\nType error: Property 'x' does not exist on type 'Props'."
    failure = primary_failure(log)
    assert failure.kind == FailureKind.TYPE_ERROR
    assert failure.detail == "app/page.tsx:12"
    assert failure.category == "Syntax"
    assert failure.fix_owner == "build"


def test_syntax_error():
    log = "./components/Hero.jsx:7:3\nParsing ecmascript source code failed\nUnexpected token `}`"
    failure = primary_failure(log)
    assert failure.kind == FailureKind.SYNTAX_ERROR
    assert failure.detail == "components/Hero.jsx:7"


# -- runtime / resources ---------------------------------------------------------
def test_port_in_use():
    assert primary_failure("Error: listen EADDRINUSE: address already in use :::3000").kind == FailureKind.PORT


def test_out_of_memory():
    log = "FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory"
    assert primary_failure(log).kind == FailureKind.OUT_OF_MEMORY


def test_timeout_is_a_major_retry():
    failure = primary_failure("Error: Build exceeded maximum duration of 45 minutes")
    assert failure.kind == FailureKind.TIMEOUT
    assert failure.recovery == Recovery.RETRY
    assert failure.severity == Severity.MAJOR


def test_database_problems():
    failure = primary_failure("Error: Can't reach database server at `db.example.com:5432`")
    assert failure.kind == FailureKind.DATABASE
    assert failure.category == "Database"


# -- priority, unknown, safety --------------------------------------------------
def test_root_cause_comes_first_when_several_failures_match():
    log = (
        "Error: Environment variable not found: DATABASE_URL.\n"
        "Type error: Cannot find name 'db'.\n"
        "Build failed"
    )
    kinds = [f.kind for f in classify_failures(log)]
    assert kinds[0] == FailureKind.MISSING_ENV
    assert FailureKind.TYPE_ERROR in kinds
    assert primary_failure(log).kind == FailureKind.MISSING_ENV


def test_unknown_failure_falls_back_to_escalate_with_last_error_line():
    failure = primary_failure("Installing...\nSomething odd\nError: the flux capacitor overloaded")
    assert failure.kind == FailureKind.UNKNOWN
    assert failure.recovery == Recovery.ESCALATE
    assert failure.severity == Severity.MAJOR
    assert "flux capacitor" in failure.evidence


def test_empty_or_none_logs_are_unknown_not_a_crash():
    assert primary_failure("").kind == FailureKind.UNKNOWN
    assert primary_failure(None).kind == FailureKind.UNKNOWN


def test_secrets_in_evidence_are_masked():
    token = "ghp_" + "a1B2c3D4e5" * 4
    failure = primary_failure(f"Error: Environment variable not found: API_KEY, token={token}")
    assert token not in failure.evidence
    assert "REDACTED" in failure.evidence


def test_huge_and_pathological_logs_are_handled_quickly():
    huge = ("a.b" * 200_000) + "\n" + ("x" * 500_000) + "\nError: Environment variable not found: DATABASE_URL"
    started = time.monotonic()
    failure = primary_failure(huge)
    assert time.monotonic() - started < 5
    assert failure.kind == FailureKind.MISSING_ENV


# -- helpers --------------------------------------------------------------------
def test_missing_env_failure_helper_for_preflight():
    failure = missing_env_failure(["B_VAR", "A_VAR", "A_VAR"])
    assert failure.kind == FailureKind.MISSING_ENV
    assert failure.variables == ("A_VAR", "B_VAR")
    assert failure.summary == "Missing environment variables: A_VAR, B_VAR"


def test_timeout_failure_helper():
    failure = timeout_failure(900)
    assert failure.kind == FailureKind.TIMEOUT
    assert "900" in failure.summary
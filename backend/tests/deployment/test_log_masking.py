import io
import logging

import pytest

from app.deployment.log_masking import REDACTED, install_log_masking, mask_secrets

GH_PAT = "github_pat_" + "A1b2C3d4E5" * 6
GH_CLASSIC = "ghp_" + "a1B2c3D4e5" * 4


@pytest.fixture
def captured():
    uninstall = install_log_masking()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("teslalab.test.masking")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    yield logger, stream
    logger.removeHandler(handler)
    uninstall()


def test_masks_github_tokens_in_message(captured):
    logger, stream = captured
    logger.info("using token %s and %s", GH_PAT, GH_CLASSIC)
    out = stream.getvalue()
    assert GH_PAT not in out and GH_CLASSIC not in out
    assert REDACTED in out


def test_masks_tokens_in_f_strings(captured):
    logger, stream = captured
    logger.info(f"cloning with {GH_CLASSIC}")
    assert GH_CLASSIC not in stream.getvalue()


def test_masks_tokens_in_exception_traces(captured):
    logger, stream = captured
    try:
        raise RuntimeError(f"auth failed for {GH_PAT}")
    except RuntimeError:
        logger.exception("push failed")
    out = stream.getvalue()
    assert GH_PAT not in out
    assert "push failed" in out


def test_masks_authorization_headers():
    assert "abc123secret" not in mask_secrets("Authorization: Bearer abc123secret")
    assert "dXNlcjpwYXNz" not in mask_secrets("authorization: Basic dXNlcjpwYXNz")


def test_masks_url_credentials():
    out = mask_secrets("https://x-access-token:supersecret@github.com/org/repo.git")
    assert "supersecret" not in out
    assert "github.com/org/repo.git" in out


def test_masks_sensitive_key_value_pairs():
    for text in ["api_key=abc999", "DATABASE_PASSWORD: hunter2", "client_secret='zzz111'"]:
        out = mask_secrets(text)
        assert REDACTED in out
        assert not any(s in out for s in ("abc999", "hunter2", "zzz111"))


def test_normal_messages_are_unchanged():
    msg = "Deployment ready at https://proj1.teslalab.dev (build 42s)"
    assert mask_secrets(msg) == msg

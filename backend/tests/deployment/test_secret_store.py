import pytest

from app.deployment.secret_store import (
    ENV_VAR,
    DecryptionError,
    SecretsConfigError,
    decrypt,
    encrypt,
    generate_key,
)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(ENV_VAR, generate_key())


def test_round_trip():
    assert decrypt(encrypt("ghp_example_secret")) == "ghp_example_secret"


def test_ciphertext_is_not_plaintext():
    assert "my-secret-value" not in encrypt("my-secret-value")


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv(ENV_VAR)
    with pytest.raises(SecretsConfigError):
        encrypt("x")


def test_invalid_key_error_does_not_leak_key(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "not-a-valid-key-123")
    with pytest.raises(SecretsConfigError) as exc:
        encrypt("x")
    assert "not-a-valid-key-123" not in str(exc.value)


def test_wrong_key_cannot_decrypt(monkeypatch):
    ciphertext = encrypt("secret")
    monkeypatch.setenv(ENV_VAR, generate_key())
    with pytest.raises(DecryptionError):
        decrypt(ciphertext)


def test_key_rotation_old_data_still_decrypts(monkeypatch):
    import os

    old_key = os.environ[ENV_VAR]
    ciphertext = encrypt("secret")
    new_key = generate_key()
    monkeypatch.setenv(ENV_VAR, f"{new_key},{old_key}")
    assert decrypt(ciphertext) == "secret"
    # New data is encrypted with the new key only.
    monkeypatch.setenv(ENV_VAR, new_key)
    assert decrypt(encrypt("fresh")) == "fresh"

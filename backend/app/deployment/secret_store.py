"""Encryption helpers for tokens and per-project secrets (Fernet).

The key comes from the TOKEN_ENCRYPTION_KEY environment variable and must
never be committed to git. Generate one with:

    python -c "from deployment.secret_store import generate_key; print(generate_key())"

Key rotation: set TOKEN_ENCRYPTION_KEY to a comma-separated list, newest key
first. New data is encrypted with the first key; old data still decrypts.

Rules:
- Never log plaintext secrets or the key itself.
- Store only the ciphertext (value_encrypted) in the database.
- Decrypt as late as possible (at deploy time) and never write it to the repo.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

ENV_VAR = "TOKEN_ENCRYPTION_KEY"


class SecretsConfigError(RuntimeError):
    """The encryption key is missing or malformed."""


class DecryptionError(Exception):
    """Ciphertext could not be decrypted (wrong key or corrupted data)."""


def generate_key() -> str:
    return Fernet.generate_key().decode()


def _cipher() -> MultiFernet:
    raw = os.environ.get(ENV_VAR, "").strip()
    if not raw:
        raise SecretsConfigError(f"{ENV_VAR} is not set")
    try:
        keys = [Fernet(k.strip().encode()) for k in raw.split(",") if k.strip()]
    except ValueError:
        # Deliberately do not include the key in the message.
        raise SecretsConfigError(f"{ENV_VAR} is not a valid Fernet key") from None
    return MultiFernet(keys)


def encrypt(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise DecryptionError("Could not decrypt value (wrong key or corrupted data)") from None
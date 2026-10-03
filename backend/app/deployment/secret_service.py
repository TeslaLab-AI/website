"""Store secrets encrypted, and inject them into a deployment.

Flow: set_secret() encrypts -> repository stores ciphertext only ->
deploy_with_secrets() decrypts at the last moment and hands the values to the
provider adapter. Values are never written to the repo and never logged.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable

from .adapters.base import DeploymentAdapter, DeployResult
from .secret_store import decrypt as default_decrypt
from .secret_store import encrypt as default_encrypt
from .secrets_repo import SecretsRepository

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_VALUE_LENGTH = 10_000


class MissingSecretsError(Exception):
    """Required variables have no stored value. Carries NAMES only."""

    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(f"Missing required environment variables: {', '.join(names)}")


class SecretService:
    def __init__(
        self,
        repo: SecretsRepository,
        encrypt: Callable[[str], str] = default_encrypt,
        decrypt: Callable[[str], str] = default_decrypt,
    ) -> None:
        self._repo = repo
        self._encrypt = encrypt
        self._decrypt = decrypt

    @staticmethod
    def _check_scope(tenant_id: str, project_id: str) -> None:
        if not tenant_id or not project_id:
            raise ValueError("tenant_id and project_id are required")

    def set_secret(self, tenant_id: str, project_id: str, key: str, value: str) -> None:
        self._check_scope(tenant_id, project_id)
        if not KEY_RE.match(key):
            raise ValueError("Invalid variable name (use letters, digits and underscores)")
        if not value or len(value) > MAX_VALUE_LENGTH:
            raise ValueError(f"Value for {key} must be 1-{MAX_VALUE_LENGTH} characters")
        self._repo.upsert(tenant_id, project_id, key, self._encrypt(value))

    def list_keys(self, tenant_id: str, project_id: str) -> list[str]:
        """Names only. Values are never returned by this method."""
        self._check_scope(tenant_id, project_id)
        return sorted(self._repo.get_all(tenant_id, project_id))

    def delete_secret(self, tenant_id: str, project_id: str, key: str) -> bool:
        self._check_scope(tenant_id, project_id)
        return self._repo.delete(tenant_id, project_id, key)

    def get_env_for_deploy(self, tenant_id: str, project_id: str) -> dict[str, str]:
        """Decrypt everything for one project. Call only at deploy time."""
        self._check_scope(tenant_id, project_id)
        rows = self._repo.get_all(tenant_id, project_id)
        return {key: self._decrypt(cipher) for key, cipher in rows.items()}


def deploy_with_secrets(
    adapter: DeploymentAdapter,
    secrets: SecretService,
    tenant_id: str,
    project_id: str,
    repo_url: str,
    branch: str = "main",
    required: Iterable[str] = (),
) -> DeployResult:
    """Deploy a project with its decrypted env vars.

    Pass `required` (e.g. from env_detector.detect_env_vars) to stop early with a
    clear error instead of shipping a build that will crash for a missing variable.
    """
    env_vars = secrets.get_env_for_deploy(tenant_id, project_id)
    missing = sorted(set(required) - set(env_vars))
    if missing:
        raise MissingSecretsError(missing)
    return adapter.deploy(tenant_id, project_id, repo_url, branch, env_vars)
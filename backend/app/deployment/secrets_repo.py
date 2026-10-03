"""Storage for ENCRYPTED project secrets.

Repositories only ever see ciphertext. Every method requires tenant_id and
filters by it, so one tenant can never read or change another tenant's rows.
"""

from __future__ import annotations

from typing import Protocol

TABLE = "project_secrets"


class SecretsRepository(Protocol):
    def upsert(self, tenant_id: str, project_id: str, key: str, value_encrypted: str) -> None: ...

    def get_all(self, tenant_id: str, project_id: str) -> dict[str, str]:
        """Return {key: value_encrypted} for one project."""

    def delete(self, tenant_id: str, project_id: str, key: str) -> bool: ...


class InMemorySecretsRepository:
    """For tests and local development."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], str] = {}

    def upsert(self, tenant_id, project_id, key, value_encrypted) -> None:
        self._rows[(tenant_id, project_id, key)] = value_encrypted

    def get_all(self, tenant_id, project_id) -> dict[str, str]:
        return {
            k: v
            for (t, p, k), v in self._rows.items()
            if t == tenant_id and p == project_id
        }

    def delete(self, tenant_id, project_id, key) -> bool:
        return self._rows.pop((tenant_id, project_id, key), None) is not None


class SupabaseSecretsRepository:
    """Backed by the project_secrets table (see supabase/migrations).

    Pass a supabase-py client created with the SERVICE ROLE key, server-side
    only. NOTE: not yet tested against a real Supabase project.
    """

    def __init__(self, client) -> None:
        self._client = client

    def upsert(self, tenant_id, project_id, key, value_encrypted) -> None:
        self._client.table(TABLE).upsert(
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "key": key,
                "value_encrypted": value_encrypted,
            },
            on_conflict="tenant_id,project_id,key",
        ).execute()

    def get_all(self, tenant_id, project_id) -> dict[str, str]:
        result = (
            self._client.table(TABLE)
            .select("key,value_encrypted")
            .eq("tenant_id", tenant_id)
            .eq("project_id", project_id)
            .execute()
        )
        return {row["key"]: row["value_encrypted"] for row in (result.data or [])}

    def delete(self, tenant_id, project_id, key) -> bool:
        result = (
            self._client.table(TABLE)
            .delete()
            .eq("tenant_id", tenant_id)
            .eq("project_id", project_id)
            .eq("key", key)
            .execute()
        )
        return bool(result.data)
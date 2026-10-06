"""API contract tests for the TeslaLab Build Engine."""
from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'test.db')}"

import pytest
from fastapi.testclient import TestClient

import api
from models.project import Base

TENANT_A = {"X-Tenant-Id": "t1", "X-User-Id": "u1"}
TENANT_B = {"X-Tenant-Id": "t2", "X-User-Id": "u2"}


@pytest.fixture()
def client() -> Iterator[TestClient]:
    Base.metadata.drop_all(api.engine)
    Base.metadata.create_all(api.engine)
    with TestClient(api.app) as test_client:
        yield test_client
    Base.metadata.drop_all(api.engine)


def test_create_project_ok(client: TestClient) -> None:
    response = client.post("/projects", json={"name": "My Site", "type": "website"}, headers=TENANT_A)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "My Site"
    assert body["type"] == "website"
    assert body["stack"] == "nextjs"
    assert body["status"] == "BUILDING"
    assert body["tenant_id"] == "t1"
    assert body["owner_id"] == "u1"
    assert body["repository"] is None


def test_invalid_name_rejected(client: TestClient) -> None:
    for bad_name in ("", "x" * 61):
        response = client.post("/projects", json={"name": bad_name, "type": "website"}, headers=TENANT_A)
        assert response.status_code == 422


def test_invalid_type_rejected(client: TestClient) -> None:
    response = client.post("/projects", json={"name": "ok", "type": "desktop"}, headers=TENANT_A)
    assert response.status_code == 422


@pytest.mark.parametrize("missing", ["X-Tenant-Id", "X-User-Id"])
def test_missing_identity_header_returns_401(client: TestClient, missing: str) -> None:
    headers = {**TENANT_A}
    del headers[missing]
    assert client.get("/projects", headers=headers).status_code == 401


def test_get_own_project_ok(client: TestClient) -> None:
    created = client.post("/projects", json={"name": "Mine", "type": "web_app"}, headers=TENANT_A)
    project_id = created.json()["id"]
    response = client.get(f"/projects/{project_id}", headers=TENANT_A)
    assert response.status_code == 200
    assert response.json()["id"] == project_id


def test_other_tenant_gets_404(client: TestClient) -> None:
    created = client.post("/projects", json={"name": "Secret", "type": "ai_agent"}, headers=TENANT_A)
    project_id = created.json()["id"]
    response = client.get(f"/projects/{project_id}", headers=TENANT_B)
    assert response.status_code == 404


def test_list_only_caller_tenant(client: TestClient) -> None:
    client.post("/projects", json={"name": "A", "type": "website"}, headers=TENANT_A)
    client.post("/projects", json={"name": "B", "type": "website"}, headers=TENANT_B)
    response = client.get("/projects", headers=TENANT_A)
    assert response.status_code == 200
    assert [project["name"] for project in response.json()] == ["A"]


def test_build_and_events_endpoints_are_tenant_scoped(client: TestClient) -> None:
    created = client.post("/projects", json={"name": "Private", "type": "website"}, headers=TENANT_A)
    project_id = created.json()["id"]
    assert client.post(
        f"/projects/{project_id}/build", json={"prompt": "make a site"}, headers=TENANT_B
    ).status_code == 404
    assert client.get(f"/projects/{project_id}/events", headers=TENANT_B).status_code == 404
    assert client.post(f"/projects/{project_id}/build", json={"prompt": "make a site"}).status_code == 401
    assert client.get(f"/projects/{project_id}/events").status_code == 401


def test_build_endpoint_queues_background_pipeline(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created = client.post("/projects", json={"name": "Build", "type": "website"}, headers=TENANT_A)
    project_id = created.json()["id"]
    queued: list[tuple[str, str, str]] = []
    monkeypatch.setattr(api, "_run_build_project", lambda *args: queued.append(args))
    response = client.post(
        f"/projects/{project_id}/build", json={"prompt": "Startup landing page"}, headers=TENANT_A
    )
    assert response.status_code == 202
    assert queued == [(project_id, "t1", "Startup landing page")]


def test_events_endpoint_streams_project_history(client: TestClient) -> None:
    created = client.post("/projects", json={"name": "History", "type": "website"}, headers=TENANT_A)
    project_id = created.json()["id"]
    with api.SessionLocal() as session:
        project = session.get(api.Project, project_id)
        project.history = {"events": [{"ts": "now", "stage": "build", "message": "started"}]}
        session.commit()
    response = client.get(f"/projects/{project_id}/events", headers=TENANT_A)
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"stage": "build"' in response.text

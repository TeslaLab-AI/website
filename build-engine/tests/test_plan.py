"""Offline tests for Plan JSON validation and parsing."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from plan import Plan, PlanError, parse_plan


def valid_plan() -> dict[str, object]:
    return {
        "version": "1",
        "app_type": "website",
        "name": "Launch site",
        "requirements": ["Mobile friendly"],
        "pages": [{"route": "/", "title": "Home", "purpose": "Landing page"}],
        "features": [],
        "db": [],
        "apis": [],
        "env_vars": [],
        "files": [{"path": "app/page.tsx", "purpose": "Home page"}],
    }


def test_plan_accepts_valid_v1() -> None:
    assert Plan.model_validate(valid_plan()).name == "Launch site"


@pytest.mark.parametrize(
    "edit",
    [
        lambda data: data["files"].__setitem__(0, {"path": "../outside.tsx", "purpose": "bad"}),
        lambda data: data["files"].append(data["files"][0]),
        lambda data: data["env_vars"].append("api_key=value"),
        lambda data: data["pages"].append({"route": "/missing", "title": "Missing", "purpose": "bad"}),
    ],
)
def test_plan_rejects_invalid_path_duplicate_env_and_unmapped_route(edit: object) -> None:
    data = valid_plan()
    edit(data)  # type: ignore[operator]
    with pytest.raises(ValidationError):
        Plan.model_validate(data)


def test_plan_rejects_more_than_twelve_pages() -> None:
    data = valid_plan()
    data["pages"] = [
        {"route": f"/page-{index}", "title": "Page", "purpose": "Test"}
        for index in range(13)
    ]
    with pytest.raises(ValidationError):
        Plan.model_validate(data)


def test_parse_plan_strips_fences_and_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(["not json", f"```json\n{json.dumps(valid_plan())}\n```"])
    calls: list[tuple[str, str, bool]] = []

    def fake_complete(system: str, user: str, json_mode: bool = False) -> str:
        calls.append((system, user, json_mode))
        return next(responses)

    monkeypatch.setitem(sys.modules, "llm", SimpleNamespace(complete=fake_complete))
    assert parse_plan("make a site").name == "Launch site"
    assert len(calls) == 2
    assert calls[0][2] is True
    assert "Validation error" in calls[1][1]


def test_parse_plan_raises_after_second_invalid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "llm", SimpleNamespace(complete=lambda *args, **kwargs: "{}"))
    with pytest.raises(PlanError):
        parse_plan("make a site")

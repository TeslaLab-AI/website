"""Strict Plan JSON v1 schema and parser."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator, model_validator

import sandbox


class PlanError(ValueError):
    """Raised when a model response cannot be parsed as a valid Plan."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Page(StrictModel):
    route: StrictStr
    title: StrictStr
    purpose: StrictStr

    @field_validator("route")
    @classmethod
    def validate_route(cls, route: str) -> str:
        if not route.startswith("/") or "//" in route or ".." in route.split("/"):
            raise ValueError("route must be an absolute app route without traversal")
        if route != "/" and route.endswith("/"):
            raise ValueError("route must not end with a slash")
        return route


class Column(StrictModel):
    name: StrictStr
    type: StrictStr
    nullable: StrictBool


class Table(StrictModel):
    table: StrictStr
    columns: list[Column]


class API(StrictModel):
    method: StrictStr
    path: StrictStr
    purpose: StrictStr


class File(StrictModel):
    path: StrictStr
    purpose: StrictStr

    @field_validator("path")
    @classmethod
    def validate_path(cls, path: str) -> str:
        return sandbox.validate_relative_path(path)


class Plan(StrictModel):
    version: Literal["1"]
    app_type: Literal["website", "web_app", "ai_agent"]
    name: StrictStr
    requirements: list[StrictStr]
    pages: list[Page] = Field(max_length=12)
    features: list[StrictStr]
    db: list[Table]
    apis: list[API]
    env_vars: list[StrictStr]
    files: list[File] = Field(max_length=25)

    @field_validator("env_vars")
    @classmethod
    def validate_env_vars(cls, names: list[str]) -> list[str]:
        if any(re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is None for name in names):
            raise ValueError("env_vars must contain uppercase environment variable names only")
        return names

    @model_validator(mode="after")
    def validate_files(self) -> Plan:
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("files contains duplicate paths")
        for page in self.pages:
            route_path = "app" + (page.route if page.route != "/" else "") + "/page."
            if not any(path in {route_path + "tsx", route_path + "jsx"} for path in paths):
                raise ValueError(f"route {page.route!r} has no matching App Router page file")
        return self


def _response_json(response: str) -> str:
    text = response.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
        if text.startswith("json"):
            text = text[4:].strip()
    return text


def parse_plan(prompt: str) -> Plan:
    """Ask for Plan JSON and retry once with the validation error."""
    from llm import complete

    system = (Path(__file__).parent / "prompts" / "plan.v1.md").read_text(encoding="utf-8")
    user = prompt
    for attempt in range(2):
        try:
            return Plan.model_validate_json(_response_json(complete(system, user, json_mode=True)))
        except (ValueError, json.JSONDecodeError) as exc:
            error = str(exc)
            if attempt == 0:
                user = f"{prompt}\n\nValidation error from the previous response: {error}"
    raise PlanError(f"model failed to return a valid Plan after one retry: {error}")

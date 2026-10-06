"""TeslaLab Build Engine HTTP API (Day 1)."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Iterator, NamedTuple

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from models.project import Base, Project, ProjectCreate, ProjectRead, ProjectStatus, allowed_transition

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./teslalab.db")
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="TeslaLab Build Engine", lifespan=lifespan)


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    prompt: str = Field(min_length=1)


class Caller(NamedTuple):
    tenant_id: str
    user_id: str


def current_user(
    x_tenant_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> Caller:
    # STUB: headers are trusted today; the real auth provider replaces this later.
    if not x_tenant_id or not x_user_id:
        raise HTTPException(status_code=401, detail="tenant and user headers are required")
    return Caller(tenant_id=x_tenant_id, user_id=x_user_id)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def _owned_project(session: Session, caller: Caller, project_id: str) -> Project:
    project = session.scalar(
        select(Project).where(Project.id == project_id, Project.tenant_id == caller.tenant_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@app.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(
    payload: ProjectCreate,
    caller: Caller = Depends(current_user),
    session: Session = Depends(get_session),
) -> Project:
    project = Project(
        tenant_id=caller.tenant_id,
        owner_id=caller.user_id,
        name=payload.name,
        type=payload.type,
        stack=payload.stack,
        status=ProjectStatus.BUILDING,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@app.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: str,
    caller: Caller = Depends(current_user),
    session: Session = Depends(get_session),
) -> Project:
    return _owned_project(session, caller, project_id)


@app.get("/projects", response_model=list[ProjectRead])
def list_projects(
    caller: Caller = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[Project]:
    rows = session.scalars(select(Project).where(Project.tenant_id == caller.tenant_id))
    return list(rows)


def _append_event(project: Project, stage: str, message: str) -> None:
    history = dict(project.history or {})
    events = list(history.get("events", []))
    events.append({"ts": datetime.now(timezone.utc).isoformat(), "stage": stage, "message": message})
    history["events"] = events
    project.history = history


def _run_build_project(project_id: str, tenant_id: str, prompt: str) -> None:
    import build
    import sandbox
    from plan import parse_plan

    with SessionLocal() as session:
        project = session.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
        if project is None:
            return
        try:
            _append_event(project, "plan", "Parsing prompt into Plan v1")
            session.commit()
            plan = parse_plan(prompt)
            build.generate_files(plan, tenant_id, project_id)
            _append_event(project, "generate", "Generated Plan-listed files")
            session.commit()
            if build.build_loop(project):
                server = sandbox.start_dev_server(tenant_id, project_id)
                upstream = f"http://127.0.0.1:{server['port']}"
                preview = build.on_preview_ready(tenant_id, project_id, upstream)
                deployment = dict(project.deployment or {})
                deployment["preview"] = preview
                project.deployment = deployment
                _append_event(project, "preview", "Preview server is ready")
            else:
                session.commit()
                return
        except Exception:
            current = ProjectStatus(project.status)
            if current != ProjectStatus.ERROR and allowed_transition(current, ProjectStatus.ERROR):
                project.status = ProjectStatus.ERROR
            _append_event(project, "error", "Build pipeline failed during plan, generation, or preview")
        session.commit()


@app.post("/projects/{project_id}/build", status_code=202)
def build_project(
    project_id: str,
    payload: BuildRequest,
    background_tasks: BackgroundTasks,
    caller: Caller = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    _owned_project(session, caller, project_id)
    background_tasks.add_task(_run_build_project, project_id, caller.tenant_id, payload.prompt)
    return {"project_id": project_id, "status": "accepted"}


@app.get("/projects/{project_id}/events")
def project_events(
    project_id: str,
    caller: Caller = Depends(current_user),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    history = _owned_project(session, caller, project_id).history or {}
    events = list(history.get("events", []))

    def stream_events() -> Iterator[str]:
        for index, event in enumerate(events):
            yield f"id: {index}\nevent: {event.get('stage', 'message')}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(stream_events(), media_type="text/event-stream")

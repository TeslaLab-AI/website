"""TeslaLab Build Engine HTTP API (Day 1)."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Iterator, NamedTuple

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from models.project import Base, Project, ProjectCreate, ProjectRead, ProjectStatus

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./teslalab.db")
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="TeslaLab Build Engine", lifespan=lifespan)


class Caller(NamedTuple):
    tenant_id: str
    user_id: str


def current_user(
    x_tenant_id: str = Header(...),
    x_user_id: str = Header(...),
) -> Caller:
    # STUB: headers are trusted today; the real auth provider replaces this later.
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

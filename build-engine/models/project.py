"""Shared contract for the TeslaLab Build Engine. Add fields only, never rename."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, DateTime, Enum as SAEnum, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ProjectType(str, enum.Enum):
    WEBSITE = "website"
    WEB_APP = "web_app"
    AI_AGENT = "ai_agent"


class ProjectStatus(str, enum.Enum):
    BUILDING = "BUILDING"
    READY = "READY"
    DEPLOYING = "DEPLOYING"
    LIVE = "LIVE"
    ERROR = "ERROR"
    MAINTENANCE = "MAINTENANCE"


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(60))
    type: Mapped[ProjectType] = mapped_column(
        SAEnum(ProjectType, native_enum=False, values_callable=lambda e: [m.value for m in e])
    )
    stack: Mapped[str] = mapped_column(String(32), default="nextjs")
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        default=ProjectStatus.BUILDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    repository: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deployment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tests: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    maintenance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    history: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    type: ProjectType
    stack: str = Field(default="nextjs", max_length=32)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    owner_id: str
    name: str
    type: ProjectType
    stack: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    repository: dict | None = None
    deployment: dict | None = None
    tests: dict | None = None
    maintenance: dict | None = None
    history: dict | None = None


_TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.BUILDING: {ProjectStatus.READY, ProjectStatus.ERROR},
    ProjectStatus.READY: {ProjectStatus.DEPLOYING},
    ProjectStatus.DEPLOYING: {ProjectStatus.LIVE, ProjectStatus.ERROR},
    ProjectStatus.LIVE: {ProjectStatus.MAINTENANCE, ProjectStatus.ERROR},
    ProjectStatus.MAINTENANCE: {ProjectStatus.LIVE, ProjectStatus.ERROR},
    ProjectStatus.ERROR: {ProjectStatus.BUILDING},
}


def allowed_transition(old: ProjectStatus, new: ProjectStatus) -> bool:
    return new in _TRANSITIONS.get(old, set())

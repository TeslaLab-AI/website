"""Project status transition contract tests."""
from __future__ import annotations

import pytest

from models.project import ProjectStatus, allowed_transition


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (ProjectStatus.BUILDING, ProjectStatus.READY),
        (ProjectStatus.BUILDING, ProjectStatus.ERROR),
        (ProjectStatus.READY, ProjectStatus.DEPLOYING),
        (ProjectStatus.DEPLOYING, ProjectStatus.LIVE),
        (ProjectStatus.DEPLOYING, ProjectStatus.ERROR),
        (ProjectStatus.LIVE, ProjectStatus.MAINTENANCE),
        (ProjectStatus.LIVE, ProjectStatus.ERROR),
        (ProjectStatus.MAINTENANCE, ProjectStatus.LIVE),
        (ProjectStatus.MAINTENANCE, ProjectStatus.ERROR),
        (ProjectStatus.ERROR, ProjectStatus.BUILDING),
    ],
)
def test_allowed_transition_accepts_contract(old: ProjectStatus, new: ProjectStatus) -> None:
    assert allowed_transition(old, new)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (ProjectStatus.READY, ProjectStatus.BUILDING),
        (ProjectStatus.READY, ProjectStatus.ERROR),
        (ProjectStatus.ERROR, ProjectStatus.READY),
        (ProjectStatus.BUILDING, ProjectStatus.DEPLOYING),
        (ProjectStatus.LIVE, ProjectStatus.BUILDING),
    ],
)
def test_allowed_transition_rejects_forbidden(old: ProjectStatus, new: ProjectStatus) -> None:
    assert not allowed_transition(old, new)

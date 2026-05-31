"""In-memory project task store (MVP)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from app.core.schemas import ProjectArtifacts, ProjectStatus


@dataclass
class ProjectRecord:
    project_id: str
    novel_name: str
    episode: int
    text: str
    status: ProjectStatus = ProjectStatus.PENDING
    progress: float = 0.0
    current_stage: str | None = None
    error: str | None = None
    artifacts: ProjectArtifacts = field(default_factory=ProjectArtifacts)
    config_overrides: dict[str, Any] = field(default_factory=dict)
    work_dir: str = ""


class TaskStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._projects: dict[str, ProjectRecord] = {}

    def create(
        self,
        project_id: str,
        novel_name: str,
        episode: int,
        text: str,
        work_dir: str,
        overrides: dict | None = None,
    ) -> ProjectRecord:
        record = ProjectRecord(
            project_id=project_id,
            novel_name=novel_name,
            episode=episode,
            text=text,
            work_dir=work_dir,
            config_overrides=overrides or {},
        )
        with self._lock:
            self._projects[project_id] = record
        return record

    def get(self, project_id: str) -> ProjectRecord | None:
        with self._lock:
            return self._projects.get(project_id)

    def update(
        self,
        project_id: str,
        *,
        status: ProjectStatus | None = None,
        progress: float | None = None,
        current_stage: str | None = None,
        error: str | None = None,
        artifacts: ProjectArtifacts | None = None,
    ) -> None:
        with self._lock:
            rec = self._projects.get(project_id)
            if not rec:
                return
            if status is not None:
                rec.status = status
            if progress is not None:
                rec.progress = progress
            if current_stage is not None:
                rec.current_stage = current_stage
            if error is not None:
                rec.error = error
            if artifacts is not None:
                rec.artifacts = artifacts

    def list_ids(self) -> list[str]:
        with self._lock:
            return list(self._projects.keys())


task_store = TaskStore()

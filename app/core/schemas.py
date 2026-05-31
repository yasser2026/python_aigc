"""Pydantic models for API and pipeline data."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    IMAGING = "imaging"
    MOTION = "motion"
    AUDIO = "audio"
    SUBTITLES = "subtitles"
    ASSEMBLING = "assembling"
    DONE = "done"
    FAILED = "failed"


class Character(BaseModel):
    id: str
    name: str
    appearance: str
    ref_image: str | None = None


class Scene(BaseModel):
    id: str
    narration: str
    visual_prompt: str
    character_ids: list[str] = Field(default_factory=list)
    shot_type: str = "medium"
    duration_sec: float | None = None
    image_path: str | None = None
    audio_path: str | None = None
    clip_path: str | None = None


class SceneScript(BaseModel):
    characters: list[Character]
    scenes: list[Scene]


class CreateProjectRequest(BaseModel):
    title: str = "untitled"
    text: str
    config_overrides: dict[str, Any] | None = None


class CreateProjectResponse(BaseModel):
    project_id: str
    status: ProjectStatus


class ProjectArtifacts(BaseModel):
    scenes_json: str | None = None
    output_video: str | None = None
    images_dir: str | None = None


class ProjectDetailResponse(BaseModel):
    project_id: str
    title: str
    status: ProjectStatus
    progress: float
    current_stage: str | None = None
    error: str | None = None
    artifacts: ProjectArtifacts


class HealthResponse(BaseModel):
    status: str
    ffmpeg: bool
    comfyui: bool
    comfyui_mock: bool

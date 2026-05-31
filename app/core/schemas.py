"""Pydantic models for API and pipeline data."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


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


class Location(BaseModel):
    id: str
    name: str
    description: str
    ref_image: str | None = None


class Scene(BaseModel):
    id: str
    narration: str
    visual_prompt: str
    character_ids: list[str] = Field(default_factory=list)
    location_id: str | None = None
    shot_type: str = "medium"
    duration_sec: float | None = None
    image_path: str | None = None
    audio_path: str | None = None
    clip_path: str | None = None


class SceneScript(BaseModel):
    characters: list[Character]
    locations: list[Location] = Field(default_factory=list)
    scenes: list[Scene]


class CreateProjectRequest(BaseModel):
    novel_name: str = Field(..., description="小说名称", min_length=1, max_length=200)
    episode: int = Field(..., description="第几集", ge=1, le=9999)
    text: str = Field(..., description="小说正文片段", min_length=1)
    config_overrides: dict[str, Any] | None = None

    @field_validator("novel_name", "text", mode="before")
    @classmethod
    def strip_whitespace(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class CreateProjectResponse(BaseModel):
    project_id: str
    novel_name: str
    episode: int
    work_dir: str
    status: ProjectStatus


class ProjectArtifacts(BaseModel):
    scenes_json: str | None = None
    output_video: str | None = None
    images_dir: str | None = None


class ProjectDetailResponse(BaseModel):
    project_id: str
    novel_name: str
    episode: int
    work_dir: str
    status: ProjectStatus
    progress: float
    current_stage: str | None = None
    error: str | None = None
    artifacts: ProjectArtifacts


class PortfolioItem(BaseModel):
    project_id: str
    novel_name: str
    episode: int
    has_video: bool = True
    has_poster: bool = False
    video_size_bytes: int | None = None
    finished_at: str | None = None


class PortfolioListResponse(BaseModel):
    items: list[PortfolioItem]
    total: int


class HealthResponse(BaseModel):
    status: str
    ffmpeg: bool
    image_provider: str
    comfyui: bool
    comfyui_mock: bool
    milvus: bool = False
    vector_store_enabled: bool = False

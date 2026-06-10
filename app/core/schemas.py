"""Pydantic models for API and pipeline data."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

NarrativeMode = Literal["faithful", "protagonist_focus"]
ProjectMode = Literal["video", "anime"]
CharacterRole = Literal["protagonist", "supporting", "minor"]
CharacterGender = Literal["male", "female", "unknown"]
CharacterAgeGroup = Literal["child", "teen", "adult", "elder"]
NarrationType = Literal["narrator", "dialogue", "mixed"]
SceneType = Literal["character", "environment", "crowd"]


RelationType = Literal[
    "family", "ally", "enemy", "master_apprentice", "love", "colleague", "subordinate", "other"
]


class CharacterRelation(BaseModel):
    source_id: str
    target_id: str
    type: RelationType = "other"
    note: str | None = None
    bidirectional: bool = False
    confidence: float = 1.0


class PlotEvent(BaseModel):
    event_id: str
    summary: str
    character_ids: list[str] = Field(default_factory=list)
    location_id: str | None = None
    order: int = 0


class GraphDelta(BaseModel):
    relationships: list[CharacterRelation] = Field(default_factory=list)
    plot_events: list[PlotEvent] = Field(default_factory=list)


class EpisodeAnalysis(BaseModel):
    book_protagonist_id: str | None = None
    fragment_focus_ids: list[str] = Field(default_factory=list)
    fragment_summary: str | None = None
    role_notes: dict[str, str] = Field(default_factory=dict)
    episode_supporting_names: list[str] = Field(default_factory=list)


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


class CharacterVariant(BaseModel):
    variant_id: str
    label: str | None = None
    appearance: str
    age_group: CharacterAgeGroup | None = None
    ref_image: str | None = None
    aliases: list[str] = Field(default_factory=list)


class Character(BaseModel):
    id: str
    name: str
    appearance: str
    ref_image: str | None = None
    role: CharacterRole | None = None
    gender: CharacterGender | None = None
    age_group: CharacterAgeGroup | None = None
    aliases: list[str] = Field(default_factory=list)
    default_variant_id: str = "default"
    variants: dict[str, CharacterVariant] = Field(default_factory=dict)
    voice_ref: str | None = None
    voice_ref_text: str | None = None


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
    narration_speaker_id: str | None = None
    narration_type: NarrationType | None = None
    scene_type: SceneType | None = None
    focus_character_ids: list[str] = Field(default_factory=list)
    character_variants: dict[str, str] = Field(default_factory=dict)
    duration_sec: float | None = None
    image_path: str | None = None
    audio_path: str | None = None
    clip_path: str | None = None


class SceneScript(BaseModel):
    characters: list[Character]
    locations: list[Location] = Field(default_factory=list)
    scenes: list[Scene]
    episode_analysis: EpisodeAnalysis | None = None
    graph_delta: GraphDelta | None = None


class CreateProjectRequest(BaseModel):
    novel_name: str = Field(..., description="小说名称", min_length=1, max_length=200)
    episode: int = Field(..., description="第几集", ge=1, le=9999)
    text: str = Field(..., description="小说正文片段", min_length=1)
    mode: ProjectMode = Field(
        default="video",
        description="生成模式：video 生成视频（默认）/ anime 生成动画（data_anime）",
    )
    narrative_mode: NarrativeMode = Field(
        default="protagonist_focus",
        description="叙事模式：protagonist_focus 主角视角 / faithful 忠实原文",
    )
    protagonist_name: str | None = Field(
        default=None,
        description="全书主角姓名，多个可用分号/逗号/空格分隔；首次设定后锁定",
        max_length=300,
    )
    supporting_names: str | None = Field(
        default=None,
        description="本集配角姓名，多个可用分号/逗号/空格分隔；每集可不同",
        max_length=500,
    )
    config_overrides: dict[str, Any] | None = None

    @field_validator("novel_name", "text", "protagonist_name", "supporting_names", mode="before")
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
    mode: ProjectMode = "video"


class ProjectArtifacts(BaseModel):
    scenes_json: str | None = None
    episode_analysis: str | None = None
    output_video: str | None = None
    images_dir: str | None = None


class ProjectDetailResponse(BaseModel):
    project_id: str
    novel_name: str
    episode: int
    work_dir: str
    status: ProjectStatus
    mode: ProjectMode = "video"
    progress: float
    current_stage: str | None = None
    error: str | None = None
    artifacts: ProjectArtifacts


class PortfolioItem(BaseModel):
    project_id: str
    novel_name: str
    episode: int
    mode: ProjectMode = "video"
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
    neo4j: bool = False
    knowledge_graph_enabled: bool = False


class AnimeHealthResponse(BaseModel):
    available: bool
    comfyui: bool = False
    wan_i2v: bool = False
    infinitetalk: bool = False
    gptsovits: bool = False
    message: str | None = None


class NovelMetaResponse(BaseModel):
    novel_name: str
    protagonist_id: str | None = None
    protagonist_ids: list[str] = Field(default_factory=list)
    protagonist_name: str | None = None
    protagonist_names: list[str] = Field(default_factory=list)
    protagonist_locked: bool = False

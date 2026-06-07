"""Pipeline state machine: skip stages when episode input is unchanged."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.schemas import Scene
from app.services import llm_scene, novel_meta

logger = logging.getLogger(__name__)

STATE_FILE = "pipeline_state.json"
ALL_STAGES = [
    "parse_scenes",
    "generate_images",
    "tts",
    "motion_clips",
    "subtitles",
    "assemble",
]


@dataclass
class PipelineState:
    input_fingerprint: str
    completed_stages: list[str] = field(default_factory=list)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_fingerprint": self.input_fingerprint,
            "completed_stages": self.completed_stages,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineState:
        return cls(
            input_fingerprint=str(data.get("input_fingerprint", "")),
            completed_stages=list(data.get("completed_stages") or []),
            updated_at=data.get("updated_at"),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_input_fingerprint(
    *,
    text: str,
    narrative_mode: str,
    supporting_names: list[str] | None = None,
    novel_name: str | None = None,
) -> str:
    """Stable hash of episode inputs that affect LLM scene parsing."""
    protagonist_ids: list[str] = []
    if novel_name:
        meta = novel_meta.get_novel_meta_response(novel_name)
        if meta:
            protagonist_ids = sorted(meta.get("protagonist_ids") or [])

    payload = {
        "text": (text or "").strip(),
        "narrative_mode": narrative_mode or "protagonist_focus",
        "supporting_names": sorted(supporting_names or []),
        "protagonist_ids": protagonist_ids,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_fingerprint_from_record(rec: Any) -> str:
    return compute_input_fingerprint(
        text=rec.text,
        narrative_mode=rec.narrative_mode,
        supporting_names=rec.supporting_names,
        novel_name=rec.novel_name,
    )


def state_path(work_dir: Path) -> Path:
    return work_dir / STATE_FILE


def load_state(work_dir: Path) -> PipelineState | None:
    path = state_path(work_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PipelineState.from_dict(data)
    except (json.JSONDecodeError, OSError, TypeError) as exc:
        logger.warning("Invalid pipeline state %s: %s", path, exc)
        return None


def save_state(work_dir: Path, state: PipelineState) -> None:
    state.updated_at = _now_iso()
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path(work_dir).write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def infer_completed_stages(work_dir: Path) -> list[str]:
    """Detect finished stages from on-disk artifacts (legacy runs without state file)."""
    completed: list[str] = []
    for stage in ALL_STAGES:
        if verify_stage_artifacts(work_dir, stage):
            completed.append(stage)
    return completed


def load_or_reset_state(work_dir: Path, fingerprint: str) -> PipelineState:
    state = load_state(work_dir)
    if state and state.input_fingerprint == fingerprint:
        return state
    if state and state.input_fingerprint != fingerprint:
        logger.info(
            "Episode input changed (%s -> %s), resetting pipeline cache",
            state.input_fingerprint[:8],
            fingerprint[:8],
        )
    state = PipelineState(input_fingerprint=fingerprint)
    inferred = infer_completed_stages(work_dir)
    if inferred:
        state.completed_stages = inferred
        save_state(work_dir, state)
        logger.info(
            "Inferred completed stages for %s: %s",
            work_dir.name,
            ", ".join(inferred),
        )
    return state


def _load_scenes(work_dir: Path) -> list[Scene]:
    script = llm_scene.load_scene_script(work_dir)
    return script.scenes


def verify_stage_artifacts(work_dir: Path, stage: str) -> bool:
    """Return True when on-disk outputs for a stage look complete."""
    if stage == "parse_scenes":
        return (work_dir / "scenes.json").is_file()

    scenes: list[Scene] | None = None

    def scenes_or_load() -> list[Scene]:
        nonlocal scenes
        if scenes is None:
            if not (work_dir / "scenes.json").is_file():
                return []
            scenes = _load_scenes(work_dir)
        return scenes

    if stage == "generate_images":
        for scene in scenes_or_load():
            img = work_dir / "images" / f"{scene.id}.png"
            if scene.image_path:
                from app.core.paths import storage_path_is_file

                if storage_path_is_file(scene.image_path):
                    continue
            if not img.is_file():
                return False
        return bool(scenes_or_load())

    if stage == "tts":
        audio_dir = work_dir / "audio"
        for scene in scenes_or_load():
            audio = audio_dir / f"{scene.id}.mp3"
            if not audio.is_file() or audio.stat().st_size <= 256:
                return False
        return bool(scenes_or_load())

    if stage == "motion_clips":
        clips_dir = work_dir / "clips"
        for scene in scenes_or_load():
            clip = clips_dir / f"{scene.id}.mp4"
            silent = clips_dir / f"{scene.id}_silent.mp4"
            if not clip.is_file() and not silent.is_file():
                return False
        return bool(scenes_or_load())

    if stage == "subtitles":
        subs = work_dir / "subs"
        if not (subs / "full.ass").is_file():
            return False
        for scene in scenes_or_load():
            if not (subs / f"{scene.id}.ass").is_file():
                return False
        return bool(scenes_or_load())

    if stage == "assemble":
        return (work_dir / "output" / "final.mp4").is_file()

    return False


def is_stage_complete(
    work_dir: Path,
    stage: str,
    state: PipelineState,
    fingerprint: str,
) -> bool:
    if state.input_fingerprint != fingerprint:
        return False
    if stage not in state.completed_stages:
        return False
    return verify_stage_artifacts(work_dir, stage)


def should_skip_stage(
    work_dir: Path,
    stage: str,
    state: PipelineState,
    fingerprint: str,
    *,
    enabled: bool = True,
) -> bool:
    if not enabled:
        return False
    return is_stage_complete(work_dir, stage, state, fingerprint)


def mark_stage_complete(
    work_dir: Path,
    state: PipelineState,
    stage: str,
    fingerprint: str,
) -> PipelineState:
    state.input_fingerprint = fingerprint
    if stage not in state.completed_stages:
        state.completed_stages.append(stage)
    save_state(work_dir, state)
    return state


def is_fully_complete(
    work_dir: Path,
    state: PipelineState,
    fingerprint: str,
    *,
    stages: list[str] | None = None,
    enabled: bool = True,
) -> bool:
    if not enabled:
        return False
    if state.input_fingerprint != fingerprint:
        return False
    target = stages or list(ALL_STAGES)
    if "assemble" not in target:
        return False
    return is_stage_complete(work_dir, "assemble", state, fingerprint)


async def load_durations_from_audio(
    work_dir: Path,
    scenes: list[Scene],
    *,
    default_dur: float = 4.0,
) -> list[float]:
    """Probe existing mp3 files when TTS stage is skipped."""
    from app.services.tts_service import _get_audio_duration, estimate_duration_from_text

    durations: list[float] = []
    audio_dir = work_dir / "audio"
    for scene in scenes:
        if scene.duration_sec and scene.duration_sec > 0:
            durations.append(float(scene.duration_sec))
            continue
        audio_path = audio_dir / f"{scene.id}.mp3"
        if audio_path.is_file():
            dur = await _get_audio_duration(audio_path)
            if dur <= 0:
                dur = estimate_duration_from_text(scene.narration)
            durations.append(dur)
        else:
            durations.append(default_dur)
    return durations


def hydrate_scene_paths(work_dir: Path, scenes: list[Scene]) -> list[Scene]:
    """Fill audio/clip/image paths from standard layout when resuming."""
    audio_dir = work_dir / "audio"
    clips_dir = work_dir / "clips"
    images_dir = work_dir / "images"
    updated: list[Scene] = []
    for scene in scenes:
        patch: dict[str, Any] = {}
        if not scene.image_path:
            img = images_dir / f"{scene.id}.png"
            if img.is_file():
                patch["image_path"] = str(img)
        if not scene.audio_path:
            audio = audio_dir / f"{scene.id}.mp3"
            if audio.is_file():
                patch["audio_path"] = str(audio)
        if not scene.clip_path:
            clip = clips_dir / f"{scene.id}.mp4"
            silent = clips_dir / f"{scene.id}_silent.mp4"
            if clip.is_file():
                patch["clip_path"] = str(clip)
            elif silent.is_file():
                patch["clip_path"] = str(silent)
        updated.append(scene.model_copy(update=patch) if patch else scene)
    return updated

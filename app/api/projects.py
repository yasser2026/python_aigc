"""Project API routes."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app.core.config_loader import load_config
from app.core.runtime import normalize_mode, set_mode
from app.core.schemas import (
    AnimeHealthResponse,
    CreateProjectRequest,
    CreateProjectResponse,
    HealthResponse,
    ProjectArtifacts,
    ProjectDetailResponse,
    ProjectStatus,
)
from app.core.paths import build_project_id, build_work_dir, data_root_for_mode
from app.pipeline.runner import run_pipeline
from app.pipeline import state as pipeline_state
from app.pipeline.task_store import task_store
from app.services import anime_health, comfyui_client, ffmpeg_motion, knowledge_graph, novel_meta
from app.services.image_provider import get_image_provider
from app.services import vector_store

router = APIRouter()
health_router = APIRouter()


def _output_video_on_disk(project_id: str, mode: str = "video") -> Path | None:
    """Fallback when task_store is empty but pipeline already wrote final.mp4."""
    path = data_root_for_mode(mode) / project_id / "output" / "final.mp4"
    return path if path.is_file() else None


@health_router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    provider = get_image_provider()
    comfy_cfg = load_config("comfyui")
    ffmpeg_ok = ffmpeg_motion.ffmpeg_available()

    if provider == "comfyui":
        comfy_ok = await comfyui_client.comfyui_reachable()
        comfy_mock = comfy_cfg.get("mock", True) or not comfy_ok
    elif provider == "qwen":
        comfy_ok = False
        comfy_mock = False
    else:
        comfy_ok = False
        comfy_mock = True

    return HealthResponse(
        status="ok",
        ffmpeg=ffmpeg_ok,
        image_provider=provider,
        comfyui=comfy_ok,
        comfyui_mock=comfy_mock,
        milvus=vector_store.ping(),
        vector_store_enabled=vector_store.is_enabled(),
        neo4j=knowledge_graph.ping() if knowledge_graph.is_enabled() else False,
        knowledge_graph_enabled=knowledge_graph.is_pipeline_enabled(),
    )


@health_router.get("/anime/health", response_model=AnimeHealthResponse)
async def anime_health_check() -> AnimeHealthResponse:
    result = await anime_health.check_anime_services()
    return AnimeHealthResponse(**result)


@router.post("", response_model=CreateProjectResponse)
async def create_project(
    body: CreateProjectRequest,
    background_tasks: BackgroundTasks,
) -> CreateProjectResponse:
    mode = set_mode(body.mode)
    project_id = build_project_id(body.novel_name, body.episode)
    work_dir = build_work_dir(body.novel_name, body.episode)
    work_dir.mkdir(parents=True, exist_ok=True)

    protagonist_meta: dict | None = None
    if body.protagonist_name and body.protagonist_name.strip():
        try:
            protagonist_meta = novel_meta.set_user_protagonist(
                body.novel_name, body.protagonist_name.strip()
            )
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
    elif novel_meta.is_protagonist_locked(body.novel_name):
        protagonist_meta = novel_meta.get_novel_meta_response(body.novel_name)

    supporting_names = novel_meta.parse_character_names(body.supporting_names or "")

    record = task_store.create(
        project_id=project_id,
        novel_name=body.novel_name,
        episode=body.episode,
        text=body.text,
        work_dir=str(work_dir),
        overrides=body.config_overrides,
        narrative_mode=body.narrative_mode,
        supporting_names=supporting_names,
        mode=mode,
    )
    meta_payload = {
        "novel_name": body.novel_name,
        "episode": body.episode,
        "project_id": project_id,
        "mode": mode,
        "narrative_mode": body.narrative_mode,
    }
    if body.protagonist_name and body.protagonist_name.strip():
        meta_payload["protagonist_name"] = body.protagonist_name.strip()
    if supporting_names:
        meta_payload["supporting_names"] = supporting_names
    if protagonist_meta:
        meta_payload["protagonist_locked"] = protagonist_meta.get("protagonist_locked")
        if protagonist_meta.get("protagonist_ids"):
            meta_payload["protagonist_ids"] = protagonist_meta["protagonist_ids"]
        if protagonist_meta.get("protagonist_names"):
            meta_payload["protagonist_names"] = protagonist_meta["protagonist_names"]
        if protagonist_meta.get("protagonist_id"):
            meta_payload["protagonist_id"] = protagonist_meta["protagonist_id"]

    fingerprint = pipeline_state.compute_input_fingerprint(
        text=body.text,
        narrative_mode=body.narrative_mode,
        supporting_names=supporting_names,
        novel_name=body.novel_name,
    )
    meta_payload["input_fingerprint"] = fingerprint

    (work_dir / "meta.json").write_text(
        json.dumps(meta_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (work_dir / "input.txt").write_text(body.text, encoding="utf-8")

    cache_enabled = load_config("pipeline").get("cache", {}).get("enabled", True)
    pstate = pipeline_state.load_or_reset_state(work_dir, fingerprint)
    final_path = work_dir / "output" / "final.mp4"
    already_done = (
        cache_enabled
        and pipeline_state.is_fully_complete(
            work_dir, pstate, fingerprint, enabled=cache_enabled
        )
    )

    if already_done:
        task_store.update(
            record.project_id,
            mode=mode,
            status=ProjectStatus.DONE,
            progress=100.0,
            current_stage="done",
            artifacts=ProjectArtifacts(
                scenes_json=str(work_dir / "scenes.json"),
                episode_analysis=str(work_dir / "episode_analysis.json")
                if (work_dir / "episode_analysis.json").is_file()
                else None,
                output_video=str(final_path),
                images_dir=str(work_dir / "images"),
            ),
        )
        return CreateProjectResponse(
            project_id=record.project_id,
            novel_name=record.novel_name,
            episode=record.episode,
            work_dir=record.work_dir,
            status=ProjectStatus.DONE,
            mode=mode,
        )

    background_tasks.add_task(_run_async, record.project_id, mode)

    return CreateProjectResponse(
        project_id=record.project_id,
        novel_name=record.novel_name,
        episode=record.episode,
        work_dir=record.work_dir,
        status=ProjectStatus.PENDING,
        mode=mode,
    )


async def _run_async(project_id: str, mode: str = "video") -> None:
    await run_pipeline(project_id, mode)


@router.get("")
def list_projects() -> dict:
    ids = task_store.list_ids()
    return {"projects": ids}


@router.get("/{project_id:path}/download")
def download_project(project_id: str, mode: str = "video") -> FileResponse:
    mode = set_mode(mode)
    rec = task_store.get(project_id, mode=mode)
    disk_path = _output_video_on_disk(project_id, mode)

    if rec:
        if rec.status != ProjectStatus.DONE:
            raise HTTPException(status_code=409, detail=f"project status is {rec.status.value}")
        path_str = rec.artifacts.output_video
        path = Path(path_str) if path_str else None
        if path and path.is_file():
            return FileResponse(
                path,
                media_type="video/mp4",
                filename=f"{rec.novel_name}_第{rec.episode:02d}集.mp4",
            )

    if disk_path:
        meta_path = disk_path.parent.parent / "meta.json"
        novel, episode = project_id.rsplit("/", 1)[0], 1
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            novel = meta.get("novel_name", novel)
            episode = int(meta.get("episode", episode))
        else:
            import re

            m = re.search(r"第(\d+)集", project_id)
            if m:
                episode = int(m.group(1))
            novel = project_id.split("/")[0] if "/" in project_id else project_id
        return FileResponse(
            disk_path,
            media_type="video/mp4",
            filename=f"{novel}_第{episode:02d}集.mp4",
        )

    raise HTTPException(status_code=404, detail="output video not found")


@router.get("/{project_id:path}", response_model=ProjectDetailResponse)
def get_project(project_id: str, mode: str = "video") -> ProjectDetailResponse:
    mode = normalize_mode(mode)
    rec = task_store.get(project_id, mode=mode)
    if not rec:
        raise HTTPException(status_code=404, detail="project not found")
    return ProjectDetailResponse(
        project_id=rec.project_id,
        novel_name=rec.novel_name,
        episode=rec.episode,
        work_dir=rec.work_dir,
        status=rec.status,
        mode=rec.mode,
        progress=rec.progress,
        current_stage=rec.current_stage,
        error=rec.error,
        artifacts=rec.artifacts,
    )

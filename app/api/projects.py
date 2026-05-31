"""Project API routes."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app.core.config_loader import get_root, load_config
from app.core.schemas import (
    CreateProjectRequest,
    CreateProjectResponse,
    HealthResponse,
    ProjectDetailResponse,
    ProjectStatus,
)
from app.core.paths import build_project_id, build_work_dir
from app.pipeline.runner import run_pipeline
from app.pipeline.task_store import task_store
from app.services import comfyui_client, ffmpeg_motion
from app.services.image_provider import get_image_provider
from app.services import vector_store

router = APIRouter()
health_router = APIRouter()


def _output_video_on_disk(project_id: str) -> Path | None:
    """Fallback when task_store is empty but pipeline already wrote final.mp4."""
    app_cfg = load_config("app")
    path = get_root() / app_cfg.get("data_root", "data") / project_id / "output" / "final.mp4"
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
    )


@router.post("", response_model=CreateProjectResponse)
async def create_project(
    body: CreateProjectRequest,
    background_tasks: BackgroundTasks,
) -> CreateProjectResponse:
    project_id = build_project_id(body.novel_name, body.episode)
    work_dir = build_work_dir(body.novel_name, body.episode)
    work_dir.mkdir(parents=True, exist_ok=True)

    record = task_store.create(
        project_id=project_id,
        novel_name=body.novel_name,
        episode=body.episode,
        text=body.text,
        work_dir=str(work_dir),
        overrides=body.config_overrides,
    )
    (work_dir / "meta.json").write_text(
        json.dumps(
            {
                "novel_name": body.novel_name,
                "episode": body.episode,
                "project_id": project_id,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (work_dir / "input.txt").write_text(body.text, encoding="utf-8")

    background_tasks.add_task(_run_async, record.project_id)

    return CreateProjectResponse(
        project_id=record.project_id,
        novel_name=record.novel_name,
        episode=record.episode,
        work_dir=record.work_dir,
        status=ProjectStatus.PENDING,
    )


async def _run_async(project_id: str) -> None:
    await run_pipeline(project_id)


@router.get("")
def list_projects() -> dict:
    ids = task_store.list_ids()
    return {"projects": ids}


@router.get("/{project_id:path}/download")
def download_project(project_id: str) -> FileResponse:
    rec = task_store.get(project_id)
    disk_path = _output_video_on_disk(project_id)

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
def get_project(project_id: str) -> ProjectDetailResponse:
    rec = task_store.get(project_id)
    if not rec:
        raise HTTPException(status_code=404, detail="project not found")
    return ProjectDetailResponse(
        project_id=rec.project_id,
        novel_name=rec.novel_name,
        episode=rec.episode,
        work_dir=rec.work_dir,
        status=rec.status,
        progress=rec.progress,
        current_stage=rec.current_stage,
        error=rec.error,
        artifacts=rec.artifacts,
    )

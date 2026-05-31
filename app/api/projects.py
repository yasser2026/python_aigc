"""Project API routes."""

from __future__ import annotations

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
from app.pipeline.runner import _work_path, run_pipeline
from app.pipeline.task_store import task_store
from app.services import comfyui_client, ffmpeg_motion

router = APIRouter()
health_router = APIRouter()


@health_router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    cfg = load_config("comfyui")
    comfy_ok = await comfyui_client.comfyui_reachable()
    return HealthResponse(
        status="ok",
        ffmpeg=ffmpeg_motion.ffmpeg_available(),
        comfyui=comfy_ok,
        comfyui_mock=cfg.get("mock", True) or not comfy_ok,
    )


@router.post("", response_model=CreateProjectResponse)
async def create_project(
    body: CreateProjectRequest,
    background_tasks: BackgroundTasks,
) -> CreateProjectResponse:
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    record = task_store.create(
        title=body.title,
        text=body.text.strip(),
        work_dir="",
        overrides=body.config_overrides,
    )
    work_dir = _work_path(record.project_id)
    record.work_dir = str(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "input.txt").write_text(body.text, encoding="utf-8")

    background_tasks.add_task(_run_async, record.project_id)

    return CreateProjectResponse(
        project_id=record.project_id,
        status=ProjectStatus.PENDING,
    )


async def _run_async(project_id: str) -> None:
    await run_pipeline(project_id)


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project(project_id: str) -> ProjectDetailResponse:
    rec = task_store.get(project_id)
    if not rec:
        raise HTTPException(status_code=404, detail="project not found")
    return ProjectDetailResponse(
        project_id=rec.project_id,
        title=rec.title,
        status=rec.status,
        progress=rec.progress,
        current_stage=rec.current_stage,
        error=rec.error,
        artifacts=rec.artifacts,
    )


@router.get("")
def list_projects() -> dict:
    ids = task_store.list_ids()
    return {"projects": ids}


@router.get("/{project_id}/download")
def download_project(project_id: str) -> FileResponse:
    rec = task_store.get(project_id)
    if not rec:
        raise HTTPException(status_code=404, detail="project not found")
    if rec.status != ProjectStatus.DONE:
        raise HTTPException(status_code=409, detail=f"project status is {rec.status.value}")
    path = rec.artifacts.output_video
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="output video not found")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{rec.title or project_id}.mp4",
    )

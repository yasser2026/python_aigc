"""Shared ComfyUI HTTP helpers (upload, prompt, poll, fetch output).

Reused by the image, Wan2.1 I2V, and InfiniteTalk clients so they don't each
re-implement the ComfyUI prompt/poll dance.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from app.core.config_loader import get_root, load_config

_VIDEO_EXTS = (".mp4", ".webm", ".mov", ".gif", ".mkv")


def set_nested(obj: dict, path: list, value: Any) -> None:
    cur = obj
    keys = [str(path[0])] + list(path[1:])
    for key in keys[:-1]:
        cur = cur[key]
    cur[keys[-1]] = value


def resolve_host(cfg_name: str, default: str = "http://127.0.0.1:8188") -> str:
    cfg = load_config(cfg_name)
    host = cfg.get("host", default)
    if not host or host.startswith("${"):
        host = default
    return host.rstrip("/")


def load_workflow(cfg_name: str) -> dict[str, Any]:
    cfg = load_config(cfg_name)
    wf_path = get_root() / cfg["workflow_path"]
    with open(wf_path, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not str(k).startswith("_")}


async def reachable(host: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{host}/system_stats")
            return r.status_code == 200
    except Exception:
        return False


async def upload_input_file(host: str, file_path: Path, content_type: str) -> str:
    """Upload a file into ComfyUI's input folder; returns the stored filename."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        with open(file_path, "rb") as f:
            files = {"image": (file_path.name, f, content_type)}
            data = {"overwrite": "true"}
            r = await client.post(f"{host}/upload/image", files=files, data=data)
        r.raise_for_status()
        return r.json().get("name", file_path.name)


async def submit_prompt(host: str, workflow: dict, client_id: str = "aigc") -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{host}/prompt",
            json={"prompt": workflow, "client_id": client_id},
        )
        r.raise_for_status()
        return r.json()["prompt_id"]


async def poll_history(
    host: str, prompt_id: str, *, interval: float = 3.0, timeout: float = 900.0
) -> dict:
    elapsed = 0.0
    async with httpx.AsyncClient(timeout=30.0) as client:
        while elapsed < timeout:
            r = await client.get(f"{host}/history/{prompt_id}")
            if r.status_code == 200:
                data = r.json()
                if prompt_id in data:
                    return data[prompt_id]
            await asyncio.sleep(interval)
            elapsed += interval
    raise TimeoutError(f"ComfyUI prompt {prompt_id} timed out after {timeout}s")


def _iter_outputs(history: dict, keys: tuple[str, ...]) -> list[dict]:
    found: list[dict] = []
    for node_out in history.get("outputs", {}).values():
        for key in keys:
            for item in node_out.get(key, []) or []:
                found.append(item)
    return found


async def fetch_video_output(host: str, history: dict, output_path: Path) -> Path:
    """Download the first video output referenced in a ComfyUI history entry."""
    candidates = _iter_outputs(history, ("gifs", "videos", "images"))
    for info in candidates:
        filename = info.get("filename", "")
        if not filename.lower().endswith(_VIDEO_EXTS):
            continue
        subfolder = info.get("subfolder", "")
        ftype = info.get("type", "output")
        url = f"{host}/view?filename={filename}&subfolder={subfolder}&type={ftype}"
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(resp.content)
            return output_path
    raise RuntimeError("No video output found in ComfyUI history")

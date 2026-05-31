"""ComfyUI HTTP API client with mock fallback."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import httpx
from app.core.config_loader import get_root, load_config
from app.core.paths import character_ref_path
from app.services import character_refs
from app.services.mock_image import create_mock_image as render_mock_image
from app.core.schemas import Character, Location, Scene


def _set_nested(obj: dict, path: list[str], value: Any) -> None:
    cur = obj
    for key in path[:-1]:
        cur = cur[key]
    cur[path[-1]] = value


def _load_workflow() -> dict[str, Any]:
    cfg = load_config("comfyui")
    wf_path = get_root() / cfg["workflow_path"]
    with open(wf_path, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not str(k).startswith("_")}


async def comfyui_reachable() -> bool:
    cfg = load_config("comfyui")
    if cfg.get("mock", False):
        return False
    host = cfg.get("host", "http://127.0.0.1:8188")
    if host.startswith("${"):
        host = "http://127.0.0.1:8188"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{host.rstrip('/')}/system_stats")
            return r.status_code == 200
    except Exception:
        return False


async def _upload_image(host: str, image_path: Path) -> str:
    """Upload image to ComfyUI input folder; returns filename for workflow."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        with open(image_path, "rb") as f:
            files = {"image": (image_path.name, f, "image/png")}
            data = {"overwrite": "true"}
            r = await client.post(f"{host.rstrip('/')}/upload/image", files=files, data=data)
        r.raise_for_status()
        return r.json().get("name", image_path.name)


async def _poll_history(host: str, prompt_id: str) -> dict:
    cfg = load_config("comfyui")
    interval = cfg.get("poll_interval_sec", 2)
    timeout = cfg.get("poll_timeout_sec", 300)
    elapsed = 0.0
    async with httpx.AsyncClient(timeout=30.0) as client:
        while elapsed < timeout:
            r = await client.get(f"{host.rstrip('/')}/history/{prompt_id}")
            if r.status_code == 200:
                data = r.json()
                if prompt_id in data:
                    return data[prompt_id]
            await asyncio.sleep(interval)
            elapsed += interval
    raise TimeoutError(f"ComfyUI prompt {prompt_id} timed out")


async def generate_scene_image(
    scene: Scene,
    characters: list[Character],
    output_path: Path,
    ref_image: Path | None = None,
    novel_name: str | None = None,
    locations: list[Location] | None = None,
) -> Path:
    cfg = load_config("comfyui")
    use_mock = cfg.get("mock", True)
    host = cfg.get("host", "http://127.0.0.1:8188")
    if host.startswith("${"):
        host = "http://127.0.0.1:8188"

    char_map = {c.id: c for c in characters}
    loc_map = {loc.id: loc for loc in (locations or [])}
    prompt = character_refs.build_scene_visual_prompt(
        scene,
        char_map,
        loc_map,
        with_ref=bool(ref_image and ref_image.exists()),
    )

    if use_mock or not await comfyui_reachable():
        return render_mock_image(scene, characters, output_path)

    workflow = copy.deepcopy(_load_workflow())
    mappings = cfg.get("input_mappings", {})

    pos_path = mappings.get("positive_prompt", ["6", "inputs", "text"])
    neg_path = mappings.get("negative_prompt", ["7", "inputs", "text"])
    _set_nested(workflow, [str(pos_path[0])] + pos_path[1:], prompt)
    _set_nested(
        workflow,
        [str(neg_path[0])] + neg_path[1:],
        cfg.get("default_negative", "low quality"),
    )

    if ref_image and ref_image.exists():
        ref_name = await _upload_image(host, ref_image)
        ref_path = mappings.get("reference_image")
        if ref_path:
            _set_nested(workflow, [str(ref_path[0])] + ref_path[1:], ref_name)

    client_id = "novel_video"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{host.rstrip('/')}/prompt",
            json={"prompt": workflow, "client_id": client_id},
        )
        r.raise_for_status()
        prompt_id = r.json()["prompt_id"]

    history = await _poll_history(host, prompt_id)
    outputs = history.get("outputs", {})
    for node_out in outputs.values():
        images = node_out.get("images", [])
        if images:
            img_info = images[0]
            filename = img_info["filename"]
            subfolder = img_info.get("subfolder", "")
            img_type = img_info.get("type", "output")
            url = (
                f"{host.rstrip('/')}/view?"
                f"filename={filename}&subfolder={subfolder}&type={img_type}"
            )
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(resp.content)
                return output_path

    raise RuntimeError(f"No image output from ComfyUI for scene {scene.id}")


async def generate_character_ref(
    character: Character,
    output_path: Path,
    novel_name: str,
) -> Path:
    """Generate reference portrait for IP-Adapter consistency."""
    scene = character_refs.portrait_scene(character)
    return await generate_scene_image(
        scene, [character], output_path, ref_image=None, novel_name=novel_name
    )


async def generate_all_images(
    work_dir: Path,
    characters: list[Character],
    scenes: list[Scene],
    novel_name: str,
    locations: list[Location] | None = None,
) -> list[Scene]:
    locs = locations or []
    characters = character_refs.merge_with_novel_registry(novel_name, characters)
    locs = character_refs.merge_locations(novel_name, locs)
    character_refs.sync_ref_paths(characters, novel_name)

    images_dir = work_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    char_map = {c.id: c for c in characters}
    for char in characters:
        ref_path = character_ref_path(novel_name, char.id)
        if not ref_path.exists():
            ref_path.parent.mkdir(parents=True, exist_ok=True)
            await generate_character_ref(char, ref_path, novel_name)
        char.ref_image = str(ref_path)

    character_refs.save_registry(novel_name, characters, locs)

    updated: list[Scene] = []
    for scene in scenes:
        ref: Path | None = None
        if scene.character_ids:
            ref = character_refs.pick_scene_ref_image(scene, char_map, novel_name)
        out = images_dir / f"{scene.id}.png"
        await generate_scene_image(
            scene,
            characters,
            out,
            ref_image=ref,
            novel_name=novel_name,
            locations=locs,
        )
        scene.image_path = str(out)
        updated.append(scene)

    character_refs.save_registry(novel_name, characters, locs)
    return updated

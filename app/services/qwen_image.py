"""Alibaba DashScope Qwen-Image text-to-image (serial, sync HTTP + backoff)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

import httpx

from app.core.config_loader import load_config
from app.core.paths import character_ref_path
from app.core.schemas import Character, Location, Scene
from app.services import character_refs

logger = logging.getLogger(__name__)

_ENV_IN_KEY = re.compile(r"\$\{([^}]+)\}")


def _api_key(cfg: dict) -> str:
    key = cfg.get("api_key", "")
    if key.startswith("${"):
        raise ValueError(
            f"{_ENV_IN_KEY.search(key).group(1) if _ENV_IN_KEY.search(key) else 'DASHSCOPE_API_KEY'} "
            "not set in .env"
        )
    return key


def _generation_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/services/aigc/multimodal-generation/generation"


def _extract_image_urls(data: dict) -> list[str]:
    urls: list[str] = []
    output = data.get("output") or {}
    choices = output.get("choices") or []
    for choice in choices:
        message = choice.get("message") or {}
        content = message.get("content") or []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("image"):
                    urls.append(item["image"])
        elif isinstance(content, dict) and content.get("image"):
            urls.append(content["image"])
    if not urls and output.get("results"):
        for item in output["results"]:
            if isinstance(item, dict) and item.get("url"):
                urls.append(item["url"])
    return urls


def _retry_backoff_sec(cfg: dict) -> list[float]:
    retry = cfg.get("retry", {})
    backoff = retry.get("backoff_sec", [5, 15, 30])
    return [float(x) for x in backoff]


def _max_attempts(cfg: dict) -> int:
    retry = cfg.get("retry", {})
    backoff = _retry_backoff_sec(cfg)
    return int(retry.get("max_attempts", len(backoff) + 1))


def _request_interval_sec(cfg: dict) -> float:
    """Min seconds between scene requests (Qwen image pro: 2 RPM)."""
    if "request_interval_sec" in cfg:
        return float(cfg["request_interval_sec"])
    rpm = float(cfg.get("rate_limit_rpm", 2))
    rpm = max(rpm, 0.1)
    return 60.0 / rpm + 2.0


def _post_with_retry(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    body: dict,
    scene_id: str,
    cfg: dict,
) -> dict:
    backoff = _retry_backoff_sec(cfg)
    max_attempts = _max_attempts(cfg)
    min_wait = _request_interval_sec(cfg)
    last_err: Exception | None = None

    for attempt in range(max_attempts):
        resp = client.post(url, headers=headers, json=body)
        if resp.status_code == 429:
            wait = backoff[min(attempt, len(backoff) - 1)] if backoff else 5.0
            wait = max(wait, min_wait)
            logger.warning(
                "Qwen image 429 for %s, attempt %s/%s, sleep %.0fs",
                scene_id,
                attempt + 1,
                max_attempts,
                wait,
            )
            time.sleep(wait)
            last_err = httpx.HTTPStatusError(
                "429 Too Many Requests",
                request=resp.request,
                response=resp,
            )
            continue

        try:
            resp.raise_for_status()
            data = resp.json()
            if data.get("code"):
                raise RuntimeError(f"Qwen image API error: {data.get('message', data)}")
            return data
        except httpx.HTTPStatusError as e:
            last_err = e
            if e.response.status_code == 429 and attempt < max_attempts - 1:
                wait = backoff[min(attempt, len(backoff) - 1)] if backoff else 5.0
                wait = max(wait, min_wait)
                time.sleep(wait)
                continue
            raise

    raise RuntimeError(
        f"Qwen image rate limited for {scene_id} after {max_attempts} attempts"
    ) from last_err


def _build_messages_content(
    prompt: str,
    ref_image: Path | None,
    cfg: dict,
) -> list[dict]:
    """Qwen 2.0: optional reference image + text prompt."""
    if ref_image and ref_image.is_file() and cfg.get("use_character_ref", True):
        return [
            {"image": character_refs.image_to_data_uri(ref_image)},
            {"text": prompt},
        ]
    return [{"text": prompt}]


def generate_scene_image_sync(
    scene: Scene,
    output_path: Path,
    *,
    characters: list[Character] | None = None,
    locations: list[Location] | None = None,
    ref_image: Path | None = None,
    novel_name: str | None = None,
    size_override: str | None = None,
) -> Path:
    """Blocking: one scene, one request chain, with 429 backoff."""
    cfg = load_config("image")
    api_key = _api_key(cfg)
    char_map = {c.id: c for c in (characters or [])}
    loc_map = {loc.id: loc for loc in (locations or [])}

    visual = character_refs.build_scene_visual_prompt(
        scene,
        char_map,
        loc_map,
        with_ref=bool(ref_image and ref_image.is_file()),
    )
    prefix = cfg.get("style_prefix", "").strip()
    suffix = cfg.get("style_suffix", "").strip()
    prompt = visual
    if prefix:
        prompt = f"{prefix} {prompt}"
    if suffix:
        prompt = f"{prompt}, {suffix}"

    body = {
        "model": cfg.get("model", "qwen-image-2.0-pro-2026-04-22"),
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": _build_messages_content(prompt, ref_image, cfg),
                }
            ]
        },
        "parameters": {
            "size": size_override or cfg.get("size", "1080*1920"),
            "n": 1,
            "watermark": cfg.get("watermark", False),
            "prompt_extend": cfg.get("prompt_extend", True),
            "negative_prompt": cfg.get("negative_prompt", ""),
        },
    }

    timeout = float(cfg.get("request_timeout_sec", 180))
    url = _generation_url(cfg["base_url"])
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=timeout) as client:
        data = _post_with_retry(client, url, headers, body, scene.id, cfg)
        urls = _extract_image_urls(data)
        if not urls:
            raise RuntimeError(f"No image URL in Qwen response for {scene.id}")

        img_resp = client.get(urls[0])
        img_resp.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(img_resp.content)

    return output_path


def _sleep_interval(cfg: dict, label: str) -> None:
    interval = _request_interval_sec(cfg)
    logger.info("Qwen image: wait %.1fs before %s", interval, label)
    time.sleep(interval)


def _ensure_character_refs(
    novel_name: str,
    characters: list[Character],
    cfg: dict,
    *,
    after_api_call: bool,
) -> bool:
    """Generate and persist ref.png per character under data/{小说名}/characters/."""
    portrait_size = cfg.get("ref_portrait_size", "768*1152")
    for char in characters:
        ref_path = character_ref_path(novel_name, char.id)
        if ref_path.is_file():
            char.ref_image = str(ref_path)
            continue
        if after_api_call:
            _sleep_interval(cfg, f"ref_{char.id}")
            after_api_call = True

        ref_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Qwen image: character ref portrait for %s (%s)", char.name, char.id)
        scene = character_refs.portrait_scene(char)
        generate_scene_image_sync(
            scene,
            ref_path,
            characters=[char],
            ref_image=None,
            novel_name=novel_name,
            size_override=portrait_size,
        )
        char.ref_image = str(ref_path)
        after_api_call = True
    return after_api_call


def generate_all_images_sync(
    work_dir: Path,
    characters: list[Character],
    scenes: list[Scene],
    novel_name: str,
    locations: list[Location] | None = None,
) -> list[Scene]:
    """Serial generation with per-novel character ref images."""
    cfg = load_config("image")
    interval = _request_interval_sec(cfg)
    images_dir = work_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    characters = character_refs.merge_with_novel_registry(novel_name, characters)
    character_refs.sync_ref_paths(characters, novel_name)

    had_api = False
    locs = locations or []
    if cfg.get("use_character_ref", True) and characters:
        had_api = _ensure_character_refs(novel_name, characters, cfg, after_api_call=False)
        character_refs.save_registry(novel_name, characters, locs)

    char_map = {c.id: c for c in characters}
    loc_map = {loc.id: loc for loc in locs}
    updated: list[Scene] = []
    for index, scene in enumerate(scenes):
        if had_api or index > 0:
            logger.info("Qwen image: wait %.1fs before %s", interval, scene.id)
            time.sleep(interval)
        had_api = True

        ref = None
        if scene.character_ids and cfg.get("use_character_ref", True):
            ref = character_refs.pick_scene_ref_image(scene, char_map, novel_name)

        out = images_dir / f"{scene.id}.png"
        logger.info(
            "Qwen image: generating %s (%s/%s)%s",
            scene.id,
            index + 1,
            len(scenes),
            " with ref" if ref else "",
        )
        generate_scene_image_sync(
            scene,
            out,
            characters=characters,
            locations=locs,
            ref_image=ref,
            novel_name=novel_name,
        )
        scene.image_path = str(out)
        updated.append(scene)

    character_refs.save_registry(novel_name, characters, locs)
    return updated


async def generate_scene_image(scene: Scene, output_path: Path, **kwargs) -> Path:
    return await asyncio.to_thread(generate_scene_image_sync, scene, output_path, **kwargs)


async def generate_all_images(
    work_dir: Path,
    characters: list[Character],
    scenes: list[Scene],
    novel_name: str,
    locations: list[Location] | None = None,
) -> list[Scene]:
    return await asyncio.to_thread(
        generate_all_images_sync,
        work_dir,
        characters,
        scenes,
        novel_name,
        locations,
    )

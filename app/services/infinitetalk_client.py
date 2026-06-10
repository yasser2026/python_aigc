"""InfiniteTalk audio-driven talking-head client via ComfyUI.

Drives a character still with the scene's TTS audio to produce a lip-synced
clip for dialogue shots. Raises on failure so the caller can fall back to
Ken Burns.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from app.core.config_loader import load_config
from app.core.schemas import Scene
from app.services import comfyui_common as cc

logger = logging.getLogger(__name__)


async def generate_clip(
    scene: Scene,
    image_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    cfg = load_config("infinitetalk")
    host = cc.resolve_host("infinitetalk")

    if cfg.get("mock", False) or not await cc.reachable(host):
        raise RuntimeError("InfiniteTalk service unreachable")
    if not audio_path.is_file():
        raise RuntimeError("InfiniteTalk requires scene audio")

    img_name = await cc.upload_input_file(host, image_path, "image/png")
    audio_name = await cc.upload_input_file(host, audio_path, "audio/mpeg")

    workflow = copy.deepcopy(cc.load_workflow("infinitetalk"))
    m = cfg.get("input_mappings", {})
    if m.get("image"):
        cc.set_nested(workflow, m["image"], img_name)
    if m.get("audio"):
        cc.set_nested(workflow, m["audio"], audio_name)
    if m.get("positive_prompt"):
        cc.set_nested(workflow, m["positive_prompt"], cfg.get("default_prompt", ""))
    if m.get("width"):
        cc.set_nested(workflow, m["width"], cfg.get("width", 720))
    if m.get("height"):
        cc.set_nested(workflow, m["height"], cfg.get("height", 1280))

    prompt_id = await cc.submit_prompt(host, workflow, client_id="infinitetalk")
    history = await cc.poll_history(
        host,
        prompt_id,
        interval=cfg.get("poll_interval_sec", 3),
        timeout=cfg.get("poll_timeout_sec", 900),
    )
    return await cc.fetch_video_output(host, history, output_path)

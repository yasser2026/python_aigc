"""Wan2.1 image-to-video (I2V) client via ComfyUI.

Turns a scene still into a short animated clip. Resolution tier is chosen per
scene type (key character shots get the high tier, pass shots the cheap tier)
to fit a single 24G GPU. Raises on failure so the caller can fall back to
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


def _pick_tier(scene: Scene, cfg: dict) -> dict:
    tiers = cfg.get("resolution_tiers", {})
    high_types = cfg.get("high_tier_scene_types", ["character"])
    tier_name = "high" if (scene.scene_type in high_types and "high" in tiers) else cfg.get(
        "default_tier", "low"
    )
    return tiers.get(tier_name, {"width": 480, "height": 854})


async def generate_clip(
    scene: Scene,
    image_path: Path,
    output_path: Path,
    duration_sec: float,
    *,
    motion_prompt: str | None = None,
) -> Path:
    cfg = load_config("wan_i2v")
    host = cc.resolve_host("wan_i2v")

    if cfg.get("mock", False) or not await cc.reachable(host):
        raise RuntimeError("Wan I2V service unreachable")

    tier = _pick_tier(scene, cfg)
    fps = int(cfg.get("fps", 16))
    max_dur = float(cfg.get("max_duration_sec", duration_sec) or duration_sec)
    dur = min(duration_sec, max_dur) if max_dur else duration_sec
    num_frames = max(8, int(dur * fps))

    prompt = motion_prompt or scene.visual_prompt or ""
    suffix = cfg.get("motion_prompt_suffix", "")
    if suffix:
        prompt = f"{prompt}, {suffix}" if prompt else suffix

    host_name = await cc.upload_input_file(host, image_path, "image/png")

    workflow = copy.deepcopy(cc.load_workflow("wan_i2v"))
    m = cfg.get("input_mappings", {})
    if m.get("image"):
        cc.set_nested(workflow, m["image"], host_name)
    if m.get("positive_prompt"):
        cc.set_nested(workflow, m["positive_prompt"], prompt)
    if m.get("negative_prompt"):
        cc.set_nested(workflow, m["negative_prompt"], cfg.get("default_negative", ""))
    if m.get("num_frames"):
        cc.set_nested(workflow, m["num_frames"], num_frames)
    if m.get("width"):
        cc.set_nested(workflow, m["width"], tier.get("width", 480))
    if m.get("height"):
        cc.set_nested(workflow, m["height"], tier.get("height", 854))

    prompt_id = await cc.submit_prompt(host, workflow, client_id="wan_i2v")
    history = await cc.poll_history(
        host,
        prompt_id,
        interval=cfg.get("poll_interval_sec", 3),
        timeout=cfg.get("poll_timeout_sec", 900),
    )
    return await cc.fetch_video_output(host, history, output_path)

"""Reachability checks for the anime-mode AutoDL GPU services.

Anime generation has no mock fallback for its core stages: it must reach the
real ComfyUI (image) and Wan2.1 I2V (animation) services. If those are down we
report the feature as unavailable so the frontend can disable it. Voice cloning
(GPT-SoVITS) and talking-head (InfiniteTalk) are optional — they degrade to
edge-tts / Ken Burns — so they don't gate availability.
"""

from __future__ import annotations

import asyncio

from app.core.runtime import set_mode
from app.services import comfyui_client, gptsovits_client
from app.services import comfyui_common as cc

UNAVAILABLE_MESSAGE = "生成动画模块技术升级中，暂时关闭"


async def _safe(coro) -> bool:
    try:
        return bool(await coro)
    except Exception:
        return False


async def check_anime_services() -> dict:
    """Probe all anime-mode services in parallel under the anime config set."""
    set_mode("anime")

    comfy_ok, wan_ok, talk_ok, sovits_ok = await asyncio.gather(
        _safe(comfyui_client.comfyui_reachable()),
        _safe(cc.reachable(cc.resolve_host("wan_i2v"))),
        _safe(cc.reachable(cc.resolve_host("infinitetalk"))),
        _safe(gptsovits_client.reachable()),
    )

    available = comfy_ok and wan_ok
    return {
        "available": available,
        "comfyui": comfy_ok,
        "wan_i2v": wan_ok,
        "infinitetalk": talk_ok,
        "gptsovits": sovits_ok,
        "message": None if available else UNAVAILABLE_MESSAGE,
    }

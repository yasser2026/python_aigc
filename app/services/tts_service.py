"""Edge TTS narration per scene."""

from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts

from app.core.config_loader import load_config
from app.core.schemas import Scene


async def synthesize_scene(scene: Scene, output_path: Path) -> float:
    """Generate MP3 and return duration in seconds."""
    cfg = load_config("tts")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    communicate = edge_tts.Communicate(
        scene.narration,
        voice=cfg.get("voice", "zh-CN-XiaoxiaoNeural"),
        rate=cfg.get("rate", "+0%"),
        volume=cfg.get("volume", "+0%"),
    )
    await communicate.save(str(output_path))

    duration = await _get_audio_duration(output_path)
    if duration <= 0:
        duration = estimate_duration_from_text(scene.narration)
    scene.audio_path = str(output_path)
    scene.duration_sec = duration
    return duration


async def _get_audio_duration(path: Path) -> float:
    """Probe duration via ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode == 0 and stdout.strip():
        try:
            return float(stdout.decode().strip())
        except ValueError:
            pass
    return 4.0


def estimate_duration_from_text(text: str) -> float:
    """Rough duration when ffprobe unavailable (~4 chars/sec)."""
    return max(3.0, len(text) / 4.0)

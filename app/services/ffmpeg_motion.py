"""FFmpeg Ken Burns: static image to video clip."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from app.core.config_loader import load_config
from app.core.schemas import Scene


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


async def image_to_clip(
    image_path: Path,
    output_path: Path,
    duration_sec: float,
) -> Path:
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg not found in PATH")

    cfg = load_config("ffmpeg")
    pipeline = load_config("pipeline")
    w = cfg.get("width", 1920)
    h = cfg.get("height", 1080)
    fps = cfg.get("fps", 24)
    kb = cfg.get("ken_burns", {})
    codec = cfg.get("codec", "libx264")
    preset = cfg.get("preset", "medium")
    crf = cfg.get("crf", 23)

    duration_sec = max(duration_sec, pipeline.get("scene_duration_sec", 4))
    frames = int(duration_sec * fps)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if kb.get("enabled", True):
        z_start = kb.get("zoom_start", 1.0)
        z_end = kb.get("zoom_end", 1.15)
        # zoompan: slow zoom in
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},"
            f"zoompan=z='min({z_end},{z_start}+(on/{frames})*({z_end}-{z_start}))':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={w}x{h}:fps={fps}"
        )
    else:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps}"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-vf", vf,
        "-t", str(duration_sec),
        "-c:v", codec,
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-an",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg motion failed: {stderr.decode(errors='replace')[-500:]}")

    return output_path


async def merge_audio_to_clip(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    duration_sec: float,
) -> Path:
    """Mux narration audio onto silent video clip."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-t", str(duration_sec),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mux audio failed: {stderr.decode(errors='replace')[-500:]}")
    return output_path

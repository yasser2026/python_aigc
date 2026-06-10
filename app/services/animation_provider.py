"""Animation router for anime mode: per-scene I2V / talking-head / Ken Burns.

Routing by scene type:
  - dialogue/character shots with audio -> InfiniteTalk (lip sync)
  - environment/crowd/other          -> Wan2.1 I2V (animated still)
  - any failure                      -> Ken Burns (existing ffmpeg_motion)

Always returns a final clip in ``clips_dir``; clips carry the scene audio so
the assemble stage is unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.core.config_loader import load_config
from app.core.schemas import Scene
from app.services import (
    ffmpeg_motion,
    infinitetalk_client,
    wan_i2v_client,
)

logger = logging.getLogger(__name__)


async def animate_scene(
    scene: Scene,
    image_path: Path,
    clips_dir: Path,
    duration_sec: float,
    *,
    novel_name: str | None = None,
) -> Path:
    clips_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config("pipeline")
    anim = cfg.get("animation", {})
    effective_type = scene.scene_type or "environment"

    final_clip = clips_dir / f"{scene.id}.mp4"
    audio_path = Path(scene.audio_path) if scene.audio_path else None
    has_audio = bool(audio_path and audio_path.is_file())

    talk_cfg = anim.get("talk", {})
    if (
        talk_cfg.get("enabled", True)
        and effective_type in talk_cfg.get("scene_types", ["character"])
        and (has_audio or not talk_cfg.get("require_audio", True))
    ):
        try:
            clip = await infinitetalk_client.generate_clip(
                scene, image_path, audio_path, final_clip
            )
            logger.info("Scene %s animated via InfiniteTalk", scene.id)
            return clip
        except Exception as exc:  # noqa: BLE001
            logger.warning("InfiniteTalk failed for %s (%s), trying I2V", scene.id, exc)

    i2v_cfg = anim.get("i2v", {})
    if i2v_cfg.get("enabled", True) and effective_type in i2v_cfg.get(
        "scene_types", ["environment", "crowd", "character"]
    ):
        try:
            silent = clips_dir / f"{scene.id}_i2v.mp4"
            await wan_i2v_client.generate_clip(
                scene, image_path, silent, duration_sec
            )
            logger.info("Scene %s animated via Wan I2V", scene.id)
            if has_audio:
                await _mux_audio_extend(silent, audio_path, final_clip, duration_sec)
                return final_clip
            silent_final = clips_dir / f"{scene.id}_silent.mp4"
            silent.replace(silent_final)
            return silent_final
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Wan I2V failed for %s (%s), falling back to Ken Burns", scene.id, exc
            )

    return await _ken_burns(scene, image_path, clips_dir, duration_sec, has_audio, audio_path)


async def _ken_burns(
    scene: Scene,
    image_path: Path,
    clips_dir: Path,
    duration_sec: float,
    has_audio: bool,
    audio_path: Path | None,
) -> Path:
    silent_clip = clips_dir / f"{scene.id}_silent.mp4"
    await ffmpeg_motion.image_to_clip(image_path, silent_clip, duration_sec)
    if has_audio and audio_path is not None:
        final_clip = clips_dir / f"{scene.id}.mp4"
        await ffmpeg_motion.merge_audio_to_clip(
            silent_clip, audio_path, final_clip, duration_sec
        )
        return final_clip
    return silent_clip


async def _mux_audio_extend(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    target_dur: float,
) -> Path:
    """Mux audio onto an I2V clip, holding the last frame to reach audio length.

    I2V clips are short; cloning the final frame avoids cutting off narration
    while keeping the motion natural (motion then a brief hold).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-filter_complex",
        f"[0:v]tpad=stop_mode=clone:stop_duration={target_dur}[v]",
        "-map", "[v]",
        "-map", "1:a",
        "-t", str(target_dur),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg i2v mux failed: {stderr.decode(errors='replace')[-400:]}"
        )
    return output_path

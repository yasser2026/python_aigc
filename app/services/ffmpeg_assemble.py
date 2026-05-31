"""FFmpeg final assembly: concat clips, subtitles, optional BGM."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from app.core.config_loader import load_config


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


async def concat_clips(clip_paths: list[Path], output_path: Path) -> Path:
    if not clip_paths:
        raise ValueError("No clips to concat")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = output_path.parent / "concat_list.txt"
    # Use forward slashes for ffmpeg concat demuxer on Windows
    lines = [f"file '{p.resolve().as_posix()}'" for p in clip_paths]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {stderr.decode(errors='replace')[-500:]}")
    return output_path


async def burn_subtitles(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Escape path for ffmpeg filter on Windows
    ass_escaped = ass_path.resolve().as_posix().replace(":", "\\:")
    vf = f"subtitles='{ass_escaped}'"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-c:a", "copy",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        # Fallback: copy without subtitles if burn fails (font missing etc.)
        shutil.copy2(video_path, output_path)
    return output_path


async def add_bgm(
    video_path: Path,
    bgm_path: Path,
    output_path: Path,
    bgm_volume: float = 0.2,
) -> Path:
    if not bgm_path.exists():
        shutil.copy2(video_path, output_path)
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(bgm_path),
        "-filter_complex",
        f"[1:a]volume={bgm_volume}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        shutil.copy2(video_path, output_path)
    return output_path


async def assemble_final(
    clip_paths: list[Path],
    ass_path: Path | None,
    output_path: Path,
) -> Path:
    cfg = load_config("ffmpeg")
    work = output_path.parent
    merged = work / "_merged.mp4"
    await concat_clips(clip_paths, merged)

    if ass_path and ass_path.exists():
        subtitled = work / "_subtitled.mp4"
        await burn_subtitles(merged, ass_path, subtitled)
        merged = subtitled

    bgm_cfg = cfg.get("bgm", {})
    if bgm_cfg.get("enabled") and bgm_cfg.get("path"):
        bgm_p = Path(bgm_cfg["path"])
        if bgm_p.exists():
            final_with_bgm = work / "_bgm.mp4"
            await add_bgm(merged, bgm_p, final_with_bgm, bgm_cfg.get("volume", 0.2))
            merged = final_with_bgm

    shutil.copy2(merged, output_path)
    return output_path

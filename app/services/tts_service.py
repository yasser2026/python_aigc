"""Edge TTS narration per scene."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import edge_tts
from edge_tts.exceptions import NoAudioReceived

from app.core.config_loader import load_config
from app.core.schemas import Character, Scene
from app.services import graph_context

logger = logging.getLogger(__name__)


def _build_communicate(
    text: str,
    *,
    voice: str,
    rate: str,
    volume: str,
) -> edge_tts.Communicate:
    return edge_tts.Communicate(text, voice=voice, rate=rate, volume=volume)


def resolve_voice(
    scene: Scene,
    char_map: dict[str, Character],
    cfg: dict | None = None,
) -> str:
    """Pick Edge TTS voice: narrator default or character profile."""
    cfg = cfg or load_config("tts")
    narrator = cfg.get("narrator_voice") or cfg.get("voice", "zh-CN-XiaoxiaoNeural")
    speaker_id = scene.narration_speaker_id
    if not speaker_id or speaker_id not in char_map:
        return narrator

    voice_map = cfg.get("voice_map") or {}
    if speaker_id in voice_map:
        return voice_map[speaker_id]

    ch = char_map[speaker_id]
    gender = ch.gender or "unknown"
    age = ch.age_group or "unknown"
    profile_key = f"{gender}_{age}"
    by_profile = cfg.get("voice_by_profile") or {}
    return by_profile.get(profile_key) or by_profile.get("unknown_unknown") or narrator


def _retry_backoff_sec(cfg: dict) -> list[float]:
    retry = cfg.get("retry", {})
    backoff = retry.get("backoff_sec", [3, 8, 15])
    return [float(x) for x in backoff]


def _max_tts_attempts(cfg: dict) -> int:
    retry = cfg.get("retry", {})
    backoff = _retry_backoff_sec(cfg)
    return int(retry.get("max_attempts", len(backoff) + 1))


def _voice_candidates(primary: str, cfg: dict) -> list[str]:
    """Ordered voices to try; primary first, then configured fallbacks."""
    candidates = [primary]
    for voice in cfg.get("voice_fallback_chain") or []:
        if voice and voice not in candidates:
            candidates.append(voice)
    narrator = cfg.get("narrator_voice") or cfg.get("voice")
    if narrator and narrator not in candidates:
        candidates.append(narrator)
    return candidates


async def synthesize_scene(
    scene: Scene,
    output_path: Path,
    *,
    char_map: dict[str, Character] | None = None,
    novel_name: str | None = None,
) -> float:
    """Generate MP3 and return duration in seconds."""
    cfg = load_config("tts")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scene = graph_context.validate_scene_speaker(scene)

    if (
        cfg.get("skip_existing_audio", True)
        and output_path.is_file()
        and output_path.stat().st_size > 256
    ):
        duration = await _get_audio_duration(output_path)
        if duration <= 0:
            duration = estimate_duration_from_text(scene.narration)
        scene.audio_path = str(output_path)
        scene.duration_sec = duration
        return duration

    voice = resolve_voice(scene, char_map or {}, cfg)

    rate = cfg.get("rate", "+0%")
    if novel_name:
        rel_rate = graph_context.get_relation_tts_rate(novel_name, scene)
        if rel_rate:
            rate = rel_rate

    max_attempts = _max_tts_attempts(cfg)
    backoff = _retry_backoff_sec(cfg)
    last_err: Exception | None = None
    used_voice = voice
    for voice_idx, try_voice in enumerate(_voice_candidates(voice, cfg)):
        for attempt in range(max_attempts):
            communicate = _build_communicate(
                scene.narration,
                voice=try_voice,
                rate=rate,
                volume=cfg.get("volume", "+0%"),
            )
            try:
                await communicate.save(str(output_path))
                used_voice = try_voice
                last_err = None
                break
            except NoAudioReceived as exc:
                last_err = exc
                if attempt + 1 >= max_attempts:
                    break
                wait = backoff[min(attempt, len(backoff) - 1)]
                logger.warning(
                    "Edge TTS no audio for %s voice=%s (attempt %s/%s), retry in %.0fs",
                    scene.id,
                    try_voice,
                    attempt + 1,
                    max_attempts,
                    wait,
                )
                await asyncio.sleep(wait)
        if last_err is None:
            break
        if voice_idx + 1 < len(_voice_candidates(voice, cfg)):
            logger.warning(
                "Voice %s failed for %s, trying fallback",
                try_voice,
                scene.id,
            )
    if last_err:
        raise last_err
    if used_voice != voice:
        logger.info("Scene %s synthesized with fallback voice %s", scene.id, used_voice)

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

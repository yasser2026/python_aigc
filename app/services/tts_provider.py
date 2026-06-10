"""TTS provider router: edge-tts (default) or GPT-SoVITS voice cloning.

Keeps the same entry point as the legacy service
(``synthesize_scene(scene, output_path, *, char_map, novel_name) -> float``)
so the pipeline runner is agnostic to the backend. In anime mode the config
selects ``provider: gptsovits`` and each character clones from its own
reference audio; on any failure it falls back to edge-tts so a single bad
clone never fails the whole episode.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from app.core.config_loader import load_config
from app.core.paths import character_voice_ref_path
from app.core.schemas import Character, Scene
from app.services import graph_context, gptsovits_client, tts_service

logger = logging.getLogger(__name__)


async def synthesize_scene(
    scene: Scene,
    output_path: Path,
    *,
    char_map: dict[str, Character] | None = None,
    novel_name: str | None = None,
) -> float:
    """Generate MP3 for a scene and return duration in seconds."""
    cfg = load_config("tts")
    provider = str(cfg.get("provider", "edge")).lower()

    if provider != "gptsovits":
        return await tts_service.synthesize_scene(
            scene, output_path, char_map=char_map, novel_name=novel_name
        )

    char_map = char_map or {}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scene = graph_context.validate_scene_speaker(scene)

    if (
        cfg.get("skip_existing_audio", True)
        and output_path.is_file()
        and output_path.stat().st_size > 256
    ):
        duration = await tts_service._get_audio_duration(output_path)
        if duration <= 0:
            duration = tts_service.estimate_duration_from_text(scene.narration)
        scene.audio_path = str(output_path)
        scene.duration_sec = duration
        return duration

    ref_audio, ref_text, char_id = _resolve_voice_ref(scene, char_map, cfg, novel_name)

    if ref_audio is None:
        logger.info(
            "Scene %s has no voice ref (speaker=%s), falling back to edge-tts",
            scene.id,
            scene.narration_speaker_id,
        )
        return await tts_service.synthesize_scene(
            scene, output_path, char_map=char_map, novel_name=novel_name
        )

    try:
        audio_bytes = await _clone_with_retry(
            scene.narration, ref_audio, ref_text, char_id, cfg
        )
        await _write_audio(audio_bytes, output_path, cfg)
    except Exception as exc:  # noqa: BLE001 - degrade gracefully
        logger.warning(
            "GPT-SoVITS failed for scene %s (%s); falling back to edge-tts",
            scene.id,
            exc,
        )
        if cfg.get("fallback_to_edge", True):
            return await tts_service.synthesize_scene(
                scene, output_path, char_map=char_map, novel_name=novel_name
            )
        raise

    duration = await tts_service._get_audio_duration(output_path)
    if duration <= 0:
        duration = tts_service.estimate_duration_from_text(scene.narration)
    scene.audio_path = str(output_path)
    scene.duration_sec = duration
    return duration


def _resolve_voice_ref(
    scene: Scene,
    char_map: dict[str, Character],
    cfg: dict,
    novel_name: str | None,
) -> tuple[Path | None, str, str | None]:
    """Return (ref_audio_path, ref_text, character_id) for the speaker.

    Falls back to the narrator reference when there is no in-scene speaker.
    """
    speaker_id = scene.narration_speaker_id
    if speaker_id and speaker_id in char_map and novel_name:
        char = char_map[speaker_id]
        ref_path = character_voice_ref_path(novel_name, char.id)
        if ref_path.is_file():
            ref_text = char.voice_ref_text or cfg.get("gptsovits", {}).get(
                "default_prompt_text", ""
            )
            return ref_path, ref_text, char.id

    narrator_ref = cfg.get("narrator_voice_ref")
    if narrator_ref:
        ref_path = Path(narrator_ref)
        if not ref_path.is_absolute():
            from app.core.config_loader import get_root

            ref_path = get_root() / narrator_ref
        if ref_path.is_file():
            return ref_path, cfg.get("narrator_voice_ref_text", "") or "", "narrator"

    return None, "", None


async def _clone_with_retry(
    text: str,
    ref_audio: Path,
    ref_text: str,
    char_id: str | None,
    cfg: dict,
) -> bytes:
    retry = cfg.get("retry", {})
    max_attempts = int(retry.get("max_attempts", 3))
    backoff = retry.get("backoff_sec", [3, 8])
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await gptsovits_client.synthesize(
                text, ref_audio, ref_text, character_id=char_id
            )
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt + 1 >= max_attempts:
                break
            wait = backoff[min(attempt, len(backoff) - 1)]
            logger.warning(
                "GPT-SoVITS attempt %s/%s failed (%s), retry in %ss",
                attempt + 1,
                max_attempts,
                exc,
                wait,
            )
            await asyncio.sleep(wait)
    raise last_err or RuntimeError("GPT-SoVITS synthesis failed")


async def _write_audio(audio_bytes: bytes, output_path: Path, cfg: dict) -> None:
    """Write raw (wav) bytes to mp3 via ffmpeg, with optional loudnorm/trim."""
    filters: list[str] = []
    if cfg.get("trim_silence", True):
        filters.append(
            "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-50dB:"
            "stop_periods=1:stop_silence=0.2:stop_threshold=-50dB"
        )
    if cfg.get("loudnorm", True):
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = Path(tmp.name)

    try:
        args = ["ffmpeg", "-y", "-i", str(tmp_path)]
        if filters:
            args += ["-af", ",".join(filters)]
        args += ["-codec:a", "libmp3lame", "-q:a", "2", str(output_path)]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg audio convert failed: {stderr.decode(errors='replace')[-300:]}"
            )
    finally:
        tmp_path.unlink(missing_ok=True)

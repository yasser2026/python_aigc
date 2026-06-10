"""GPT-SoVITS HTTP client for zero-shot voice cloning (anime mode TTS).

Talks to a standalone GPT-SoVITS api_v2 service (default AutoDL :9880). Each
character clones from its own reference audio so multi-character scenes get
distinct voices. Returns raw audio bytes; conversion/normalization to mp3 is
handled by the caller (tts_provider).
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.core.config_loader import load_config

logger = logging.getLogger(__name__)


def _host() -> str:
    cfg = load_config("gptsovits")
    host = cfg.get("host", "http://127.0.0.1:9880")
    if not host or host.startswith("${"):
        host = "http://127.0.0.1:9880"
    return host.rstrip("/")


async def reachable() -> bool:
    host = _host()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{host}/")
            return r.status_code < 500
    except Exception:
        return False


def _server_ref_path(ref_audio: Path, character_id: str | None) -> str:
    """Resolve the reference-audio path string the GPU server should read.

    When the GPU box does not share a filesystem with the app server, set
    ``remote_ref_audio_dir`` in config/gptsovits.json to a synced directory;
    otherwise the local absolute path is passed (works for shared FS / local).
    """
    cfg = load_config("gptsovits")
    remote_dir = cfg.get("remote_ref_audio_dir")
    if remote_dir and character_id:
        return f"{remote_dir.rstrip('/')}/{character_id}/voice_ref.wav"
    return str(ref_audio.resolve())


async def synthesize(
    text: str,
    ref_audio: Path,
    ref_text: str,
    *,
    character_id: str | None = None,
) -> bytes:
    """Synthesize speech bytes (wav) cloning the given reference voice.

    Raises on transport/HTTP errors so the caller can fall back to edge-tts.
    """
    cfg = load_config("gptsovits")
    host = _host()
    endpoint = cfg.get("tts_endpoint", "/tts")
    timeout = cfg.get("request_timeout_sec", 120)

    payload = {
        "text": text,
        "text_lang": cfg.get("text_lang", "zh"),
        "ref_audio_path": _server_ref_path(ref_audio, character_id),
        "prompt_text": ref_text or "",
        "prompt_lang": cfg.get("prompt_lang", "zh"),
        "top_k": cfg.get("top_k", 5),
        "top_p": cfg.get("top_p", 1.0),
        "temperature": cfg.get("temperature", 1.0),
        "speed_factor": cfg.get("speed_factor", 1.0),
        "media_type": cfg.get("media_type", "wav"),
        "batch_size": cfg.get("batch_size", 1),
        "streaming_mode": cfg.get("streaming_mode", False),
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{host}{endpoint}", json=payload)
        if r.status_code != 200:
            raise RuntimeError(
                f"GPT-SoVITS {r.status_code}: {r.text[:200]}"
            )
        content = r.content
    if not content or len(content) < 256:
        raise RuntimeError("GPT-SoVITS returned empty audio")
    return content

"""Per-request/pipeline mode context (video | anime).

A single ContextVar threads the active mode through the whole pipeline so that
config loading and data-root resolution can branch without passing `mode` to
every call site.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Literal

Mode = Literal["video", "anime"]

VALID_MODES: tuple[str, ...] = ("video", "anime")

_MODE: ContextVar[str] = ContextVar("aigc_mode", default="video")


def normalize_mode(mode: str | None) -> str:
    """Return a valid mode string, defaulting to 'video'."""
    if not mode:
        return "video"
    m = str(mode).strip().lower()
    return m if m in VALID_MODES else "video"


def set_mode(mode: str | None) -> str:
    """Set the active mode for the current context; returns normalized value."""
    normalized = normalize_mode(mode)
    _MODE.set(normalized)
    return normalized


def get_mode() -> str:
    """Return the active mode (defaults to 'video')."""
    return _MODE.get()


def is_anime() -> bool:
    return get_mode() == "anime"

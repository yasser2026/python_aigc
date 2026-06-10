"""Load JSON configs with ${ENV_VAR} substitution."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.core.runtime import get_mode, normalize_mode

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_CACHE: dict[tuple[str, str], Any] = {}


def get_root() -> Path:
    return _ROOT


def _substitute(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match[str]) -> str:
            key = m.group(1)
            return os.environ.get(key, m.group(0))

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _substitute(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v) for v in value]
    return value


def load_config(name: str, *, reload: bool = False, mode: str | None = None) -> dict[str, Any]:
    """Load config/{name}.json with env substitution.

    In anime mode, prefer config/{name}.anime.json and fall back to the base
    config/{name}.json when the mode-specific file does not exist.
    """
    resolved_mode = normalize_mode(mode) if mode is not None else get_mode()
    cache_key = (name, resolved_mode)
    if not reload and cache_key in _CONFIG_CACHE:
        return _CONFIG_CACHE[cache_key]

    load_dotenv(_ROOT / ".env")
    path = config_path(name, mode=resolved_mode)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = _substitute(data)
    _CONFIG_CACHE[cache_key] = result
    return result


def config_path(name: str, *, mode: str | None = None) -> Path:
    """Resolve the config file path, preferring mode-specific overrides."""
    resolved_mode = normalize_mode(mode) if mode is not None else get_mode()
    if resolved_mode != "video":
        override = _ROOT / "config" / f"{name}.{resolved_mode}.json"
        if override.exists():
            return override
    return _ROOT / "config" / f"{name}.json"

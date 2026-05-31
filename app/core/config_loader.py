"""Load JSON configs with ${ENV_VAR} substitution."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_CACHE: dict[str, Any] = {}


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


def load_config(name: str, *, reload: bool = False) -> dict[str, Any]:
    """Load config/{name}.json with env substitution."""
    if not reload and name in _CONFIG_CACHE:
        return _CONFIG_CACHE[name]

    load_dotenv(_ROOT / ".env")
    path = _ROOT / "config" / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = _substitute(data)
    _CONFIG_CACHE[name] = result
    return result


def config_path(name: str) -> Path:
    return _ROOT / "config" / f"{name}.json"

"""Project directory layout: data/{novel_name}/第{episode}集/."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config_loader import get_root, load_config

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_novel_dir(name: str) -> str:
    """Safe folder name for novel title."""
    name = _INVALID_CHARS.sub("", name.strip())
    name = name.rstrip(". ")
    return name or "未命名小说"


def episode_dir_name(episode: int) -> str:
    return f"第{int(episode):02d}集"


def build_project_id(novel_name: str, episode: int) -> str:
    """API project_id: 小说名/第01集 (relative to data root)."""
    return f"{sanitize_novel_dir(novel_name)}/{episode_dir_name(episode)}"


def build_work_dir(novel_name: str, episode: int) -> Path:
    app_cfg = load_config("app")
    rel = build_project_id(novel_name, episode)
    return get_root() / app_cfg.get("data_root", "data") / rel


def build_novel_dir(novel_name: str) -> Path:
    """data/{小说名}/ — shared assets across episodes."""
    app_cfg = load_config("app")
    return get_root() / app_cfg.get("data_root", "data") / sanitize_novel_dir(novel_name)


def character_ref_path(novel_name: str, character_id: str) -> Path:
    """data/{小说名}/characters/{char_id}/ref.png"""
    return build_novel_dir(novel_name) / "characters" / character_id / "ref.png"


def novel_characters_registry_path(novel_name: str) -> Path:
    return build_novel_dir(novel_name) / "characters.json"


def novel_locations_registry_path(novel_name: str) -> Path:
    return build_novel_dir(novel_name) / "locations.json"


def location_ref_path(novel_name: str, location_id: str) -> Path:
    return build_novel_dir(novel_name) / "locations" / location_id / "ref.png"

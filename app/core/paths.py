"""Project directory layout: data/{novel_name}/第{episode}集/."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config_loader import get_root, load_config
from app.core.runtime import get_mode

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_DEFAULT_DATA_ROOT = {"video": "data", "anime": "data_anime"}


def data_root_for_mode(mode: str | None = None) -> Path:
    """Absolute data root for a mode.

    Each mode's app config (app.json / app.anime.json) declares its own
    ``data_root``; falls back to sane per-mode defaults.
    """
    resolved = mode or get_mode()
    app_cfg = load_config("app", mode=resolved)
    default = _DEFAULT_DATA_ROOT.get(resolved, "data")
    return get_root() / app_cfg.get("data_root", default)


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
    rel = build_project_id(novel_name, episode)
    return data_root_for_mode() / rel


def build_novel_dir(novel_name: str) -> Path:
    """{data_root}/{小说名}/ — shared assets across episodes (per mode)."""
    return data_root_for_mode() / sanitize_novel_dir(novel_name)


def to_storage_path(path: Path | str | None) -> str | None:
    """Path relative to project root with forward slashes (Windows/Linux compatible)."""
    if path is None:
        return None
    text = str(path).strip()
    if not text:
        return None
    p = Path(text)
    root = get_root().resolve()
    if p.is_absolute():
        try:
            rel = p.resolve().relative_to(root)
        except ValueError:
            return text.replace("\\", "/")
    else:
        rel = Path(text.replace("\\", "/"))
    return str(rel).replace("\\", "/")


def resolve_storage_path(stored: str | Path | None) -> Path | None:
    """Resolve project-relative storage path to an absolute Path."""
    if stored is None:
        return None
    text = str(stored).strip()
    if not text:
        return None
    p = Path(text)
    if p.is_absolute():
        return p
    return (get_root() / p).resolve()


def storage_path_is_file(stored: str | Path | None) -> bool:
    resolved = resolve_storage_path(stored)
    return bool(resolved and resolved.is_file())


def character_ref_path(novel_name: str, character_id: str) -> Path:
    """data/{小说名}/characters/{char_id}/ref.png — default variant."""
    return character_variant_ref_path(novel_name, character_id, "default")


def character_variant_ref_path(
    novel_name: str,
    character_id: str,
    variant_id: str = "default",
) -> Path:
    """Default variant: characters/{id}/ref.png; others: characters/{id}/variants/{vid}/ref.png."""
    base = build_novel_dir(novel_name) / "characters" / character_id
    if variant_id == "default":
        return base / "ref.png"
    return base / "variants" / variant_id / "ref.png"


def character_voice_ref_path(novel_name: str, character_id: str) -> Path:
    """{data_root}/{小说名}/characters/{char_id}/voice_ref.wav — TTS clone source."""
    return build_novel_dir(novel_name) / "characters" / character_id / "voice_ref.wav"


def novel_characters_registry_path(novel_name: str) -> Path:
    return build_novel_dir(novel_name) / "characters.json"


def novel_locations_registry_path(novel_name: str) -> Path:
    return build_novel_dir(novel_name) / "locations.json"


def novel_meta_path(novel_name: str) -> Path:
    return build_novel_dir(novel_name) / "novel_meta.json"


def location_ref_path(novel_name: str, location_id: str) -> Path:
    return build_novel_dir(novel_name) / "locations" / location_id / "ref.png"


def novel_knowledge_graph_path(novel_name: str) -> Path:
    """data/{小说名}/knowledge_graph.json — Neo4j fallback + human-readable export."""
    return build_novel_dir(novel_name) / "knowledge_graph.json"

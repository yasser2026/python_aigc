"""Novel-level metadata: protagonist, character profiles."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.config_loader import load_config
from app.core.paths import novel_meta_path
from app.core.schemas import Character, NarrativeMode

logger = logging.getLogger(__name__)

_NAME_SPLIT = re.compile(r"[;；,\，、\s]+")


def parse_protagonist_names(raw: str) -> list[str]:
    """Split character name input by semicolon, comma, ideographic comma, or whitespace."""
    names: list[str] = []
    seen: set[str] = set()
    for part in _NAME_SPLIT.split(raw.strip()):
        name = part.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def format_protagonist_names(names: list[str]) -> str:
    return "；".join(names)


parse_character_names = parse_protagonist_names
format_character_names = format_protagonist_names


def load_novel_meta(novel_name: str) -> dict[str, Any]:
    path = novel_meta_path(novel_name)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid novel_meta: %s", path)
    return {}


def save_novel_meta(novel_name: str, meta: dict[str, Any]) -> None:
    path = novel_meta_path(novel_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def default_narrative_mode() -> NarrativeMode:
    pipeline = load_config("pipeline")
    mode = pipeline.get("narrative_mode_default", "protagonist_focus")
    if mode in ("faithful", "protagonist_focus"):
        return mode
    return "protagonist_focus"


def get_protagonist_id(novel_name: str) -> str | None:
    ids = get_protagonist_ids(novel_name)
    return ids[0] if ids else None


def get_protagonist_ids(novel_name: str) -> list[str]:
    meta = load_novel_meta(novel_name)
    raw_ids = meta.get("protagonist_ids")
    if isinstance(raw_ids, list) and raw_ids:
        return [str(i) for i in raw_ids if i]
    pid = meta.get("protagonist_id")
    return [str(pid)] if pid else []


def get_protagonist_names(novel_name: str) -> list[str]:
    meta = load_novel_meta(novel_name)
    raw = meta.get("protagonist_names")
    if isinstance(raw, list) and raw:
        return [str(n).strip() for n in raw if str(n).strip()]
    name = meta.get("protagonist_name")
    if name:
        return [str(name).strip()]
    ids = get_protagonist_ids(novel_name)
    names: list[str] = []
    for cid in ids:
        n = _name_for_id(novel_name, cid)
        if n:
            names.append(n)
    return names


def get_protagonist_name(novel_name: str) -> str | None:
    names = get_protagonist_names(novel_name)
    return format_protagonist_names(names) if names else None


def is_protagonist_locked(novel_name: str) -> bool:
    return bool(load_novel_meta(novel_name).get("protagonist_locked"))


def get_novel_meta_response(novel_name: str) -> dict[str, Any]:
    meta = load_novel_meta(novel_name)
    names = get_protagonist_names(novel_name)
    ids = get_protagonist_ids(novel_name)
    if names and not ids:
        for name in names:
            cid = _resolve_id_by_name(novel_name, name)
            if cid and cid not in ids:
                ids.append(cid)
    return {
        "novel_name": novel_name,
        "protagonist_id": ids[0] if ids else None,
        "protagonist_ids": ids,
        "protagonist_name": format_protagonist_names(names) if names else None,
        "protagonist_names": names,
        "protagonist_locked": bool(meta.get("protagonist_locked")),
    }


def _name_for_id(novel_name: str, char_id: str) -> str | None:
    from app.services.character_refs import load_character_registry

    entry = load_character_registry(novel_name).get(char_id)
    if entry and entry.get("name"):
        return str(entry["name"])
    meta_chars = load_novel_meta(novel_name).get("characters") or {}
    entry = meta_chars.get(char_id) or {}
    name = entry.get("name")
    return str(name) if name else None


def _resolve_id_by_name(
    novel_name: str,
    name: str,
    characters: list[Character] | None = None,
) -> str | None:
    name = name.strip()
    if not name:
        return None
    name_map = build_name_to_id_map(novel_name, characters)
    return name_map.get(name)


def set_user_protagonist(novel_name: str, protagonist_name: str) -> dict[str, Any]:
    """Set or validate user-specified protagonist(s); lock after first successful set."""
    names = parse_protagonist_names(protagonist_name)
    if not names:
        return get_novel_meta_response(novel_name)

    meta = load_novel_meta(novel_name)
    locked = bool(meta.get("protagonist_locked"))
    existing_names = get_protagonist_names(novel_name)

    if locked:
        if existing_names and existing_names != names:
            raise ValueError(
                f"主角已锁定为「{format_protagonist_names(existing_names)}」，"
                f"不可改为「{format_protagonist_names(names)}」。"
                "如需更换请手动编辑 data/{小说名}/novel_meta.json"
            )
        return get_novel_meta_response(novel_name)

    resolved_ids: list[str] = []
    char_meta = dict(meta.get("characters") or {})
    for name in names:
        char_id = _resolve_id_by_name(novel_name, name)
        if char_id and char_id not in resolved_ids:
            resolved_ids.append(char_id)
            entry = dict(char_meta.get(char_id) or {})
            entry["name"] = name
            entry["role"] = "protagonist"
            char_meta[char_id] = entry

    meta["protagonist_names"] = names
    meta["protagonist_name"] = format_protagonist_names(names)
    meta["protagonist_locked"] = True
    if resolved_ids:
        meta["protagonist_ids"] = resolved_ids
        meta["protagonist_id"] = resolved_ids[0]
        meta["characters"] = char_meta
    if "narrative_mode_default" not in meta:
        meta["narrative_mode_default"] = default_narrative_mode()
    save_novel_meta(novel_name, meta)
    logger.info(
        "Locked protagonists for %s: %s (%s)",
        novel_name,
        names,
        resolved_ids,
    )
    return get_novel_meta_response(novel_name)


def ensure_protagonist_resolved(
    novel_name: str,
    characters: list[Character],
) -> list[str]:
    """Match locked protagonist names to character ids after parse."""
    meta = load_novel_meta(novel_name)
    existing = get_protagonist_ids(novel_name)
    if existing:
        return existing

    names = get_protagonist_names(novel_name)
    if not names:
        return existing

    resolved: list[str] = []
    for pname in names:
        char_id = _resolve_id_by_name(novel_name, pname, characters)
        if not char_id:
            for c in characters:
                if c.name == pname:
                    char_id = c.id
                    break
        if char_id and char_id not in resolved:
            resolved.append(char_id)

    if not resolved:
        return existing

    meta["protagonist_ids"] = resolved
    meta["protagonist_id"] = resolved[0]
    save_novel_meta(novel_name, meta)
    return resolved


def enforce_locked_protagonist_on_characters(
    novel_name: str,
    characters: list[Character],
) -> list[Character]:
    """Force protagonist role onto all locked ids; demote others mislabeled."""
    if not is_protagonist_locked(novel_name):
        return characters

    pids = set(get_protagonist_ids(novel_name))
    if not pids:
        return characters

    updated: list[Character] = []
    for c in characters:
        if c.id in pids:
            updated.append(c.model_copy(update={"role": "protagonist"}))
        elif c.role == "protagonist":
            updated.append(c.model_copy(update={"role": "supporting"}))
        else:
            updated.append(c)
    return updated


def update_from_characters(
    novel_name: str,
    characters: list[Character],
    *,
    protagonist_id: str | None = None,
) -> None:
    """Merge character profiles into novel_meta; respect locked protagonist."""
    meta = load_novel_meta(novel_name)
    char_meta: dict[str, dict] = dict(meta.get("characters") or {})
    locked = bool(meta.get("protagonist_locked"))

    locked_ids = set(get_protagonist_ids(novel_name)) if locked else set()

    for c in characters:
        entry = char_meta.get(c.id, {})
        entry["name"] = c.name
        role = c.role
        if locked and c.id in locked_ids:
            role = "protagonist"
        elif locked and c.role == "protagonist" and c.id not in locked_ids:
            role = "supporting"
        if role:
            entry["role"] = role
        if c.gender:
            entry["gender"] = c.gender
        if c.age_group:
            entry["age_group"] = c.age_group
        if c.aliases:
            entry["aliases"] = list(dict.fromkeys(c.aliases))
        char_meta[c.id] = entry

    pids: list[str] = []
    if locked:
        pids = get_protagonist_ids(novel_name)
        if not pids:
            for name in get_protagonist_names(novel_name):
                cid = _resolve_id_by_name(novel_name, name, characters)
                if cid and cid not in pids:
                    pids.append(cid)
    else:
        if protagonist_id:
            pids = [protagonist_id]
        elif meta.get("protagonist_id"):
            pids = [str(meta["protagonist_id"])]
        else:
            for c in characters:
                if c.role == "protagonist" and c.id not in pids:
                    pids.append(c.id)

    meta["characters"] = char_meta
    if pids:
        meta["protagonist_ids"] = pids
        meta["protagonist_id"] = pids[0]
        resolved_names = [
            _name_for_id(novel_name, cid) or ""
            for cid in pids
        ]
        resolved_names = [n for n in resolved_names if n]
        if not resolved_names:
            resolved_names = get_protagonist_names(novel_name)
        if resolved_names:
            meta["protagonist_names"] = resolved_names
            meta["protagonist_name"] = format_protagonist_names(resolved_names)
    if "narrative_mode_default" not in meta:
        meta["narrative_mode_default"] = default_narrative_mode()
    save_novel_meta(novel_name, meta)


def apply_protagonist_from_analysis(
    novel_name: str,
    book_protagonist_id: str | None,
    *,
    allow_set_if_empty: bool = True,
) -> None:
    """Set protagonist_id from episode analysis only when not user-locked."""
    if not book_protagonist_id:
        return
    if is_protagonist_locked(novel_name):
        return
    meta = load_novel_meta(novel_name)
    if meta.get("protagonist_id") and not allow_set_if_empty:
        return
    if meta.get("protagonist_id"):
        return
    from app.services.character_refs import load_character_registry

    registry = load_character_registry(novel_name)
    if registry and book_protagonist_id not in registry:
        logger.warning(
            "book_protagonist_id %s not in registry, skipping",
            book_protagonist_id,
        )
        return
    meta["protagonist_id"] = book_protagonist_id
    save_novel_meta(novel_name, meta)


def build_name_to_id_map(
    novel_name: str,
    characters: list[Character] | None = None,
) -> dict[str, str]:
    """Map canonical name / alias -> character id."""
    from app.services.character_refs import load_character_registry

    mapping: dict[str, str] = {}
    meta = load_novel_meta(novel_name)
    meta_chars = meta.get("characters") or {}

    def add_name(name: str, cid: str) -> None:
        name = name.strip()
        if name and name not in mapping:
            mapping[name] = cid

    registry = load_character_registry(novel_name)
    for cid, entry in registry.items():
        add_name(entry.get("name", ""), cid)
        for alias in entry.get("aliases") or []:
            add_name(str(alias), cid)
        m_entry = meta_chars.get(cid) or {}
        for alias in m_entry.get("aliases") or []:
            add_name(str(alias), cid)

    for c in characters or []:
        add_name(c.name, c.id)
        for alias in c.aliases:
            add_name(alias, c.id)

    return mapping


def build_variant_alias_map(
    novel_name: str,
    characters: list[Character] | None = None,
) -> dict[str, tuple[str, str]]:
    """Map variant-level alias -> (character_id, variant_id)."""
    from app.services.character_refs import load_character_registry

    mapping: dict[str, tuple[str, str]] = {}
    registry = load_character_registry(novel_name)

    def add_alias(alias: str, cid: str, vid: str) -> None:
        alias = alias.strip()
        if alias and alias not in mapping:
            mapping[alias] = (cid, vid)

    for cid, entry in registry.items():
        for vid, v in (entry.get("variants") or {}).items():
            if isinstance(v, dict):
                for alias in v.get("aliases") or []:
                    add_alias(str(alias), cid, vid)

    for c in characters or []:
        for vid, variant in c.variants.items():
            for alias in variant.aliases:
                add_alias(alias, c.id, vid)

    return mapping
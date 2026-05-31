"""Per-novel character/location refs + Milvus vector retrieval."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from app.core.config_loader import load_config
from app.core.paths import (
    character_ref_path,
    location_ref_path,
    novel_characters_registry_path,
    novel_locations_registry_path,
)
from app.core.schemas import Character, Location, Scene
from app.services import vector_store

logger = logging.getLogger(__name__)


def _similarity_threshold() -> float:
    return float(load_config("milvus").get("similarity_threshold", 0.72))


def load_character_registry(novel_name: str) -> dict[str, dict]:
    path = novel_characters_registry_path(novel_name)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid characters registry: %s", path)
    return {}


def load_location_registry(novel_name: str) -> dict[str, dict]:
    path = novel_locations_registry_path(novel_name)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid locations registry: %s", path)
    return {}


def _index_character(novel_name: str, char: Character) -> None:
    vector_store.upsert_entity(
        novel_name,
        "character",
        char.id,
        char.name,
        char.appearance,
        char.ref_image,
    )


def _index_location(novel_name: str, loc: Location) -> None:
    vector_store.upsert_entity(
        novel_name,
        "location",
        loc.id,
        loc.name,
        loc.description,
        loc.ref_image,
    )


def save_registry(
    novel_name: str,
    characters: list[Character],
    locations: list[Location] | None = None,
) -> None:
    char_path = novel_characters_registry_path(novel_name)
    char_path.parent.mkdir(parents=True, exist_ok=True)
    registry = load_character_registry(novel_name)
    for c in characters:
        entry = c.model_dump()
        ref = character_ref_path(novel_name, c.id)
        if ref.is_file():
            entry["ref_image"] = str(ref)
        registry[c.id] = entry
        _index_character(novel_name, Character(**entry))
    char_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if locations is not None:
        loc_path = novel_locations_registry_path(novel_name)
        loc_registry = load_location_registry(novel_name)
        for loc in locations:
            entry = loc.model_dump()
            ref = location_ref_path(novel_name, loc.id)
            if ref.is_file():
                entry["ref_image"] = str(ref)
            loc_registry[loc.id] = entry
            _index_location(novel_name, Location(**entry))
        loc_path.write_text(
            json.dumps(loc_registry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _enrich_from_vector(
    novel_name: str,
    entity_type: str,
    name: str,
    description: str,
    ref_image: str | None,
) -> tuple[str, str | None]:
    hits = vector_store.search_entities(
        novel_name,
        f"{name} {description}",
        entity_type,
        top_k=1,
    )
    if not hits:
        return description, ref_image
    hit = hits[0]
    if hit.get("score", 0) < _similarity_threshold():
        return description, ref_image
    desc = hit.get("description") or description
    if len(desc) > len(description):
        description = desc
    ref = hit.get("ref_image") or ref_image
    if ref and Path(ref).is_file():
        ref_image = ref
    return description, ref_image


def merge_with_novel_registry(novel_name: str, characters: list[Character]) -> list[Character]:
    """Reuse saved appearance + ref_image; vector search fills canonical profiles."""
    registry = load_character_registry(novel_name)
    merged: list[Character] = []
    for c in characters:
        old = registry.get(c.id)
        ref = character_ref_path(novel_name, c.id)
        ref_str = str(ref) if ref.is_file() else c.ref_image
        appearance = c.appearance
        if old and old.get("appearance"):
            if len(old["appearance"]) >= len(appearance):
                appearance = old["appearance"]
        appearance, ref_str = _enrich_from_vector(
            novel_name, "character", c.name, appearance, ref_str
        )
        merged.append(
            c.model_copy(
                update={
                    "appearance": appearance,
                    "ref_image": ref_str or (old.get("ref_image") if old else ref_str),
                }
            )
        )
    return merged


def merge_locations(novel_name: str, locations: list[Location]) -> list[Location]:
    registry = load_location_registry(novel_name)
    merged: list[Location] = []
    for loc in locations:
        old = registry.get(loc.id)
        desc = loc.description
        if old and old.get("description") and len(old["description"]) >= len(desc):
            desc = old["description"]
        desc, ref_str = _enrich_from_vector(
            novel_name, "location", loc.name, desc, loc.ref_image
        )
        merged.append(loc.model_copy(update={"description": desc, "ref_image": ref_str}))
    return merged


def sync_ref_paths(characters: list[Character], novel_name: str) -> None:
    for c in characters:
        ref = character_ref_path(novel_name, c.id)
        if ref.is_file():
            c.ref_image = str(ref)


def portrait_scene(character: Character) -> Scene:
    return Scene(
        id=f"ref_{character.id}",
        narration="",
        visual_prompt=(
            f"character design sheet, portrait, front view, full face visible, "
            f"{character.appearance}, neutral background, same outfit for all scenes"
        ),
        character_ids=[character.id],
        shot_type="close-up",
    )


def build_scene_visual_prompt(
    scene: Scene,
    char_map: dict[str, Character],
    loc_map: dict[str, Location] | None = None,
    *,
    with_ref: bool = False,
) -> str:
    cfg = load_config("image")
    base = scene.visual_prompt.strip()
    parts: list[str] = []
    for cid in scene.character_ids:
        ch = char_map.get(cid)
        if ch and ch.appearance:
            parts.append(f"{ch.name}: {ch.appearance}")
    if parts:
        base = f"{base}. Characters in scene: {'; '.join(parts)}"

    if loc_map and scene.location_id:
        loc = loc_map.get(scene.location_id)
        if loc and loc.description:
            base = f"{base}. Location ({loc.name}): {loc.description}"

    if with_ref and scene.character_ids:
        tpl = cfg.get(
            "ref_scene_prompt_suffix",
            "Keep the same face, hairstyle, and clothing as the reference character image.",
        )
        base = f"{base}. {tpl}"
    return base


def pick_scene_ref_image(
    scene: Scene,
    char_map: dict[str, Character],
    novel_name: str,
) -> Path | None:
    for cid in scene.character_ids:
        ch = char_map.get(cid)
        if ch and ch.ref_image:
            p = Path(ch.ref_image)
            if p.is_file():
                return p
        p = character_ref_path(novel_name, cid)
        if p.is_file():
            return p
    return None


def image_to_data_uri(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > 10 * 1024 * 1024:
        raise ValueError(f"Reference image too large: {path}")
    mime = "image/png"
    if path.suffix.lower() in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif path.suffix.lower() == ".webp":
        mime = "image/webp"
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"

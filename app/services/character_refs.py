"""Per-novel character/location refs + Milvus vector retrieval."""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path

from app.core.config_loader import load_config
from app.core.paths import (
    character_ref_path,
    character_variant_ref_path,
    location_ref_path,
    novel_characters_registry_path,
    novel_locations_registry_path,
    resolve_storage_path,
    storage_path_is_file,
    to_storage_path,
)
from app.core.schemas import Character, CharacterVariant, Location, Scene
from app.services import novel_meta, vector_store

logger = logging.getLogger(__name__)

_CHAR_ID = re.compile(r"^char_(\d+)$")
DEFAULT_VARIANT_ID = "default"


def _similarity_threshold() -> float:
    return float(load_config("milvus").get("similarity_threshold", 0.72))


def load_character_registry(novel_name: str) -> dict[str, dict]:
    path = novel_characters_registry_path(novel_name)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: migrate_registry_entry(novel_name, k, v) for k, v in data.items()}
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


def _normalize_ref_value(
    ref_value: str | None,
    *,
    canonical: Path | None = None,
) -> str | None:
    if canonical is not None and canonical.is_file():
        return to_storage_path(canonical)
    if not ref_value:
        return None
    if storage_path_is_file(ref_value):
        return to_storage_path(resolve_storage_path(ref_value))
    return to_storage_path(ref_value)


def migrate_registry_entry(novel_name: str, char_id: str, entry: dict) -> dict:
    """Ensure legacy flat entries have variants.default."""
    if entry.get("variants"):
        entry = dict(entry)
        for vid, v in list(entry["variants"].items()):
            if isinstance(v, dict):
                v = dict(v)
                ref = character_variant_ref_path(novel_name, char_id, vid)
                v["ref_image"] = _normalize_ref_value(v.get("ref_image"), canonical=ref)
                entry["variants"][vid] = v
        entry["ref_image"] = _normalize_ref_value(
            entry.get("ref_image"),
            canonical=character_variant_ref_path(
                novel_name,
                char_id,
                entry.get("default_variant_id") or DEFAULT_VARIANT_ID,
            ),
        )
        return entry
    vid = entry.get("default_variant_id") or DEFAULT_VARIANT_ID
    entry = dict(entry)
    entry["default_variant_id"] = vid
    canonical = character_variant_ref_path(novel_name, char_id, vid)
    entry["variants"] = {
        vid: {
            "variant_id": vid,
            "label": entry.pop("variant_label", None),
            "appearance": entry.get("appearance") or "",
            "age_group": entry.get("age_group"),
            "ref_image": _normalize_ref_value(entry.get("ref_image"), canonical=canonical),
            "aliases": [],
        }
    }
    entry["ref_image"] = entry["variants"][vid]["ref_image"]
    return entry


def ensure_character_variants(char: Character) -> Character:
    if char.variants:
        return sync_character_top_level(char)
    vid = char.default_variant_id or DEFAULT_VARIANT_ID
    variant = CharacterVariant(
        variant_id=vid,
        appearance=char.appearance,
        age_group=char.age_group,
        ref_image=char.ref_image,
    )
    return char.model_copy(
        update={
            "default_variant_id": vid,
            "variants": {vid: variant},
        }
    )


def sync_character_top_level(char: Character) -> Character:
    char = ensure_character_variants(char) if not char.variants else char
    default_id = char.default_variant_id or DEFAULT_VARIANT_ID
    variant = char.variants.get(default_id)
    if not variant:
        return char
    return char.model_copy(
        update={
            "appearance": variant.appearance,
            "ref_image": variant.ref_image,
            "age_group": variant.age_group or char.age_group,
        }
    )


def get_variant(char: Character, variant_id: str | None) -> CharacterVariant:
    char = ensure_character_variants(char)
    vid = variant_id or char.default_variant_id or DEFAULT_VARIANT_ID
    if vid in char.variants:
        return char.variants[vid]
    default = char.variants.get(char.default_variant_id or DEFAULT_VARIANT_ID)
    if default:
        return default
    return CharacterVariant(variant_id=vid, appearance=char.appearance, age_group=char.age_group)


def scene_variant_id(scene: Scene, char_id: str, char: Character | None = None) -> str:
    vid = scene.character_variants.get(char_id)
    if vid:
        return vid
    if char:
        return char.default_variant_id or DEFAULT_VARIANT_ID
    return DEFAULT_VARIANT_ID


def iter_character_variants(char: Character) -> list[tuple[str, CharacterVariant]]:
    char = ensure_character_variants(char)
    return list(char.variants.items())


def _index_character(novel_name: str, char: Character) -> None:
    char = ensure_character_variants(char)
    for vid, variant in char.variants.items():
        entity_id = f"{char.id}::{vid}" if vid != DEFAULT_VARIANT_ID else char.id
        label = f"{char.name} ({variant.label or vid})" if vid != DEFAULT_VARIANT_ID else char.name
        vector_store.upsert_entity(
            novel_name,
            "character",
            entity_id,
            label,
            variant.appearance,
            variant.ref_image,
            variant_id=vid,
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


def _max_char_num(*sources: dict | list) -> int:
    nums: list[int] = []
    for src in sources:
        if isinstance(src, dict):
            keys = src.keys()
        else:
            keys = (getattr(x, "id", "") for x in src)
        for key in keys:
            m = _CHAR_ID.match(str(key))
            if m:
                nums.append(int(m.group(1)))
    return max(nums) if nums else 0


def _parse_entity_id(entity_id: str) -> tuple[str, str]:
    if "::" in entity_id:
        cid, vid = entity_id.split("::", 1)
        return cid, vid
    return entity_id, DEFAULT_VARIANT_ID


def _lookup_canonical_id(novel_name: str, name: str, name_map: dict[str, str]) -> str | None:
    name = name.strip()
    if not name:
        return None
    if name in name_map:
        return name_map[name]
    hits = vector_store.search_entities(novel_name, name, "character", top_k=3)
    good = [h for h in hits if h.get("score", 0) >= _similarity_threshold()]
    if len(good) == 1:
        return _parse_entity_id(str(good[0].get("entity_id") or ""))[0]
    return None


def _prune_junk_registry_entries(registry: dict[str, dict]) -> None:
    name_to_id: dict[str, str] = {}
    for cid, entry in registry.items():
        name = (entry.get("name") or "").strip()
        if name:
            name_to_id[name] = cid

    to_remove: list[str] = []
    for cid, entry in registry.items():
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        parts = novel_meta.parse_character_names(name)
        if len(parts) <= 1:
            continue
        if all(p in name_to_id and name_to_id[p] != cid for p in parts):
            to_remove.append(cid)

    for cid in to_remove:
        logger.info("Removing junk registry entry %s (%s)", cid, registry[cid].get("name"))
        del registry[cid]


def _lock_variant_appearance(
    llm_appearance: str,
    old_variant: dict | None,
    *,
    has_ref: bool,
) -> str:
    stored = ((old_variant or {}).get("appearance") or "").strip()
    if stored and (has_ref or stored):
        return stored
    return llm_appearance or stored


def _lock_trait(field: str, llm_value: str | None, old: dict, meta_entry: dict) -> str | None:
    stored = old.get(field) or meta_entry.get(field)
    if stored:
        return stored
    return llm_value


def _merge_variant_dicts(
    novel_name: str,
    char_id: str,
    base: dict[str, CharacterVariant],
    incoming: dict[str, CharacterVariant],
    registry_variants: dict[str, dict],
) -> dict[str, CharacterVariant]:
    merged = dict(base)
    for vid, variant in incoming.items():
        old_v = registry_variants.get(vid, {})
        ref_path = character_variant_ref_path(novel_name, char_id, vid)
        has_ref = ref_path.is_file()
        ref_str = to_storage_path(ref_path) if has_ref else _normalize_ref_value(
            old_v.get("ref_image") or variant.ref_image,
            canonical=ref_path if has_ref else None,
        )
        appearance = _lock_variant_appearance(variant.appearance, old_v, has_ref=has_ref)
        merged[vid] = CharacterVariant(
            variant_id=vid,
            label=variant.label or old_v.get("label"),
            appearance=appearance,
            age_group=variant.age_group or old_v.get("age_group"),
            ref_image=ref_str,
            aliases=list(
                dict.fromkeys((variant.aliases or []) + (old_v.get("aliases") or []))
            ),
        )
    return merged


def merge_variants_from_script(
    novel_name: str,
    characters: list[Character],
    scenes: list[Scene],
) -> list[Character]:
    """Merge LLM/scene variant selections into character registry entries."""
    registry = load_character_registry(novel_name)
    char_map = {c.id: ensure_character_variants(c) for c in characters}
    updated: list[Character] = []

    scene_variants: dict[str, dict[str, str]] = {}
    for scene in scenes:
        for cid in set(scene.character_ids) | set(scene.focus_character_ids):
            vid = scene.character_variants.get(cid)
            if vid:
                scene_variants.setdefault(cid, {})[vid] = vid

    for c in characters:
        reg = registry.get(c.id, {})
        reg_variants = reg.get("variants") or {}
        merged_variants = dict(c.variants)
        default_id = c.default_variant_id or reg.get("default_variant_id") or DEFAULT_VARIANT_ID

        for vid in scene_variants.get(c.id, {}):
            if vid not in merged_variants:
                merged_variants[vid] = CharacterVariant(
                    variant_id=vid,
                    appearance=c.appearance,
                    age_group=c.age_group,
                )

        merged_variants = _merge_variant_dicts(
            novel_name,
            c.id,
            ensure_character_variants(c).variants,
            merged_variants,
            reg_variants,
        )

        old = reg
        meta_entry = novel_meta.load_novel_meta(novel_name).get("characters", {}).get(c.id, {})
        default_variant = merged_variants.get(default_id) or next(iter(merged_variants.values()))

        updated.append(
            c.model_copy(
                update={
                    "default_variant_id": default_id,
                    "variants": merged_variants,
                    "appearance": default_variant.appearance,
                    "ref_image": default_variant.ref_image,
                    "age_group": default_variant.age_group or c.age_group,
                    "role": c.role or old.get("role") or meta_entry.get("role"),
                    "gender": _lock_trait("gender", c.gender, old, meta_entry),
                    "aliases": list(
                        dict.fromkeys(
                            (c.aliases or [])
                            + (old.get("aliases") or [])
                            + (meta_entry.get("aliases") or [])
                        )
                    ),
                }
            )
        )
    return updated


def resolve_canonical_characters(
    novel_name: str,
    characters: list[Character],
) -> list[Character]:
    """Align LLM characters to registry by name; avoid id/name collisions across episodes."""
    registry = load_character_registry(novel_name)
    name_map = novel_meta.build_name_to_id_map(novel_name)
    next_num = _max_char_num(registry, characters)
    resolved: list[Character] = []

    for c in characters:
        c = ensure_character_variants(c)
        canonical_id = _lookup_canonical_id(novel_name, c.name, name_map)
        if not canonical_id:
            for alias in c.aliases:
                canonical_id = _lookup_canonical_id(novel_name, alias, name_map)
                if canonical_id:
                    break

        if canonical_id:
            cid = canonical_id
        elif c.id in registry and registry[c.id].get("name") == c.name:
            cid = c.id
        elif c.id in registry and registry[c.id].get("name") != c.name:
            next_num += 1
            cid = f"char_{next_num}"
            logger.warning(
                "Character id conflict: %s reused for %s; assigned %s (registry has %s)",
                c.id,
                c.name,
                cid,
                registry[c.id].get("name"),
            )
        else:
            cid = c.id
            if cid in registry and registry[cid].get("name") not in (None, "", c.name):
                next_num += 1
                cid = f"char_{next_num}"
                logger.warning(
                    "Character id %s occupied; assigned %s to %s",
                    c.id,
                    cid,
                    c.name,
                )

        old = registry.get(cid, {})
        reg_variants = old.get("variants") or {}
        default_id = c.default_variant_id or old.get("default_variant_id") or DEFAULT_VARIANT_ID
        merged_variants = _merge_variant_dicts(
            novel_name,
            cid,
            c.variants or {default_id: CharacterVariant(variant_id=default_id, appearance=c.appearance)},
            c.variants,
            reg_variants,
        )
        if default_id not in merged_variants:
            merged_variants[default_id] = CharacterVariant(
                variant_id=default_id,
                appearance=c.appearance,
                age_group=c.age_group,
            )
        default_variant = merged_variants[default_id]

        meta_chars = novel_meta.load_novel_meta(novel_name).get("characters") or {}
        meta_entry = meta_chars.get(cid, {})

        resolved.append(
            c.model_copy(
                update={
                    "id": cid,
                    "default_variant_id": default_id,
                    "variants": merged_variants,
                    "appearance": default_variant.appearance,
                    "ref_image": default_variant.ref_image,
                    "role": c.role or old.get("role") or meta_entry.get("role"),
                    "gender": _lock_trait("gender", c.gender, old, meta_entry),
                    "age_group": default_variant.age_group
                    or _lock_trait("age_group", c.age_group, old, meta_entry),
                    "aliases": list(
                        dict.fromkeys(
                            (c.aliases or [])
                            + (old.get("aliases") or [])
                            + (meta_entry.get("aliases") or [])
                        )
                    ),
                }
            )
        )

    return resolved


def save_registry(
    novel_name: str,
    characters: list[Character],
    locations: list[Location] | None = None,
) -> None:
    char_path = novel_characters_registry_path(novel_name)
    char_path.parent.mkdir(parents=True, exist_ok=True)
    registry = load_character_registry(novel_name)
    for c in characters:
        c = sync_character_top_level(ensure_character_variants(c))
        for vid in list(c.variants.keys()):
            ref = character_variant_ref_path(novel_name, c.id, vid)
            if ref.is_file():
                c.variants[vid] = c.variants[vid].model_copy(
                    update={"ref_image": to_storage_path(ref)}
                )
        entry = sync_character_top_level(c).model_dump()
        default_ref = character_variant_ref_path(
            novel_name, c.id, c.default_variant_id or DEFAULT_VARIANT_ID
        )
        if default_ref.is_file():
            entry["ref_image"] = to_storage_path(default_ref)
        for vid, v in list((entry.get("variants") or {}).items()):
            if isinstance(v, dict):
                ref = character_variant_ref_path(novel_name, c.id, vid)
                v = dict(v)
                v["ref_image"] = _normalize_ref_value(v.get("ref_image"), canonical=ref)
                entry["variants"][vid] = v
        registry[c.id] = entry
    _prune_junk_registry_entries(registry)
    for cid, entry in registry.items():
        _index_character(novel_name, Character(**entry))
    char_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    novel_meta.update_from_characters(novel_name, [Character(**registry[k]) for k in registry])

    if locations is not None:
        loc_path = novel_locations_registry_path(novel_name)
        loc_registry = load_location_registry(novel_name)
        for loc in locations:
            entry = loc.model_dump()
            ref = location_ref_path(novel_name, loc.id)
            if ref.is_file():
                entry["ref_image"] = to_storage_path(ref)
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
    *,
    variant_id: str = DEFAULT_VARIANT_ID,
) -> tuple[str, str | None]:
    entity_id = f"{name}::{variant_id}" if variant_id != DEFAULT_VARIANT_ID else name
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
    if ref and storage_path_is_file(ref):
        ref_image = to_storage_path(resolve_storage_path(ref))
    return description, ref_image


def merge_with_novel_registry(novel_name: str, characters: list[Character]) -> list[Character]:
    """Reuse saved appearance + ref_image per variant."""
    registry = load_character_registry(novel_name)
    meta_chars = novel_meta.load_novel_meta(novel_name).get("characters") or {}
    merged: list[Character] = []
    for c in characters:
        c = ensure_character_variants(c)
        old = registry.get(c.id, {})
        meta_entry = meta_chars.get(c.id, {})
        reg_variants = old.get("variants") or {}
        default_id = c.default_variant_id or old.get("default_variant_id") or DEFAULT_VARIANT_ID

        new_variants: dict[str, CharacterVariant] = {}
        for vid, variant in c.variants.items():
            old_v = reg_variants.get(vid, {})
            ref_path = character_variant_ref_path(novel_name, c.id, vid)
            has_ref = ref_path.is_file()
            ref_str = to_storage_path(ref_path) if has_ref else _normalize_ref_value(
                variant.ref_image, canonical=ref_path if has_ref else None
            )
            appearance = _lock_variant_appearance(variant.appearance, old_v, has_ref=has_ref)
            if not old_v.get("appearance"):
                appearance, ref_str = _enrich_from_vector(
                    novel_name,
                    "character",
                    c.name,
                    appearance,
                    ref_str,
                    variant_id=vid,
                )
            new_variants[vid] = variant.model_copy(
                update={"appearance": appearance, "ref_image": ref_str or variant.ref_image}
            )

        default_variant = new_variants.get(default_id) or next(iter(new_variants.values()), None)
        merged.append(
            c.model_copy(
                update={
                    "variants": new_variants,
                    "appearance": default_variant.appearance if default_variant else c.appearance,
                    "ref_image": default_variant.ref_image if default_variant else c.ref_image,
                    "gender": _lock_trait("gender", c.gender, old, meta_entry),
                    "age_group": (
                        default_variant.age_group if default_variant else c.age_group
                    )
                    or _lock_trait("age_group", c.age_group, old, meta_entry),
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
    for i, c in enumerate(characters):
        c = ensure_character_variants(c)
        for vid, variant in c.variants.items():
            ref = character_variant_ref_path(novel_name, c.id, vid)
            if ref.is_file():
                c.variants[vid] = variant.model_copy(update={"ref_image": to_storage_path(ref)})
        characters[i] = sync_character_top_level(c)


def portrait_scene(
    character: Character,
    *,
    variant_id: str | None = None,
) -> Scene:
    variant = get_variant(character, variant_id)
    vid = variant.variant_id
    return Scene(
        id=f"ref_{character.id}_{vid}",
        narration="",
        visual_prompt=(
            f"character design sheet, portrait, front view, full face visible, "
            f"{variant.appearance}, neutral background, same outfit for all scenes"
        ),
        character_ids=[character.id],
        character_variants={character.id: vid},
        shot_type="close-up",
    )


def is_environment_scene(scene: Scene) -> bool:
    if scene.scene_type == "environment":
        return True
    return not scene.character_ids and scene.scene_type != "crowd"


def build_environment_prompt(
    scene: Scene,
    loc_map: dict[str, Location] | None = None,
) -> str:
    cfg = load_config("image")
    base = scene.visual_prompt.strip()
    if loc_map and scene.location_id:
        loc = loc_map.get(scene.location_id)
        if loc and loc.description:
            base = f"{base}. Location ({loc.name}): {loc.description}"
    suffix = cfg.get(
        "environment_prompt_suffix",
        "establishing shot, empty scene, no people, atmospheric depth",
    )
    return f"{base}. {suffix}"


def build_scene_visual_prompt(
    scene: Scene,
    char_map: dict[str, Character],
    loc_map: dict[str, Location] | None = None,
    *,
    with_ref: bool = False,
    graph_hints: str | None = None,
) -> str:
    cfg = load_config("image")
    base = scene.visual_prompt.strip()
    char_ids = scene.focus_character_ids or scene.character_ids
    parts: list[str] = []
    for cid in char_ids:
        ch = char_map.get(cid)
        if not ch:
            continue
        variant = get_variant(ch, scene_variant_id(scene, cid, ch))
        if variant.appearance:
            age_hint = f", age: {variant.age_group}" if variant.age_group else ""
            parts.append(f"{ch.name}: {variant.appearance}{age_hint}")
    if parts:
        base = f"{base}. Characters in scene: {'; '.join(parts)}"

    if loc_map and scene.location_id:
        loc = loc_map.get(scene.location_id)
        if loc and loc.description:
            base = f"{base}. Location ({loc.name}): {loc.description}"

    if graph_hints:
        base = f"{base}. {graph_hints}"

    if with_ref and char_ids:
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
    preferred: list[str] = []
    preferred.extend(scene.focus_character_ids)
    if scene.narration_speaker_id:
        preferred.append(scene.narration_speaker_id)
    preferred.extend(scene.character_ids)
    seen: set[str] = set()
    for cid in preferred:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        ch = char_map.get(cid)
        vid = scene_variant_id(scene, cid, ch)
        if ch:
            variant = get_variant(ch, vid)
            if variant.ref_image:
                p = resolve_storage_path(variant.ref_image)
                if p and p.is_file():
                    return p
        p = character_variant_ref_path(novel_name, cid, vid)
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

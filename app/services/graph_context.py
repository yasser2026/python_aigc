"""Read-only knowledge graph context for LLM prompts and pipeline stages."""

from __future__ import annotations

from app.core.config_loader import load_config
from app.core.schemas import Scene
from app.services import knowledge_graph, novel_meta


def _max_relations() -> int:
    return int(load_config("neo4j").get("max_relations_in_prompt", 5))


def _max_events() -> int:
    return int(load_config("neo4j").get("max_events_in_prompt", 3))


def get_character_relations(
    novel_name: str,
    char_ids: list[str],
    *,
    top_k: int | None = None,
) -> list[dict]:
    limit = top_k or _max_relations()
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for cid in char_ids:
        for rel in knowledge_graph.get_character_relations_json(novel_name, cid):
            key = (cid, rel.get("other_id", ""), rel.get("type", ""))
            if key in seen:
                continue
            seen.add(key)
            rel["source_id"] = cid
            out.append(rel)
            if len(out) >= limit:
                return out
    return out


def get_location_history(novel_name: str, location_id: str | None) -> list[dict]:
    if not location_id:
        return []
    data = knowledge_graph.load_json_graph(novel_name)
    history: list[dict] = []
    for scene in data.get("scenes", []):
        if scene.get("location_id") != location_id:
            continue
        history.append(
            {
                "episode": scene.get("episode"),
                "scene_id": scene.get("scene_id"),
                "narration": (scene.get("narration") or "")[:80],
                "scene_type": scene.get("scene_type"),
            }
        )
    return history[-5:]


def get_episode_continuity(novel_name: str, episode: int) -> dict:
    data = knowledge_graph.load_json_graph(novel_name)
    prev_key = str(episode - 1) if episode > 1 else None
    prev_summary = None
    if prev_key and prev_key in data.get("episodes", {}):
        prev_summary = data["episodes"][prev_key].get("summary")

    events = [
        e
        for e in data.get("plot_events", [])
        if int(e.get("episode", 0)) < episode
    ]
    events.sort(key=lambda e: (e.get("episode", 0), e.get("order_in_episode", 0)))
    recent_events = events[-_max_events() :]

    return {
        "previous_summary": prev_summary,
        "recent_plot_events": recent_events,
    }


def get_kg_appearance_summary(novel_name: str, char_id: str) -> str | None:
    data = knowledge_graph.load_json_graph(novel_name)
    entry = data.get("characters", {}).get(char_id, {})
    summary = entry.get("appearance_summary") or entry.get("appearance")
    return str(summary).strip() if summary else None


def format_for_llm_prompt(
    novel_name: str,
    episode: int,
    *,
    focus_char_ids: list[str] | None = None,
    supporting_names: list[str] | None = None,
) -> str:
    """Compress graph context to ~500-800 chars for LLM user prompt."""
    pipeline = load_config("pipeline")
    kg_cfg = pipeline.get("knowledge_graph") or {}
    if not kg_cfg.get("enabled", True) or kg_cfg.get("inject_in_prompt") is False:
        return ""

    lines: list[str] = []
    continuity = get_episode_continuity(novel_name, episode)
    if continuity.get("previous_summary"):
        lines.append(f"上一集剧情摘要：{continuity['previous_summary']}")

    for evt in continuity.get("recent_plot_events", []):
        lines.append(f"前情事件：{evt.get('summary', '')}")

    protagonist_ids = novel_meta.get_protagonist_ids(novel_name)
    name_map = novel_meta.build_name_to_id_map(novel_name)
    query_ids: list[str] = list(dict.fromkeys(list(focus_char_ids or []) + list(protagonist_ids)))
    if supporting_names:
        seen_names: set[str] = set()
        for raw in supporting_names:
            for name in novel_meta.parse_character_names(raw):
                if name in seen_names:
                    continue
                seen_names.add(name)
                cid = name_map.get(name)
                if cid and cid not in query_ids:
                    query_ids.append(cid)

    data = knowledge_graph.load_json_graph(novel_name)
    kg_chars = data.get("characters", {})
    profile_lines: list[str] = []
    for cid in query_ids:
        kg_entry = kg_chars.get(cid, {})
        name = kg_entry.get("name") or cid
        variants = kg_entry.get("variants") or {}
        if variants:
            for vid, summary in variants.items():
                if summary:
                    profile_lines.append(f"{name}（{vid}）：{summary}")
        else:
            summary = kg_entry.get("appearance_summary") or kg_entry.get("appearance")
            if summary:
                profile_lines.append(f"{name}：{summary}")
    if profile_lines:
        lines.append("前集人物刻画：" + "；".join(profile_lines))

    relations = get_character_relations(novel_name, query_ids)
    if relations:
        rel_lines = []
        chars = kg_chars
        for rel in relations[: _max_relations()]:
            src = chars.get(rel.get("source_id", ""), {}).get("name", rel.get("source_id"))
            tgt = rel.get("other_name") or rel.get("other_id")
            note = rel.get("note") or rel.get("type", "")
            rel_lines.append(f"{src} 与 {tgt}：{note}")
        lines.append("已知人物关系：" + "；".join(rel_lines))

    text = "\n".join(lines)
    return text[:800]


def get_scene_graph_hints(novel_name: str, scene: Scene) -> str:
    """Relationship + location hints for image prompt."""
    parts: list[str] = []
    char_ids = list(
        dict.fromkeys(list(scene.focus_character_ids) + list(scene.character_ids))
    )
    if len(char_ids) >= 2:
        relations = get_character_relations(novel_name, char_ids, top_k=3)
        for rel in relations:
            note = rel.get("note") or rel.get("type", "related")
            other = rel.get("other_name") or rel.get("other_id")
            parts.append(f"relationship with {other}: {note}")

    if scene.location_id:
        history = get_location_history(novel_name, scene.location_id)
        if history:
            parts.append(f"recurring location, seen in {len(history)} prior scenes")

    cfg = load_config("image")
    suffix = cfg.get("relationship_prompt_suffix", "Relationship context:")
    if parts:
        return f"{suffix} {'; '.join(parts)}"
    return ""


def infer_speaker_from_graph(
    novel_name: str,
    scene: Scene,
    name_map: dict[str, str],
) -> str | None:
    """Guess speaker when regex fails, using focus ids and co-occurrence."""
    if scene.narration_speaker_id:
        return scene.narration_speaker_id

    focus = scene.focus_character_ids or []
    if len(focus) == 1:
        return focus[0]

    for name, cid in name_map.items():
        if name in scene.narration and cid in scene.character_ids:
            return cid

    if len(scene.character_ids) == 1:
        return scene.character_ids[0]

    return None


def is_location_first_appearance(novel_name: str, location_id: str | None) -> bool:
    if not location_id:
        return False
    history = get_location_history(novel_name, location_id)
    return len(history) == 0


def validate_scene_speaker(scene: Scene) -> Scene:
    """Clear speaker if not among characters in scene."""
    sid = scene.narration_speaker_id
    if not sid:
        return scene
    if sid not in scene.character_ids and sid not in scene.focus_character_ids:
        return scene.model_copy(
            update={"narration_speaker_id": None, "narration_type": "narrator"}
        )
    return scene


def get_speaker_display_name(
    novel_name: str,
    char_id: str,
    char_map: dict | None = None,
) -> str:
    if char_map and char_id in char_map:
        return char_map[char_id].name
    name = knowledge_graph.get_character_name(novel_name, char_id)
    return name or char_id


def get_relation_tts_rate(
    novel_name: str,
    scene: Scene,
) -> str | None:
    """Optional rate tweak by relationship type for dialogue scenes."""
    if scene.narration_type != "dialogue" or not scene.narration_speaker_id:
        return None
    listener_ids = [
        cid
        for cid in scene.character_ids
        if cid != scene.narration_speaker_id
    ]
    if not listener_ids:
        return None
    relations = get_character_relations(
        novel_name, [scene.narration_speaker_id], top_k=5
    )
    types = {r.get("type") for r in relations if r.get("other_id") in listener_ids}
    if "enemy" in types:
        return "+8%"
    if "family" in types:
        return "-5%"
    return None

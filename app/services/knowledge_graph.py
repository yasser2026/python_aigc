"""Neo4j knowledge graph with JSON fallback for novel characters, scenes, plot."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.core.config_loader import load_config
from app.core.paths import (
    build_novel_dir,
    build_work_dir,
    novel_knowledge_graph_path,
    sanitize_novel_dir,
)
from app.core.schemas import (
    Character,
    CharacterRelation,
    EpisodeAnalysis,
    GraphDelta,
    Location,
    Scene,
    SceneScript,
)
from app.services import character_refs

logger = logging.getLogger(__name__)

_DRIVER = None
_DRIVER_OK: bool | None = None


def _cfg() -> dict:
    return load_config("neo4j")


def is_config_enabled() -> bool:
    """Neo4j enabled in config/neo4j.json (ignores pipeline switch)."""
    return bool(_cfg().get("enabled", False))


def is_enabled() -> bool:
    pipeline = load_config("pipeline")
    kg = pipeline.get("knowledge_graph") or {}
    if kg.get("enabled") is False:
        return False
    return bool(_cfg().get("enabled", False))


def is_pipeline_enabled() -> bool:
    """Whether knowledge graph merge/inject is active in pipeline."""
    return bool(load_config("pipeline").get("knowledge_graph", {}).get("enabled", True))


def _fallback_enabled() -> bool:
    return bool(_cfg().get("fallback_to_json", True))


def _novel_key(novel_name: str) -> str:
    return sanitize_novel_dir(novel_name)


def _empty_graph(novel_name: str) -> dict[str, Any]:
    return {
        "novel_name": _novel_key(novel_name),
        "characters": {},
        "locations": {},
        "episodes": {},
        "scenes": [],
        "relationships": [],
        "plot_events": [],
    }


def load_json_graph(novel_name: str) -> dict[str, Any]:
    path = novel_knowledge_graph_path(novel_name)
    if not path.is_file():
        return _empty_graph(novel_name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("novel_name", _novel_key(novel_name))
            data.setdefault("characters", {})
            data.setdefault("locations", {})
            data.setdefault("episodes", {})
            data.setdefault("scenes", [])
            data.setdefault("relationships", [])
            data.setdefault("plot_events", [])
            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Invalid knowledge graph JSON %s: %s", path, e)
    return _empty_graph(novel_name)


def save_json_graph(novel_name: str, data: dict[str, Any]) -> Path:
    path = novel_knowledge_graph_path(novel_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["novel_name"] = _novel_key(novel_name)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_to_json(novel_name: str) -> Path:
    """Export current graph to JSON (from Neo4j if connected, else existing file)."""
    if _neo4j_available():
        try:
            data = _neo4j_export(novel_name)
            return save_json_graph(novel_name, data)
        except Exception as e:
            logger.warning("Neo4j export failed, keeping JSON: %s", e)
    return novel_knowledge_graph_path(novel_name)


def import_from_json(novel_name: str) -> None:
    """Load JSON graph into Neo4j when available."""
    if not _neo4j_available():
        return
    data = load_json_graph(novel_name)
    try:
        _neo4j_import_bulk(novel_name, data)
    except Exception as e:
        logger.warning("Neo4j import from JSON failed: %s", e)


def ping_server() -> bool:
    """Return True if Neo4j config enabled and server reachable."""
    global _DRIVER_OK
    if not is_config_enabled():
        _DRIVER_OK = False
        return False
    try:
        driver = _get_driver()
        driver.verify_connectivity()
        _DRIVER_OK = True
        return True
    except Exception as e:
        logger.debug("Neo4j ping failed: %s", e)
        _DRIVER_OK = False
        return False


def ping() -> bool:
    if not is_enabled():
        return False
    return ping_server()


def _get_driver():
    global _DRIVER
    if _DRIVER is not None:
        return _DRIVER
    from neo4j import GraphDatabase

    cfg = _cfg()
    uri = cfg.get("uri", "bolt://127.0.0.1:7687")
    if uri.startswith("${"):
        uri = "bolt://127.0.0.1:7687"
    user = cfg.get("user", "neo4j")
    password = cfg.get("password", "password")
    if password.startswith("${"):
        password = "password"
    _DRIVER = GraphDatabase.driver(uri, auth=(user, password))
    return _DRIVER


def _neo4j_available() -> bool:
    if not is_enabled():
        return False
    if _DRIVER_OK is False:
        return False
    return ping()


def _run_write(query: str, params: dict[str, Any]) -> None:
    cfg = _cfg()
    database = cfg.get("database", "neo4j")
    with _get_driver().session(database=database) as session:
        session.execute_write(lambda tx: tx.run(query, **params))


def _run_read(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = _cfg()
    database = cfg.get("database", "neo4j")
    with _get_driver().session(database=database) as session:
        result = session.run(query, **params)
        return [dict(record) for record in result]


def _scene_key(episode: int, scene_id: str) -> str:
    return f"ep{episode}:{scene_id}"


def _merge_json_episode(
    data: dict[str, Any],
    novel_name: str,
    episode: int,
    script: SceneScript,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    novel = _novel_key(novel_name)
    analysis = script.episode_analysis
    summary = analysis.fragment_summary if analysis else None

    for ch in script.characters:
        ch = character_refs.ensure_character_variants(ch)
        variant_summaries = {
            vid: (v.appearance or "")[:200]
            for vid, v in ch.variants.items()
        }
        data["characters"][ch.id] = {
            "id": ch.id,
            "name": ch.name,
            "role": ch.role,
            "gender": ch.gender,
            "age_group": ch.age_group,
            "appearance_summary": (ch.appearance or "")[:500],
            "variants": variant_summaries,
            "default_variant_id": ch.default_variant_id,
        }
    for loc in script.locations:
        data["locations"][loc.id] = {
            "id": loc.id,
            "name": loc.name,
            "description": loc.description,
        }

    ep_key = str(episode)
    data["episodes"][ep_key] = {
        "number": episode,
        "summary": summary,
        "project_id": project_id,
    }

    data["scenes"] = [
        s
        for s in data["scenes"]
        if not (s.get("novel_name") == novel and s.get("episode") == episode)
    ]

    for order, scene in enumerate(script.scenes, start=1):
        entry = {
            "novel_name": novel,
            "episode": episode,
            "scene_id": scene.id,
            "key": _scene_key(episode, scene.id),
            "order": order,
            "scene_type": scene.scene_type,
            "narration": scene.narration,
            "visual_prompt": scene.visual_prompt,
            "shot_type": scene.shot_type,
            "location_id": scene.location_id,
            "character_ids": list(scene.character_ids),
            "focus_character_ids": list(scene.focus_character_ids),
        }
        data["scenes"].append(entry)

        for cid in scene.character_ids:
            focus = cid in scene.focus_character_ids
            rel = {
                "source_id": cid,
                "target_id": entry["key"],
                "type": "appears_in",
                "focus": focus,
                "episode": episode,
            }
            data.setdefault("scene_links", [])
            data["scene_links"] = [
                r
                for r in data.get("scene_links", [])
                if not (
                    r.get("type") == "appears_in"
                    and r.get("source_id") == cid
                    and r.get("target_id") == entry["key"]
                )
            ]
            data["scene_links"].append(rel)

    prev = episode - 1
    if prev >= 1 and str(prev) in data["episodes"]:
        data.setdefault("episode_links", [])
        link = {"from": prev, "to": episode}
        if link not in data["episode_links"]:
            data["episode_links"].append(link)

    return data


def _merge_json_delta(
    data: dict[str, Any],
    episode: int,
    delta: GraphDelta,
) -> dict[str, Any]:
    known_chars = set(data.get("characters", {}).keys())

    for rel in delta.relationships:
        if rel.source_id not in known_chars or rel.target_id not in known_chars:
            continue
        entry = {
            "source_id": rel.source_id,
            "target_id": rel.target_id,
            "type": rel.type,
            "note": rel.note,
            "source_episode": episode,
            "confidence": rel.confidence,
            "bidirectional": rel.bidirectional,
        }
        data["relationships"] = [
            r
            for r in data["relationships"]
            if not (
                r.get("source_id") == rel.source_id
                and r.get("target_id") == rel.target_id
                and r.get("type") == rel.type
            )
        ]
        data["relationships"].append(entry)
        if rel.bidirectional:
            rev = {**entry, "source_id": rel.target_id, "target_id": rel.source_id}
            data["relationships"] = [
                r
                for r in data["relationships"]
                if not (
                    r.get("source_id") == rev["source_id"]
                    and r.get("target_id") == rev["target_id"]
                    and r.get("type") == rel.type
                )
            ]
            data["relationships"].append(rev)

    for evt in delta.plot_events:
        if evt.character_ids and not all(c in known_chars for c in evt.character_ids):
            continue
        entry = {
            "event_id": evt.event_id,
            "summary": evt.summary,
            "episode": episode,
            "order_in_episode": evt.order,
            "character_ids": list(evt.character_ids),
            "location_id": evt.location_id,
        }
        data["plot_events"] = [
            e for e in data["plot_events"] if e.get("event_id") != evt.event_id
        ]
        data["plot_events"].append(entry)

    return data


def merge_episode(
    novel_name: str,
    episode: int,
    script: SceneScript,
    *,
    project_id: str | None = None,
    meta: dict | None = None,
) -> None:
    """Upsert episode nodes/scenes into graph (Neo4j + JSON fallback)."""
    _ = meta
    if not is_pipeline_enabled():
        return
    if _neo4j_available():
        try:
            _neo4j_merge_episode(novel_name, episode, script, project_id=project_id)
        except Exception as e:
            logger.warning("Neo4j merge_episode failed: %s", e)

    if _fallback_enabled():
        data = load_json_graph(novel_name)
        data = _merge_json_episode(
            data, novel_name, episode, script, project_id=project_id
        )
        save_json_graph(novel_name, data)


def merge_graph_delta(
    novel_name: str,
    episode: int,
    delta: GraphDelta | None,
) -> None:
    if not is_pipeline_enabled():
        return
    if not delta or (not delta.relationships and not delta.plot_events):
        return

    if _neo4j_available():
        try:
            _neo4j_merge_delta(novel_name, episode, delta)
        except Exception as e:
            logger.warning("Neo4j merge_graph_delta failed: %s", e)

    if _fallback_enabled():
        data = load_json_graph(novel_name)
        data = _merge_json_delta(data, episode, delta)
        save_json_graph(novel_name, data)


def get_character_name(novel_name: str, char_id: str) -> str | None:
    data = load_json_graph(novel_name)
    ch = data.get("characters", {}).get(char_id)
    if ch:
        return ch.get("name")
    return None


def get_graph_snapshot(novel_name: str) -> dict[str, Any]:
    """Return full graph as JSON-serializable dict."""
    if _neo4j_available():
        try:
            return _neo4j_export(novel_name)
        except Exception as e:
            logger.warning("Neo4j snapshot failed: %s", e)
    return load_json_graph(novel_name)


def get_character_relations_json(
    novel_name: str,
    char_id: str,
) -> list[dict[str, Any]]:
    if _neo4j_available():
        try:
            return _neo4j_character_relations(novel_name, char_id)
        except Exception as e:
            logger.warning("Neo4j relations query failed: %s", e)

    data = load_json_graph(novel_name)
    chars = data.get("characters", {})
    out: list[dict[str, Any]] = []
    for rel in data.get("relationships", []):
        if rel.get("source_id") == char_id:
            other = rel.get("target_id")
            out.append(
                {
                    "other_id": other,
                    "other_name": chars.get(other, {}).get("name", other),
                    "type": rel.get("type"),
                    "note": rel.get("note"),
                }
            )
        elif rel.get("target_id") == char_id:
            other = rel.get("source_id")
            out.append(
                {
                    "other_id": other,
                    "other_name": chars.get(other, {}).get("name", other),
                    "type": rel.get("type"),
                    "note": rel.get("note"),
                }
            )
    return out


def _neo4j_merge_episode(
    novel_name: str,
    episode: int,
    script: SceneScript,
    *,
    project_id: str | None = None,
) -> None:
    novel = _novel_key(novel_name)
    analysis = script.episode_analysis
    summary = analysis.fragment_summary if analysis else None

    _run_write(
        """
        MERGE (e:Episode {novel_name: $novel, number: $episode})
        SET e.summary = $summary, e.project_id = $project_id
        """,
        {
            "novel": novel,
            "episode": episode,
            "summary": summary,
            "project_id": project_id,
        },
    )

    if episode > 1:
        _run_write(
            """
            MATCH (prev:Episode {novel_name: $novel, number: $prev_ep})
            MATCH (cur:Episode {novel_name: $novel, number: $episode})
            MERGE (prev)-[:NEXT_EPISODE]->(cur)
            """,
            {"novel": novel, "prev_ep": episode - 1, "episode": episode},
        )

    for ch in script.characters:
        _run_write(
            """
            MERGE (c:Character {novel_name: $novel, id: $id})
            SET c.name = $name, c.role = $role, c.gender = $gender,
                c.age_group = $age_group, c.appearance_summary = $appearance
            """,
            {
                "novel": novel,
                "id": ch.id,
                "name": ch.name,
                "role": ch.role,
                "gender": ch.gender,
                "age_group": ch.age_group,
                "appearance": (ch.appearance or "")[:500],
            },
        )

    for loc in script.locations:
        _run_write(
            """
            MERGE (l:Location {novel_name: $novel, id: $id})
            SET l.name = $name, l.description = $description
            """,
            {
                "novel": novel,
                "id": loc.id,
                "name": loc.name,
                "description": loc.description,
            },
        )

    for order, scene in enumerate(script.scenes, start=1):
        _run_write(
            """
            MERGE (s:Scene {novel_name: $novel, episode: $episode, scene_id: $scene_id})
            SET s.scene_type = $scene_type, s.narration = $narration,
                s.visual_prompt = $visual_prompt, s.shot_type = $shot_type
            WITH s
            MATCH (e:Episode {novel_name: $novel, number: $episode})
            MERGE (s)-[p:PART_OF]->(e)
            SET p.order = $order
            """,
            {
                "novel": novel,
                "episode": episode,
                "scene_id": scene.id,
                "scene_type": scene.scene_type,
                "narration": scene.narration,
                "visual_prompt": scene.visual_prompt,
                "shot_type": scene.shot_type,
                "order": order,
            },
        )

        if scene.location_id:
            _run_write(
                """
                MATCH (s:Scene {novel_name: $novel, episode: $episode, scene_id: $scene_id})
                MATCH (l:Location {novel_name: $novel, id: $loc_id})
                MERGE (s)-[:SET_IN]->(l)
                """,
                {
                    "novel": novel,
                    "episode": episode,
                    "scene_id": scene.id,
                    "loc_id": scene.location_id,
                },
            )

        for cid in scene.character_ids:
            focus = cid in scene.focus_character_ids
            _run_write(
                """
                MATCH (c:Character {novel_name: $novel, id: $cid})
                MATCH (s:Scene {novel_name: $novel, episode: $episode, scene_id: $scene_id})
                MERGE (c)-[r:APPEARS_IN]->(s)
                SET r.focus = $focus
                """,
                {
                    "novel": novel,
                    "cid": cid,
                    "episode": episode,
                    "scene_id": scene.id,
                    "focus": focus,
                },
            )


def _neo4j_merge_delta(novel_name: str, episode: int, delta: GraphDelta) -> None:
    novel = _novel_key(novel_name)
    for rel in delta.relationships:
        _run_write(
            """
            MATCH (a:Character {novel_name: $novel, id: $source_id})
            MATCH (b:Character {novel_name: $novel, id: $target_id})
            MERGE (a)-[r:RELATED_TO]->(b)
            SET r.type = $type, r.note = $note, r.source_episode = $episode,
                r.confidence = $confidence
            """,
            {
                "novel": novel,
                "source_id": rel.source_id,
                "target_id": rel.target_id,
                "type": rel.type,
                "note": rel.note,
                "episode": episode,
                "confidence": rel.confidence,
            },
        )
        if rel.bidirectional:
            _run_write(
                """
                MATCH (a:Character {novel_name: $novel, id: $source_id})
                MATCH (b:Character {novel_name: $novel, id: $target_id})
                MERGE (b)-[r:RELATED_TO]->(a)
                SET r.type = $type, r.note = $note, r.source_episode = $episode,
                    r.confidence = $confidence
                """,
                {
                    "novel": novel,
                    "source_id": rel.source_id,
                    "target_id": rel.target_id,
                    "type": rel.type,
                    "note": rel.note,
                    "episode": episode,
                    "confidence": rel.confidence,
                },
            )

    for evt in delta.plot_events:
        _run_write(
            """
            MERGE (pe:PlotEvent {novel_name: $novel, event_id: $event_id})
            SET pe.summary = $summary, pe.episode = $episode, pe.order_in_episode = $order
            WITH pe
            MATCH (e:Episode {novel_name: $novel, number: $episode})
            MERGE (pe)-[:IN_EPISODE]->(e)
            """,
            {
                "novel": novel,
                "event_id": evt.event_id,
                "summary": evt.summary,
                "episode": episode,
                "order": evt.order,
            },
        )
        for cid in evt.character_ids:
            _run_write(
                """
                MATCH (pe:PlotEvent {novel_name: $novel, event_id: $event_id})
                MATCH (c:Character {novel_name: $novel, id: $cid})
                MERGE (pe)-[:INVOLVES]->(c)
                """,
                {"novel": novel, "event_id": evt.event_id, "cid": cid},
            )
        if evt.location_id:
            _run_write(
                """
                MATCH (pe:PlotEvent {novel_name: $novel, event_id: $event_id})
                MATCH (l:Location {novel_name: $novel, id: $loc_id})
                MERGE (pe)-[:AT_LOCATION]->(l)
                """,
                {"novel": novel, "event_id": evt.event_id, "loc_id": evt.location_id},
            )


def _neo4j_character_relations(novel_name: str, char_id: str) -> list[dict[str, Any]]:
    novel = _novel_key(novel_name)
    rows = _run_read(
        """
        MATCH (c:Character {novel_name: $novel, id: $cid})-[r:RELATED_TO]-(other:Character)
        RETURN other.id AS other_id, other.name AS other_name, r.type AS type, r.note AS note
        LIMIT 20
        """,
        {"novel": novel, "cid": char_id},
    )
    return rows


def _neo4j_export(novel_name: str) -> dict[str, Any]:
    novel = _novel_key(novel_name)
    data = _empty_graph(novel_name)

    chars = _run_read(
        "MATCH (c:Character {novel_name: $novel}) RETURN c",
        {"novel": novel},
    )
    for row in chars:
        node = row.get("c")
        if node:
            data["characters"][node["id"]] = dict(node)

    locs = _run_read(
        "MATCH (l:Location {novel_name: $novel}) RETURN l",
        {"novel": novel},
    )
    for row in locs:
        node = row.get("l")
        if node:
            data["locations"][node["id"]] = dict(node)

    eps = _run_read(
        "MATCH (e:Episode {novel_name: $novel}) RETURN e ORDER BY e.number",
        {"novel": novel},
    )
    for row in eps:
        node = row.get("e")
        if node:
            data["episodes"][str(node["number"])] = dict(node)

    rels = _run_read(
        """
        MATCH (a:Character {novel_name: $novel})-[r:RELATED_TO]->(b:Character)
        RETURN a.id AS source_id, b.id AS target_id, r.type AS type,
               r.note AS note, r.source_episode AS source_episode, r.confidence AS confidence
        """,
        {"novel": novel},
    )
    data["relationships"] = rels

    events = _run_read(
        """
        MATCH (pe:PlotEvent {novel_name: $novel})
        OPTIONAL MATCH (pe)-[:INVOLVES]->(c:Character)
        RETURN pe, collect(c.id) AS character_ids
        """,
        {"novel": novel},
    )
    for row in events:
        pe = row.get("pe")
        if pe:
            data["plot_events"].append(
                {
                    "event_id": pe["event_id"],
                    "summary": pe.get("summary"),
                    "episode": pe.get("episode"),
                    "order_in_episode": pe.get("order_in_episode"),
                    "character_ids": row.get("character_ids") or [],
                }
            )

    return data


def _neo4j_import_bulk(novel_name: str, data: dict[str, Any]) -> None:
    novel = _novel_key(novel_name)
    for cid, ch in data.get("characters", {}).items():
        _run_write(
            """
            MERGE (c:Character {novel_name: $novel, id: $id})
            SET c += $props
            """,
            {"novel": novel, "id": cid, "props": ch},
        )
    for lid, loc in data.get("locations", {}).items():
        _run_write(
            """
            MERGE (l:Location {novel_name: $novel, id: $id})
            SET l += $props
            """,
            {"novel": novel, "id": lid, "props": loc},
        )
    for ep_key, ep in data.get("episodes", {}).items():
        _run_write(
            """
            MERGE (e:Episode {novel_name: $novel, number: $number})
            SET e.summary = $summary, e.project_id = $project_id
            """,
            {
                "novel": novel,
                "number": int(ep.get("number", ep_key)),
                "summary": ep.get("summary"),
                "project_id": ep.get("project_id"),
            },
        )
    for rel in data.get("relationships", []):
        if rel.get("type") == "appears_in":
            continue
        delta = GraphDelta(
            relationships=[
                CharacterRelation(
                    source_id=rel["source_id"],
                    target_id=rel["target_id"],
                    type=rel.get("type", "other"),
                    note=rel.get("note"),
                    bidirectional=rel.get("bidirectional", False),
                    confidence=rel.get("confidence", 1.0),
                )
            ]
        )
        _neo4j_merge_delta(novel_name, rel.get("source_episode", 1), delta)


def backfill_novel(novel_name: str) -> int:
    """Rebuild graph from existing episode scenes.json files. Returns episode count."""
    novel_dir = build_novel_dir(novel_name)
    if not novel_dir.is_dir():
        return 0

    count = 0
    ep_pattern = re.compile(r"^第(\d+)集$")
    for child in sorted(novel_dir.iterdir()):
        if not child.is_dir():
            continue
        m = ep_pattern.match(child.name)
        if not m:
            continue
        episode = int(m.group(1))
        scenes_path = child / "scenes.json"
        if not scenes_path.is_file():
            continue
        try:
            from app.services.llm_scene import load_scene_script

            script = load_scene_script(child)
            meta_path = child / "meta.json"
            project_id = None
            if meta_path.is_file():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                project_id = meta.get("project_id")
            merge_episode(
                novel_name, episode, script, project_id=project_id
            )
            if script.graph_delta:
                merge_graph_delta(novel_name, episode, script.graph_delta)
            count += 1
        except Exception as e:
            logger.warning("Backfill skip %s: %s", child, e)

    export_to_json(novel_name)
    return count

"""Post-process scene scripts: name alignment, speaker inference, protagonist balance."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx

from app.core.config_loader import load_config
from app.core.schemas import (
    Character,
    CharacterVariant,
    EpisodeAnalysis,
    NarrativeMode,
    Scene,
    SceneScript,
)
from app.services import character_refs, graph_context, novel_meta

logger = logging.getLogger(__name__)

_SPEAKER_RE = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z·]{1,12})(?P<verb>说|道|喊|叫|低声|惊呼|吼道|答道|问道|回应)"
)
_HERO_KEYWORDS = re.compile(
    r"\b(hero|worship|symbol|admiration|idol|legend|like a hero)\b",
    re.IGNORECASE,
)
_ENV_HINTS = re.compile(
    r"(wide shot|establishing|landscape|panorama|aerial|empty|sunrise|sunset|"
    r"mist|mountain|town|sky|horizon|空镜|远景|全景|小镇|山脉|清晨|夕阳)",
    re.IGNORECASE,
)
_ENV_IN_API_KEY = re.compile(r"\$\{([^}]+)\}")


def _char_by_id(characters: list[Character]) -> dict[str, Character]:
    return {c.id: c for c in characters}


def _mentioned_ids(text: str, name_map: dict[str, str]) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for name, cid in sorted(name_map.items(), key=lambda x: -len(x[0])):
        if len(name) < 2:
            continue
        if name in text and cid not in seen:
            found.append(cid)
            seen.add(cid)
    return found


def _english_name_hints(characters: list[Character]) -> dict[str, str]:
    hints: dict[str, str] = {}
    for c in characters:
        if c.name.isascii():
            hints[c.name.lower()] = c.id
        parts = c.appearance.split()
        for token in parts[:3]:
            if token.isalpha() and len(token) > 2:
                hints[token.lower()] = c.id
    return hints


def _mention_counts(source_text: str, name_map: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, cid in name_map.items():
        if len(name) < 2:
            continue
        n = source_text.count(name)
        if n:
            counts[cid] = counts.get(cid, 0) + n
    return counts


def apply_episode_analysis(
    script: SceneScript,
    novel_name: str,
    work_dir: Path | None = None,
) -> SceneScript:
    analysis = script.episode_analysis
    locked_ids = novel_meta.get_protagonist_ids(novel_name)
    locked = novel_meta.is_protagonist_locked(novel_name)
    primary_pid = locked_ids[0] if locked_ids else None

    if locked and locked_ids:
        if analysis:
            analysis = analysis.model_copy(update={"book_protagonist_id": primary_pid})
            script = script.model_copy(update={"episode_analysis": analysis})
        script = script.model_copy(
            update={
                "characters": novel_meta.enforce_locked_protagonist_on_characters(
                    novel_name, script.characters
                )
            }
        )
    elif analysis:
        novel_meta.apply_protagonist_from_analysis(
            novel_name, analysis.book_protagonist_id
        )

    analysis = script.episode_analysis
    if not analysis:
        return script

    book_pid = primary_pid if locked and primary_pid else analysis.book_protagonist_id
    locked_set = set(locked_ids) if locked else set()

    role_from_notes = analysis.role_notes or {}
    updated_chars: list[Character] = []
    for c in script.characters:
        role = c.role
        if locked_set and c.id in locked_set:
            role = "protagonist"
        elif book_pid and c.id == book_pid:
            role = "protagonist"
        elif c.id in analysis.fragment_focus_ids and role != "protagonist":
            role = role or "supporting"
        note = role_from_notes.get(c.id, "")
        if not locked and "主角" in note and "背景" not in note:
            role = "protagonist"
        elif locked and role == "protagonist" and locked_set and c.id not in locked_set:
            role = "supporting"
        updated_chars.append(c.model_copy(update={"role": role}))

    script = script.model_copy(update={"characters": updated_chars})
    novel_meta.update_from_characters(
        novel_name,
        script.characters,
        protagonist_id=book_pid or novel_meta.get_protagonist_id(novel_name),
    )

    if work_dir and analysis:
        from app.services.llm_scene import save_episode_analysis

        save_episode_analysis(work_dir, analysis)

    return script


def fill_character_ids(
    script: SceneScript,
    novel_name: str,
    source_text: str,
) -> SceneScript:
    name_map = novel_meta.build_name_to_id_map(novel_name, script.characters)
    english_hints = _english_name_hints(script.characters)
    updated: list[Scene] = []

    for scene in script.scenes:
        if scene.scene_type == "environment":
            updated.append(
                scene.model_copy(
                    update={"character_ids": [], "focus_character_ids": []}
                )
            )
            continue

        ids = list(scene.character_ids)
        blob = f"{scene.narration} {scene.visual_prompt}"
        for cid in _mentioned_ids(blob, name_map):
            if cid not in ids:
                ids.append(cid)
        vp = scene.visual_prompt.lower()
        for hint, cid in english_hints.items():
            if hint in vp and cid not in ids:
                ids.append(cid)
        updated.append(scene.model_copy(update={"character_ids": ids}))

    counts = _mention_counts(source_text, name_map)
    analysis = script.episode_analysis
    if analysis and analysis.fragment_focus_ids and counts:
        focus_set = set(analysis.fragment_focus_ids)
        mentioned_in_text = [cid for cid in focus_set if counts.get(cid, 0) > 0]
        if not mentioned_in_text:
            logger.warning(
                "fragment_focus_ids %s have zero mentions in source text",
                analysis.fragment_focus_ids,
            )

    return script.model_copy(update={"scenes": updated})


def classify_and_fix_scenes(
    script: SceneScript,
    novel_name: str,
) -> SceneScript:
    name_map = novel_meta.build_name_to_id_map(novel_name, script.characters)
    fragment_focus = (
        list(script.episode_analysis.fragment_focus_ids)
        if script.episode_analysis
        else []
    )
    updated: list[Scene] = []

    for idx, scene in enumerate(script.scenes):
        scene_type = scene.scene_type
        ids = list(scene.character_ids)
        focus = list(scene.focus_character_ids)
        blob = f"{scene.narration} {scene.visual_prompt}"
        mentioned = _mentioned_ids(blob, name_map)

        if scene_type == "environment":
            updated.append(
                scene.model_copy(
                    update={
                        "character_ids": [],
                        "focus_character_ids": [],
                        "scene_type": "environment",
                    }
                )
            )
            continue

        if not scene_type:
            if (
                idx == 0
                and scene.location_id
                and graph_context.is_location_first_appearance(
                    novel_name, scene.location_id
                )
                and not mentioned
            ):
                scene_type = "environment"
                updated.append(
                    scene.model_copy(
                        update={
                            "scene_type": "environment",
                            "character_ids": [],
                            "focus_character_ids": [],
                        }
                    )
                )
                continue
            if not mentioned and (
                _ENV_HINTS.search(scene.visual_prompt)
                or _ENV_HINTS.search(scene.narration)
            ):
                scene_type = "environment"
                updated.append(
                    scene.model_copy(
                        update={
                            "scene_type": "environment",
                            "character_ids": [],
                            "focus_character_ids": [],
                        }
                    )
                )
                continue
            scene_type = "crowd" if not mentioned and not ids else "character"

        if scene_type == "environment":
            updated.append(
                scene.model_copy(
                    update={
                        "character_ids": [],
                        "focus_character_ids": [],
                        "scene_type": "environment",
                    }
                )
            )
            continue

        if not focus and ids:
            overlap = [cid for cid in fragment_focus if cid in ids]
            if overlap:
                focus = overlap
            elif mentioned:
                focus = [mentioned[0]]
            else:
                focus = [ids[0]]

        if scene_type == "character" and not focus and mentioned:
            focus = [mentioned[0]]
            if mentioned[0] not in ids:
                ids.append(mentioned[0])

        updated.append(
            scene.model_copy(
                update={
                    "scene_type": scene_type,
                    "character_ids": ids,
                    "focus_character_ids": focus,
                }
            )
        )

    return script.model_copy(update={"scenes": updated})


def infer_narration_speakers(script: SceneScript, novel_name: str) -> SceneScript:
    name_map = novel_meta.build_name_to_id_map(novel_name, script.characters)
    updated: list[Scene] = []

    for scene in script.scenes:
        if scene.scene_type == "environment":
            updated.append(
                scene.model_copy(
                    update={
                        "narration_speaker_id": None,
                        "narration_type": "narrator",
                    }
                )
            )
            continue

        speaker_id = scene.narration_speaker_id
        narration_type = scene.narration_type

        m = _SPEAKER_RE.search(scene.narration)
        if m:
            raw_name = m.group("name").strip()
            cid = name_map.get(raw_name)
            if cid:
                speaker_id = cid
                narration_type = "dialogue"
            elif raw_name.endswith("少年") or raw_name.endswith("孩子"):
                narration_type = "mixed"

        if not speaker_id:
            inferred = graph_context.infer_speaker_from_graph(
                novel_name, scene, name_map
            )
            if inferred:
                speaker_id = inferred
                narration_type = "dialogue"

        if not narration_type:
            narration_type = "dialogue" if speaker_id else "narrator"

        fixed = graph_context.validate_scene_speaker(
            scene.model_copy(
                update={
                    "narration_speaker_id": speaker_id,
                    "narration_type": narration_type,
                }
            )
        )
        updated.append(fixed)

    return script.model_copy(update={"scenes": updated})


def _protagonist_shot_ratio(
    scenes: list[Scene],
    protagonist_ids: list[str],
) -> float:
    if not protagonist_ids or not scenes:
        return 1.0
    eligible = [s for s in scenes if s.scene_type != "environment"]
    if not eligible:
        return 1.0
    pid_set = set(protagonist_ids)
    count = sum(
        1 for s in eligible if pid_set.intersection(s.character_ids)
    )
    return count / len(eligible)


def _supporting_hero_scenes(
    scenes: list[Scene],
    char_map: dict[str, Character],
    protagonist_ids: list[str],
) -> list[str]:
    bad: list[str] = []
    pid_set = set(protagonist_ids)
    for scene in scenes:
        if scene.scene_type == "environment":
            continue
        if not _HERO_KEYWORDS.search(scene.visual_prompt):
            continue
        for cid in scene.character_ids:
            ch = char_map.get(cid)
            if not ch or cid in pid_set:
                continue
            if ch.role in ("supporting", "minor") or ch.role is None:
                bad.append(scene.id)
                break
    return bad


def _api_key(cfg: dict) -> str:
    api_key = cfg.get("api_key", "")
    if api_key and not api_key.startswith("${"):
        return api_key
    env_name = "DASHSCOPE_API_KEY"
    m = _ENV_IN_API_KEY.search(str(cfg.get("api_key", "")))
    if m:
        env_name = m.group(1)
    import os

    return os.environ.get(env_name, "")


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


async def _refine_protagonist_focus(
    script: SceneScript,
    novel_name: str,
    source_text: str,
    protagonist_ids: list[str],
) -> SceneScript:
    cfg = load_config("llm")
    if cfg.get("mock", False):
        return script

    api_key = _api_key(cfg)
    if not api_key:
        logger.warning("Skipping protagonist refine: no API key")
        return script

    char_map = _char_by_id(script.characters)
    labels = []
    for pid in protagonist_ids:
        ch = char_map.get(pid)
        if ch:
            labels.append(f"{ch.name} ({pid})")
    if not labels:
        return script

    payload = {
        "characters": [c.model_dump() for c in script.characters],
        "scenes": [s.model_dump() for s in script.scenes],
    }
    user_content = (
        f"小说：《{novel_name}》\n"
        f"主角：{'、'.join(labels)}\n"
        f"原文片段：\n---\n{source_text[:2000]}\n---\n\n"
        f"当前分镜 JSON：\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        "请修正 scenes：所有主角合计至少出现在 40% 非 environment 场景的 character_ids 中；"
        "environment 镜保持 scene_type=environment 且 character_ids 为空；"
        "配角 visual_prompt 不得 hero/worship/symbol 式英雄化；"
        "保留 scene_type、focus_character_ids 字段。"
        "只输出 {\"scenes\": [...]} JSON。"
    )

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                _chat_url(cfg["base_url"]),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": cfg.get("model", "qwen-plus-2025-07-28"),
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是分镜编辑。只输出合法 JSON，字段与输入 scenes 一致。",
                        },
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.4,
                    "max_tokens": cfg.get("max_tokens", 4096),
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(raw)
            new_scenes = [Scene(**s) for s in data.get("scenes", [])]
            if len(new_scenes) == len(script.scenes):
                return script.model_copy(update={"scenes": new_scenes})
    except Exception as e:
        logger.warning("Protagonist focus refine failed: %s", e)

    return script


def _flatten_supporting_names(supporting_names: list[str]) -> list[str]:
    """Split legacy combined strings (e.g. 希尔曼、罗瑞、罗杰) into individual names."""
    flat: list[str] = []
    seen: set[str] = set()
    for raw in supporting_names:
        for name in novel_meta.parse_character_names(raw):
            if name not in seen:
                seen.add(name)
                flat.append(name)
    return flat


def apply_episode_supporting_names(
    script: SceneScript,
    novel_name: str,
    supporting_names: list[str],
) -> SceneScript:
    """Mark user-specified per-episode supporting cast and merge into episode_analysis."""
    if not supporting_names:
        return script

    supporting_names = _flatten_supporting_names(supporting_names)
    if not supporting_names:
        return script

    protagonist_ids = set(novel_meta.get_protagonist_ids(novel_name))
    name_map = novel_meta.build_name_to_id_map(novel_name, script.characters)
    registry = character_refs.load_character_registry(novel_name)
    chars_by_id = {c.id: c for c in script.characters}
    supporting_ids: list[str] = []

    nums: list[int] = []
    for cid in list(registry.keys()) + list(chars_by_id.keys()):
        m = re.match(r"^char_(\d+)$", cid)
        if m:
            nums.append(int(m.group(1)))
    next_num = max(nums, default=0)

    updated_chars = list(script.characters)

    for name in supporting_names:
        cid = name_map.get(name)
        if not cid:
            next_num += 1
            cid = f"char_{next_num}"
            updated_chars.append(
                Character(
                    id=cid,
                    name=name,
                    role="supporting",
                    appearance=f"{name}，本集配角",
                )
            )
            name_map[name] = cid
        elif cid not in chars_by_id:
            reg_entry = registry.get(cid, {})
            updated_chars.append(
                Character(
                    id=cid,
                    name=name,
                    role="supporting",
                    appearance=reg_entry.get("appearance") or f"{name}，本集配角",
                    gender=reg_entry.get("gender"),
                    age_group=reg_entry.get("age_group"),
                    ref_image=reg_entry.get("ref_image"),
                )
            )

        if cid in protagonist_ids:
            continue
        if cid not in supporting_ids:
            supporting_ids.append(cid)

    role_updated: list[Character] = []
    supporting_set = set(supporting_ids)
    supporting_name_set = set(supporting_names)
    for c in updated_chars:
        if c.id in protagonist_ids:
            role_updated.append(c)
        elif c.id in supporting_set or c.name in supporting_name_set:
            role_updated.append(c.model_copy(update={"role": "supporting"}))
        else:
            role_updated.append(c)

    analysis = script.episode_analysis
    role_notes = dict(analysis.role_notes) if analysis else {}
    for name in supporting_names:
        cid = name_map.get(name)
        if cid and cid not in protagonist_ids:
            role_notes.setdefault(cid, f"本集指定配角：{name}")

    focus = list(analysis.fragment_focus_ids) if analysis else []
    for sid in supporting_ids:
        if sid not in focus:
            focus.append(sid)

    if analysis:
        analysis = analysis.model_copy(
            update={
                "fragment_focus_ids": focus,
                "role_notes": role_notes,
                "episode_supporting_names": list(supporting_names),
            }
        )
    else:
        analysis = EpisodeAnalysis(
            fragment_focus_ids=supporting_ids,
            role_notes=role_notes,
            episode_supporting_names=list(supporting_names),
        )

    return script.model_copy(
        update={"characters": role_updated, "episode_analysis": analysis}
    )


def resolve_character_variants(script: SceneScript, novel_name: str) -> SceneScript:
    """Fill scene.character_variants; infer variant from variant-level aliases."""
    from app.services.character_refs import DEFAULT_VARIANT_ID, ensure_character_variants

    variant_alias_map = novel_meta.build_variant_alias_map(novel_name, script.characters)
    char_map = _char_by_id(script.characters)
    updated_scenes: list[Scene] = []

    for scene in script.scenes:
        variants = dict(scene.character_variants)
        char_ids = list(
            dict.fromkeys(list(scene.character_ids) + list(scene.focus_character_ids))
        )
        text = f"{scene.narration} {scene.visual_prompt}"
        for cid in char_ids:
            if cid in variants:
                continue
            ch = char_map.get(cid)
            default_vid = (
                ch.default_variant_id if ch else DEFAULT_VARIANT_ID
            ) or DEFAULT_VARIANT_ID
            inferred: str | None = None
            for alias, (aid, vid) in variant_alias_map.items():
                if aid == cid and alias in text:
                    inferred = vid
                    break
            variants[cid] = inferred or default_vid

        updated_scenes.append(scene.model_copy(update={"character_variants": variants}))

    updated_chars: list[Character] = []
    used_variants: dict[str, set[str]] = {}
    for scene in updated_scenes:
        for cid, vid in scene.character_variants.items():
            used_variants.setdefault(cid, set()).add(vid)

    for c in script.characters:
        c = ensure_character_variants(c)
        merged = dict(c.variants)
        for vid in used_variants.get(c.id, set()):
            if vid not in merged:
                merged[vid] = CharacterVariant(
                    variant_id=vid,
                    appearance=c.appearance,
                    age_group=c.age_group,
                )
        updated_chars.append(c.model_copy(update={"variants": merged}))

    return script.model_copy(update={"scenes": updated_scenes, "characters": updated_chars})


async def normalize_script(
    script: SceneScript,
    novel_name: str,
    source_text: str,
    narrative_mode: NarrativeMode,
    work_dir: Path | None = None,
    supporting_names: list[str] | None = None,
) -> SceneScript:
    script = apply_episode_supporting_names(script, novel_name, supporting_names or [])
    script = apply_episode_analysis(script, novel_name, work_dir)
    script = classify_and_fix_scenes(script, novel_name)
    script = fill_character_ids(script, novel_name, source_text)
    script = classify_and_fix_scenes(script, novel_name)
    script = infer_narration_speakers(script, novel_name)

    protagonist_ids = novel_meta.get_protagonist_ids(novel_name)
    if not protagonist_ids:
        for c in script.characters:
            if c.role == "protagonist" and c.id not in protagonist_ids:
                protagonist_ids.append(c.id)
    if not protagonist_ids and script.episode_analysis:
        bp = script.episode_analysis.book_protagonist_id
        if bp:
            protagonist_ids = [bp]

    char_map = _char_by_id(script.characters)
    ratio = _protagonist_shot_ratio(script.scenes, protagonist_ids)
    hero_issues = _supporting_hero_scenes(script.scenes, char_map, protagonist_ids)

    if narrative_mode == "protagonist_focus" and protagonist_ids:
        if ratio < 0.4 or hero_issues:
            logger.info(
                "Protagonist focus refine: ratio=%.2f hero_scenes=%s",
                ratio,
                hero_issues,
            )
            script = await _refine_protagonist_focus(
                script, novel_name, source_text, protagonist_ids
            )
            script = classify_and_fix_scenes(script, novel_name)
            script = fill_character_ids(script, novel_name, source_text)
            script = classify_and_fix_scenes(script, novel_name)
            script = infer_narration_speakers(script, novel_name)
    elif hero_issues:
        softened: list[Scene] = []
        for scene in script.scenes:
            if scene.id in hero_issues:
                vp = _HERO_KEYWORDS.sub("respectful", scene.visual_prompt)
                softened.append(scene.model_copy(update={"visual_prompt": vp}))
            else:
                softened.append(scene)
        script = script.model_copy(update={"scenes": softened})

    script = resolve_character_variants(script, novel_name)
    script = script.model_copy(
        update={
            "characters": character_refs.merge_variants_from_script(
                novel_name, script.characters, script.scenes
            )
        }
    )
    return script

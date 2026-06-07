"""Qwen (DashScope) LLM scene splitting."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from app.core.config_loader import load_config
from app.core.debug_log import agent_log
from app.core.paths import character_variant_ref_path
from app.core.schemas import (
    Character,
    EpisodeAnalysis,
    GraphDelta,
    Location,
    NarrativeMode,
    Scene,
    SceneScript,
)
from app.services import character_refs, graph_context, knowledge_graph, novel_meta

_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
_ENV_IN_API_KEY = re.compile(r"\$\{([^}]+)\}")


def _extract_json(text: str) -> dict:
    text = text.strip()
    m = _JSON_BLOCK.search(text)
    if m:
        text = m.group(1).strip()
    # Find outermost { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _mock_script(text: str) -> SceneScript:
    """Deterministic script for dev without API key."""
    return SceneScript(
        characters=[
            Character(
                id="char_1",
                name="少年",
                appearance="young man, black hair, simple robe, anime style",
                role="protagonist",
            )
        ],
        locations=[
            Location(
                id="loc_1",
                name="旧屋",
                description="old wooden house interior, dim candlelight, dusty room",
            )
        ],
        scenes=[
            Scene(
                id="scene_1",
                narration="夜色如墨，小镇在暮霭中静静沉睡。",
                visual_prompt="wide shot of small town at night, moonlight, mist, empty streets",
                character_ids=[],
                focus_character_ids=[],
                location_id="loc_1",
                shot_type="wide",
                scene_type="environment",
            ),
            Scene(
                id="scene_2",
                narration="少年推门而入，烛光摇曳。",
                visual_prompt="young man opening wooden door, candlelight",
                character_ids=["char_1"],
                focus_character_ids=["char_1"],
                location_id="loc_1",
                shot_type="medium",
                scene_type="character",
            ),
            Scene(
                id="scene_3",
                narration="他低声道：我来了。",
                visual_prompt="close-up face, speaking, dim room, anime portrait",
                character_ids=["char_1"],
                focus_character_ids=["char_1"],
                shot_type="close-up",
                scene_type="character",
            ),
        ],
        episode_analysis=EpisodeAnalysis(
            book_protagonist_id="char_1",
            fragment_focus_ids=["char_1"],
            fragment_summary="少年夜入旧屋",
            role_notes={"char_1": "本段唯一焦点"},
        ),
    )


def _api_key_env_name(cfg: dict) -> str:
    raw = cfg.get("api_key", "")
    m = _ENV_IN_API_KEY.search(str(raw))
    return m.group(1) if m else "DASHSCOPE_API_KEY"


def _chat_completions_url(base_url: str) -> str:
    """Build OpenAI-compatible chat URL without duplicating /v1."""
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _build_user_content(
    text: str,
    novel_name: str,
    max_scenes: int,
    narrative_mode: NarrativeMode,
    supporting_names: list[str] | None = None,
    episode: int | None = None,
) -> str:
    registry = character_refs.load_character_registry(novel_name)
    protagonist_ids = novel_meta.get_protagonist_ids(novel_name)
    lines = [
        f"小说名称：《{novel_name}》",
        f"叙事模式：{narrative_mode}",
        f"请将以下小说片段拆分为不超过 {max_scenes} 个场景的分镜脚本。",
    ]
    if protagonist_ids:
        labels = []
        for pid in protagonist_ids:
            entry = registry.get(pid, {})
            pname = entry.get("name", pid)
            labels.append(f"{pname} ({pid})")
        lines.append(f"本书主角：{'、'.join(labels)}")
    if novel_meta.is_protagonist_locked(novel_name):
        locked_names = novel_meta.get_protagonist_name(novel_name) or ""
        lines.append(
            f"主角已由用户锁定为「{locked_names}」，book_protagonist_id 取第一位主角 id，"
            "所有锁定主角 role 必须为 protagonist，不得将其他角色标为主角。"
        )
    if registry:
        registered = []
        for cid, entry in sorted(registry.items()):
            entry = character_refs.migrate_registry_entry(novel_name, cid, entry)
            variants_out = []
            for vid, v in (entry.get("variants") or {}).items():
                if not isinstance(v, dict):
                    continue
                ref = character_variant_ref_path(novel_name, cid, vid)
                variants_out.append(
                    {
                        "variant_id": vid,
                        "label": v.get("label"),
                        "appearance": v.get("appearance") or "",
                        "age_group": v.get("age_group"),
                        "aliases": v.get("aliases") or [],
                        "has_ref": ref.is_file(),
                    }
                )
            registered.append(
                {
                    "id": cid,
                    "name": entry.get("name"),
                    "role": entry.get("role"),
                    "gender": entry.get("gender"),
                    "default_variant_id": entry.get("default_variant_id") or "default",
                    "aliases": entry.get("aliases") or [],
                    "variants": variants_out,
                }
            )
        lines.append(f"已登记角色（必须复用 id）：{json.dumps(registered, ensure_ascii=False)}")
        lines.append(
            "造型变体规则：同一角色可有多个 variants（如 default/teen/disguise_xxx）。"
            "已登记 variant 的 appearance/age_group 必须原样复制，不得覆盖其他 variant；"
            "剧情需要新造型（长大、变身、假名伪装）时可新增 variant_id 与 appearance。"
            "每个非 environment 场景须填写 character_variants（char_id -> variant_id），"
            "假名出场时使用对应 variant 的 aliases 或新建 disguise_* variant。"
        )
    if supporting_names:
        labels = "、".join(supporting_names)
        lines.append(
            f"本集指定配角：{labels}。"
            "须识别并写入 characters（role=supporting），纳入 fragment_focus_ids；"
            "不得标为 protagonist。"
        )
    if episode is not None:
        graph_ctx = graph_context.format_for_llm_prompt(
            novel_name,
            episode,
            supporting_names=supporting_names,
        )
        if graph_ctx:
            lines.append(f"知识图谱上下文（跨集剧情与人物关系）：\n{graph_ctx}")
    lines.append(
        "请输出 episode_analysis、characters（含 variants 字典）、locations、"
        "每个 scene 的 scene_type、focus_character_ids、character_variants（char_id->variant_id）。"
    )
    if narrative_mode == "protagonist_focus" and protagonist_ids:
        names = novel_meta.get_protagonist_names(novel_name)
        label = "、".join(names) if names else protagonist_ids[0]
        lines.append(
            f"主角视角要求：以 {label} 为叙事中心，"
            "所有主角合计至少出现在 40% 场景的 character_ids 中。"
        )
    lines.extend(["", "---", text, "---"])
    return "\n".join(lines)


def _validate_graph_delta(
    novel_name: str,
    delta: GraphDelta | None,
    script_char_ids: set[str],
) -> GraphDelta | None:
    if not delta:
        return None
    registry = character_refs.load_character_registry(novel_name)
    known = set(registry.keys()) | script_char_ids

    valid_rels = [
        r
        for r in delta.relationships
        if r.source_id in known and r.target_id in known and r.source_id != r.target_id
    ]
    valid_events = [
        e
        for e in delta.plot_events
        if not e.character_ids or all(c in known for c in e.character_ids)
    ]
    if not valid_rels and not valid_events:
        return None
    return GraphDelta(relationships=valid_rels, plot_events=valid_events)


async def parse_novel_to_scenes(
    text: str,
    novel_name: str,
    *,
    max_scenes: int | None = None,
    narrative_mode: NarrativeMode | None = None,
    supporting_names: list[str] | None = None,
    episode: int | None = None,
) -> SceneScript:
    cfg = load_config("llm")
    pipeline = load_config("pipeline")
    max_scenes = max_scenes or pipeline.get("max_scenes_per_chapter", 12)
    mode: NarrativeMode = narrative_mode or novel_meta.default_narrative_mode()

    if cfg.get("mock", False):
        return _mock_script(text)

    api_key = cfg.get("api_key", "")
    if not api_key or api_key.startswith("${"):
        env_name = _api_key_env_name(cfg)
        raise ValueError(f"{env_name} not set. Copy .env.example to .env")

    user_content = _build_user_content(
        text,
        novel_name,
        max_scenes,
        mode,
        supporting_names=supporting_names,
        episode=episode,
    )

    retries = pipeline.get("retry", {}).get("llm", 2)
    last_err: Exception | None = None

    chat_url = _chat_completions_url(cfg["base_url"])
    # #region agent log
    agent_log(
        "llm_scene.py:parse_novel_to_scenes",
        "LLM request URL",
        {"chat_url": chat_url, "model": cfg.get("model")},
        hypothesis_id="A",
    )
    # #endregion

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(retries + 1):
            try:
                resp = await client.post(
                    chat_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": cfg.get("model", "qwen-plus-2025-07-28"),
                        "messages": [
                            {"role": "system", "content": cfg.get("system_prompt", "")},
                            {"role": "user", "content": user_content},
                        ],
                        "temperature": cfg.get("temperature", 0.7),
                        "max_tokens": cfg.get("max_tokens", 4096),
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                raw = _extract_json(content)
                analysis_raw = raw.get("episode_analysis")
                episode_analysis = (
                    EpisodeAnalysis(**analysis_raw) if analysis_raw else None
                )
                characters = [Character(**c) for c in raw.get("characters", [])]
                char_ids = {c.id for c in characters}
                graph_raw = raw.get("graph_delta")
                graph_delta = None
                if graph_raw:
                    graph_delta = _validate_graph_delta(
                        novel_name,
                        GraphDelta(**graph_raw),
                        char_ids,
                    )
                return SceneScript(
                    characters=characters,
                    locations=[Location(**l) for l in raw.get("locations", [])],
                    scenes=[Scene(**s) for s in raw.get("scenes", [])],
                    episode_analysis=episode_analysis,
                    graph_delta=graph_delta,
                )
            except (json.JSONDecodeError, KeyError, httpx.HTTPError, ValueError) as e:
                last_err = e
                if attempt >= retries:
                    break
    raise RuntimeError(f"LLM scene parse failed after retries: {last_err}") from last_err


def save_scene_script(work_dir: Path, script: SceneScript) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / "scenes.json"
    path.write_text(
        script.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def load_scene_script(work_dir: Path) -> SceneScript:
    path = work_dir / "scenes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    analysis_raw = data.get("episode_analysis")
    graph_raw = data.get("graph_delta")
    return SceneScript(
        characters=[Character(**c) for c in data.get("characters", [])],
        locations=[Location(**l) for l in data.get("locations", [])],
        scenes=[Scene(**s) for s in data.get("scenes", [])],
        episode_analysis=EpisodeAnalysis(**analysis_raw) if analysis_raw else None,
        graph_delta=GraphDelta(**graph_raw) if graph_raw else None,
    )


def save_episode_analysis(work_dir: Path, analysis: EpisodeAnalysis | None) -> Path | None:
    if not analysis:
        return None
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / "episode_analysis.json"
    path.write_text(
        analysis.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path

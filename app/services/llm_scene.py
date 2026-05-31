"""DeepSeek LLM scene splitting."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from app.core.config_loader import load_config
from app.core.schemas import Character, Scene, SceneScript

_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


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
            )
        ],
        scenes=[
            Scene(
                id="scene_1",
                narration="夜色如墨，少年推门而入。",
                visual_prompt="night, young man opening wooden door, candlelight, anime",
                character_ids=["char_1"],
                shot_type="medium",
            ),
            Scene(
                id="scene_2",
                narration="烛光摇曳，墙上映出一道修长的人影。",
                visual_prompt="candle flame, long shadow on wall, dramatic lighting, anime",
                character_ids=["char_1"],
                shot_type="wide",
            ),
            Scene(
                id="scene_3",
                narration="他低声道：我来了。",
                visual_prompt="close-up face, speaking, dim room, anime portrait",
                character_ids=["char_1"],
                shot_type="close-up",
            ),
        ],
    )


async def parse_novel_to_scenes(text: str, *, max_scenes: int | None = None) -> SceneScript:
    cfg = load_config("llm")
    pipeline = load_config("pipeline")
    max_scenes = max_scenes or pipeline.get("max_scenes_per_chapter", 12)

    if cfg.get("mock", False):
        return _mock_script(text)

    api_key = cfg.get("api_key", "")
    if not api_key or api_key.startswith("${"):
        raise ValueError("DEEPSEEK_API_KEY not set. Copy .env.example to .env")

    user_content = (
        f"请将以下小说片段拆分为不超过 {max_scenes} 个场景的分镜脚本。\n\n"
        f"---\n{text}\n---"
    )

    retries = pipeline.get("retry", {}).get("llm", 2)
    last_err: Exception | None = None

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(retries + 1):
            try:
                resp = await client.post(
                    f"{cfg['base_url'].rstrip('/')}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": cfg.get("model", "deepseek-chat"),
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
                return SceneScript(
                    characters=[Character(**c) for c in raw.get("characters", [])],
                    scenes=[Scene(**s) for s in raw.get("scenes", [])],
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
    return SceneScript(
        characters=[Character(**c) for c in data.get("characters", [])],
        scenes=[Scene(**s) for s in data.get("scenes", [])],
    )

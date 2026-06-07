"""Generate ASS subtitles aligned to scene timings."""

from __future__ import annotations

from pathlib import Path

from app.core.config_loader import load_config
from app.core.schemas import Character, Scene
from app.services import graph_context

_PUNCT = "，。！？；、："


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def _subtitle_cfg() -> dict:
    return load_config("ffmpeg").get("subtitle", {})


def split_narration_chunks(text: str, max_chars: int) -> list[str]:
    """Split narration into sequential subtitle chunks, each <= max_chars."""
    text = text.strip()
    if not text:
        return []
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_chars:
            chunks.append(rest)
            break

        segment = rest[:max_chars]
        cut = max_chars
        best = -1
        for i, ch in enumerate(segment):
            if ch in _PUNCT and i >= max(4, max_chars // 4):
                best = i + 1
        if best > 0:
            cut = best
        chunks.append(rest[:cut])
        rest = rest[cut:]

    return [c for c in chunks if c.strip()]


def format_narration_text(
    scene: Scene,
    *,
    novel_name: str | None = None,
    char_map: dict[str, Character] | None = None,
) -> str:
    text = scene.narration
    if (
        scene.narration_type == "dialogue"
        and scene.narration_speaker_id
        and novel_name
    ):
        name = graph_context.get_speaker_display_name(
            novel_name, scene.narration_speaker_id, char_map
        )
        prefix = f"{name}："
        if not text.lstrip().startswith(prefix):
            text = f"{prefix}{text}"
    return text.replace("\n", " ").strip()


def _ass_dialogue_line(start: float, end: float, text: str, style: str = "Default") -> str:
    safe = text.replace("\n", "\\N")
    return (
        f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},"
        f"{style},,0,0,0,,{safe}\n"
    )


def scene_to_ass_entries(
    scene: Scene,
    start: float,
    end: float,
    style: str = "Default",
    *,
    novel_name: str | None = None,
    char_map: dict[str, Character] | None = None,
    max_chars: int | None = None,
) -> list[str]:
    """One or more timed ASS lines; long narration is split and switched in-sequence."""
    sub = _subtitle_cfg()
    limit = max_chars if max_chars is not None else int(sub.get("max_chars_per_line", 18))
    full_text = format_narration_text(scene, novel_name=novel_name, char_map=char_map)
    chunks = split_narration_chunks(full_text, limit)
    if not chunks:
        return []

    duration = max(end - start, 0.1)
    if len(chunks) == 1:
        return [_ass_dialogue_line(start, end, chunks[0], style)]

    n = len(chunks)
    entries: list[str] = []
    for i, chunk in enumerate(chunks):
        chunk_start = start + duration * i / n
        chunk_end = end if i == n - 1 else start + duration * (i + 1) / n
        entries.append(_ass_dialogue_line(chunk_start, chunk_end, chunk, style))
    return entries


def scene_to_ass_entry(
    scene: Scene,
    start: float,
    end: float,
    style: str = "Default",
    *,
    novel_name: str | None = None,
    char_map: dict[str, Character] | None = None,
) -> str:
    entries = scene_to_ass_entries(
        scene,
        start,
        end,
        style,
        novel_name=novel_name,
        char_map=char_map,
    )
    return entries[0] if entries else ""


def _ass_header(title: str) -> str:
    cfg = load_config("ffmpeg")
    sub = _subtitle_cfg()
    bold = -1 if sub.get("bold", True) else 0
    return f"""[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: {cfg.get('width', 1920)}
PlayResY: {cfg.get('height', 1080)}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{sub.get('font_name', 'Microsoft YaHei')},{sub.get('font_size', 52)},{sub.get('primary_color', '&H00FFFFFF')},&H000000FF,{sub.get('outline_color', '&H00000000')},&H80000000,{bold},0,0,0,100,100,0,0,1,{sub.get('outline', 3)},0,2,{sub.get('margin_l', 100)},{sub.get('margin_r', 100)},{sub.get('margin_v', 60)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_scene_ass(
    scene: Scene,
    duration: float,
    output_path: Path,
    *,
    novel_name: str | None = None,
    char_map: dict[str, Character] | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = _ass_header(scene.id)
    body = "".join(
        scene_to_ass_entries(
            scene,
            0.0,
            duration,
            novel_name=novel_name,
            char_map=char_map,
        )
    )
    output_path.write_text(header + body, encoding="utf-8-sig")
    return output_path


def build_full_ass(
    scenes: list[Scene],
    durations: list[float],
    output_path: Path,
    *,
    novel_name: str | None = None,
    char_map: dict[str, Character] | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = _ass_header("full")
    t = 0.0
    events: list[str] = []
    for scene, dur in zip(scenes, durations):
        events.extend(
            scene_to_ass_entries(
                scene,
                t,
                t + dur,
                novel_name=novel_name,
                char_map=char_map,
            )
        )
        t += dur

    output_path.write_text(header + "".join(events), encoding="utf-8-sig")
    return output_path

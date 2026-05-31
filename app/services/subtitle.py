"""Generate ASS subtitles aligned to scene timings."""

from __future__ import annotations

from pathlib import Path

from app.core.config_loader import load_config
from app.core.schemas import Scene


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def scene_to_ass_entry(scene: Scene, start: float, end: float, style: str = "Default") -> str:
    text = scene.narration.replace("\n", "\\N")
    return (
        f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},"
        f"{style},,0,0,0,,{text}\n"
    )


def build_scene_ass(scene: Scene, duration: float, output_path: Path) -> Path:
    cfg = load_config("ffmpeg")
    sub = cfg.get("subtitle", {})
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bold = -1 if sub.get("bold", True) else 0
    header = f"""[Script Info]
Title: {scene.id}
ScriptType: v4.00+
PlayResX: {cfg.get('width', 1080)}
PlayResY: {cfg.get('height', 1920)}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{sub.get('font_name', 'Microsoft YaHei')},{sub.get('font_size', 72)},{sub.get('primary_color', '&H00FFFFFF')},&H000000FF,{sub.get('outline_color', '&H00000000')},&H80000000,{bold},0,0,0,100,100,0,0,1,{sub.get('outline', 4)},0,2,40,40,{sub.get('margin_v', 120)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    body = scene_to_ass_entry(scene, 0.0, duration)
    output_path.write_text(header + body, encoding="utf-8-sig")
    return output_path


def build_full_ass(scenes: list[Scene], durations: list[float], output_path: Path) -> Path:
    cfg = load_config("ffmpeg")
    sub = cfg.get("subtitle", {})
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bold = -1 if sub.get("bold", True) else 0
    header = f"""[Script Info]
Title: full
ScriptType: v4.00+
PlayResX: {cfg.get('width', 1080)}
PlayResY: {cfg.get('height', 1920)}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{sub.get('font_name', 'Microsoft YaHei')},{sub.get('font_size', 72)},{sub.get('primary_color', '&H00FFFFFF')},&H000000FF,{sub.get('outline_color', '&H00000000')},&H80000000,{bold},0,0,0,100,100,0,0,1,{sub.get('outline', 4)},0,2,40,40,{sub.get('margin_v', 120)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    t = 0.0
    events = []
    for scene, dur in zip(scenes, durations):
        events.append(scene_to_ass_entry(scene, t, t + dur))
        t += dur

    output_path.write_text(header + "".join(events), encoding="utf-8-sig")
    return output_path

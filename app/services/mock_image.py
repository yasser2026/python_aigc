"""Local mock scene images with large Chinese narration text."""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.core.config_loader import load_config
from app.core.schemas import Character, Location, Scene


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    p = Path(path)
    if p.exists():
        return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def create_mock_image(
    scene: Scene,
    characters: list[Character],
    output_path: Path,
) -> Path:
    app_cfg = load_config("app")
    ffmpeg_cfg = load_config("ffmpeg")
    mock_cfg = app_cfg.get("mock_image", {})

    w = ffmpeg_cfg.get("width", 1920)
    h = ffmpeg_cfg.get("height", 1080)
    img = Image.new("RGB", (w, h), color=(18, 28, 48))
    draw = ImageDraw.Draw(img)

    title_font = _load_font(
        mock_cfg.get("font_path", "C:/Windows/Fonts/msyh.ttc"),
        mock_cfg.get("title_font_size", 40),
    )
    body_font = _load_font(
        mock_cfg.get("font_path", "C:/Windows/Fonts/msyh.ttc"),
        mock_cfg.get("body_font_size", 56),
    )

    margin = 64
    y = margin
    draw.text((margin, y), f"【{scene.id}】", fill=(180, 200, 230), font=title_font)
    y += mock_cfg.get("title_font_size", 40) + 24

    wrap_cols = max(14, int(w / 80))
    wrapped = textwrap.fill(scene.narration, width=wrap_cols)
    for line in wrapped.split("\n"):
        draw.text((margin, y), line, fill=(255, 255, 255), font=body_font)
        y += mock_cfg.get("body_font_size", 56) + 12

    names = ", ".join(c.name for c in characters if c.id in scene.character_ids)
    if names:
        y += 20
        draw.text((margin, y), names, fill=(160, 180, 200), font=title_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


async def generate_all_images(
    work_dir: Path,
    characters: list[Character],
    scenes: list[Scene],
    novel_name: str,
    locations: list[Location] | None = None,
) -> list[Scene]:
    from app.services import character_refs

    locs = locations or []
    characters = character_refs.merge_with_novel_registry(novel_name, characters)
    locs = character_refs.merge_locations(novel_name, locs)
    character_refs.sync_ref_paths(characters, novel_name)
    character_refs.save_registry(novel_name, characters, locs)

    images_dir = work_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    updated: list[Scene] = []
    for scene in scenes:
        out = images_dir / f"{scene.id}.png"
        create_mock_image(scene, characters, out)
        scene.image_path = str(out)
        updated.append(scene)
    return updated

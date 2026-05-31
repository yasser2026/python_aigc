"""Route image generation by app.json image_provider."""

from __future__ import annotations

from pathlib import Path

from app.core.config_loader import load_config
from app.core.schemas import Character, Location, Scene
from app.services import comfyui_client, mock_image, qwen_image


def get_image_provider() -> str:
    app_cfg = load_config("app")
    return str(app_cfg.get("image_provider", "mock")).lower()


async def generate_all_images(
    work_dir: Path,
    characters: list[Character],
    scenes: list[Scene],
    novel_name: str,
    locations: list[Location] | None = None,
) -> list[Scene]:
    provider = get_image_provider()
    if provider == "qwen":
        return await qwen_image.generate_all_images(
            work_dir, characters, scenes, novel_name, locations
        )
    if provider == "comfyui":
        return await comfyui_client.generate_all_images(
            work_dir, characters, scenes, novel_name, locations
        )
    return await mock_image.generate_all_images(
        work_dir, characters, scenes, novel_name, locations
    )

"""Scan data directory for completed works (portfolio)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.core.config_loader import get_root, load_config

_EPISODE_RE = re.compile(r"第(\d+)集$")


def _data_root() -> Path:
    app_cfg = load_config("app")
    return get_root() / app_cfg.get("data_root", "data")


def _read_meta(ep_dir: Path) -> dict:
    meta_path = ep_dir / "meta.json"
    if meta_path.is_file():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _poster_path(ep_dir: Path) -> Path | None:
    images = ep_dir / "images"
    if not images.is_dir():
        return None
    for name in ("scene_1.png", "scene_01.png"):
        p = images / name
        if p.is_file():
            return p
    pngs = sorted(images.glob("*.png"))
    return pngs[0] if pngs else None


def scan_portfolio() -> list[dict]:
    """Return portfolio items sorted by video mtime (newest first)."""
    root = _data_root()
    if not root.is_dir():
        return []

    items: list[dict] = []
    for novel_dir in sorted(root.iterdir()):
        if not novel_dir.is_dir():
            continue
        for ep_dir in sorted(novel_dir.iterdir()):
            if not ep_dir.is_dir():
                continue
            video = ep_dir / "output" / "final.mp4"
            if not video.is_file():
                continue

            meta = _read_meta(ep_dir)
            novel_name = meta.get("novel_name") or novel_dir.name
            episode = meta.get("episode")
            if episode is None:
                m = _EPISODE_RE.match(ep_dir.name)
                episode = int(m.group(1)) if m else 1

            project_id = meta.get("project_id") or f"{novel_dir.name}/{ep_dir.name}"
            poster = _poster_path(ep_dir)
            stat = video.stat()

            items.append(
                {
                    "project_id": project_id,
                    "novel_name": novel_name,
                    "episode": int(episode),
                    "has_video": True,
                    "has_poster": poster is not None,
                    "video_size_bytes": stat.st_size,
                    "finished_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            )

    items.sort(key=lambda x: x["finished_at"], reverse=True)
    return items


def resolve_poster(project_id: str) -> Path | None:
    path = _data_root() / project_id.replace("\\", "/")
    if not path.is_dir():
        return None
    return _poster_path(path)

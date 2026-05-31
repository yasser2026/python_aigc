"""Pipeline orchestrator: novel text -> final MP4."""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config_loader import get_root, load_config
from app.core.schemas import ProjectArtifacts, ProjectStatus, Scene
from app.pipeline.task_store import task_store
from app.services import comfyui_client, ffmpeg_assemble, ffmpeg_motion, llm_scene, subtitle, tts_service

logger = logging.getLogger(__name__)

STAGE_ORDER = [
    "parse_scenes",
    "generate_images",
    "tts",
    "motion_clips",
    "subtitles",
    "assemble",
]

STAGE_PROGRESS = {
    "parse_scenes": (ProjectStatus.PARSING, 10),
    "generate_images": (ProjectStatus.IMAGING, 30),
    "tts": (ProjectStatus.AUDIO, 55),
    "motion_clips": (ProjectStatus.MOTION, 70),
    "subtitles": (ProjectStatus.SUBTITLES, 80),
    "assemble": (ProjectStatus.ASSEMBLING, 90),
}


def _work_path(project_id: str) -> Path:
    app_cfg = load_config("app")
    root = get_root() / app_cfg.get("data_root", "data") / project_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _update_stage(project_id: str, stage: str, progress: float) -> None:
    status, _ = STAGE_PROGRESS.get(stage, (ProjectStatus.PENDING, 0))
    task_store.update(
        project_id,
        status=status,
        current_stage=stage,
        progress=progress,
    )


async def run_pipeline(project_id: str) -> None:
    rec = task_store.get(project_id)
    if not rec:
        return

    work_dir = Path(rec.work_dir)
    pipeline_cfg = load_config("pipeline")
    configured = set(pipeline_cfg.get("stages", STAGE_ORDER))
    stages = [s for s in STAGE_ORDER if s in configured]

    try:
        script = None
        scenes: list[Scene] = []
        durations: list[float] = []

        if "parse_scenes" in stages:
            _update_stage(project_id, "parse_scenes", 5)
            script = await llm_scene.parse_novel_to_scenes(rec.text)
            scenes_path = llm_scene.save_scene_script(work_dir, script)
            scenes = script.scenes
            _update_stage(project_id, "parse_scenes", 10)
            task_store.update(
                project_id,
                artifacts=ProjectArtifacts(scenes_json=str(scenes_path)),
            )
        else:
            script = llm_scene.load_scene_script(work_dir)
            scenes = script.scenes

        characters = script.characters if script else []

        if "generate_images" in stages:
            _update_stage(project_id, "generate_images", 20)
            scenes = await comfyui_client.generate_all_images(work_dir, characters, scenes)
            # Persist updated paths
            script.scenes = scenes
            script.characters = characters
            llm_scene.save_scene_script(work_dir, script)
            _update_stage(project_id, "generate_images", 30)
            task_store.update(
                project_id,
                artifacts=ProjectArtifacts(
                    scenes_json=str(work_dir / "scenes.json"),
                    images_dir=str(work_dir / "images"),
                ),
            )

        clip_paths: list[Path] = []

        if "tts" in stages:
            _update_stage(project_id, "tts", 60)
            audio_dir = work_dir / "audio"
            durations = []
            for scene in scenes:
                audio_path = audio_dir / f"{scene.id}.mp3"
                dur = await tts_service.synthesize_scene(scene, audio_path)
                durations.append(dur)
            _update_stage(project_id, "tts", 65)

        default_dur = pipeline_cfg.get("scene_duration_sec", 4)
        if not durations:
            durations = [default_dur] * len(scenes)

        if "motion_clips" in stages:
            _update_stage(project_id, "motion_clips", 65)
            clips_dir = work_dir / "clips"
            for i, scene in enumerate(scenes):
                img = Path(scene.image_path or work_dir / "images" / f"{scene.id}.png")
                dur = durations[i] if i < len(durations) else default_dur
                dur = max(dur, default_dur * 0.5)

                silent_clip = clips_dir / f"{scene.id}_silent.mp4"
                await ffmpeg_motion.image_to_clip(img, silent_clip, dur)

                if scene.audio_path:
                    clip_with_audio = clips_dir / f"{scene.id}.mp4"
                    await ffmpeg_motion.merge_audio_to_clip(
                        silent_clip,
                        Path(scene.audio_path),
                        clip_with_audio,
                        dur,
                    )
                    scene.clip_path = str(clip_with_audio)
                    clip_paths.append(clip_with_audio)
                else:
                    scene.clip_path = str(silent_clip)
                    clip_paths.append(silent_clip)

            script.scenes = scenes
            llm_scene.save_scene_script(work_dir, script)
            _update_stage(project_id, "motion_clips", 75)

        if "subtitles" in stages:
            _update_stage(project_id, "subtitles", 72)
            subs_dir = work_dir / "subs"
            for i, scene in enumerate(scenes):
                dur = durations[i] if i < len(durations) else default_dur
                subtitle.build_scene_ass(scene, dur, subs_dir / f"{scene.id}.ass")
            subtitle.build_full_ass(scenes, durations, subs_dir / "full.ass")
            _update_stage(project_id, "subtitles", 75)

        if "assemble" in stages:
            _update_stage(project_id, "assemble", 85)
            if not clip_paths:
                clip_paths = [Path(s.clip_path) for s in scenes if s.clip_path]
            output_dir = work_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            final_path = output_dir / "final.mp4"
            ass_path = work_dir / "subs" / "full.ass"
            await ffmpeg_assemble.assemble_final(
                clip_paths,
                ass_path if ass_path.exists() else None,
                final_path,
            )
            _update_stage(project_id, "assemble", 95)
            task_store.update(
                project_id,
                status=ProjectStatus.DONE,
                progress=100.0,
                current_stage="done",
                artifacts=ProjectArtifacts(
                    scenes_json=str(work_dir / "scenes.json"),
                    output_video=str(final_path),
                    images_dir=str(work_dir / "images"),
                ),
            )
            logger.info("Project %s completed: %s", project_id, final_path)

    except Exception as e:
        logger.exception("Pipeline failed for %s", project_id)
        task_store.update(
            project_id,
            status=ProjectStatus.FAILED,
            error=str(e),
            current_stage="failed",
        )

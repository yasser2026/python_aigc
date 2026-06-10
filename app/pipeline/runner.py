"""Pipeline orchestrator: novel text -> final MP4."""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config_loader import load_config
from app.core.runtime import get_mode, set_mode
from app.core.schemas import ProjectArtifacts, ProjectStatus, Scene
from app.pipeline import state as pipeline_state
from app.pipeline.task_store import task_store
from app.services import (
    animation_provider,
    character_refs,
    ffmpeg_assemble,
    ffmpeg_motion,
    graph_context,
    image_provider,
    knowledge_graph,
    llm_scene,
    novel_meta,
    scene_normalizer,
    subtitle,
    tts_provider,
)

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


def _update_stage(project_id: str, stage: str, progress: float) -> None:
    status, _ = STAGE_PROGRESS.get(stage, (ProjectStatus.PENDING, 0))
    task_store.update(
        project_id,
        mode=get_mode(),
        status=status,
        current_stage=stage,
        progress=progress,
    )


def _mark_done(project_id: str, work_dir: Path) -> None:
    final_path = work_dir / "output" / "final.mp4"
    task_store.update(
        project_id,
        mode=get_mode(),
        status=ProjectStatus.DONE,
        progress=100.0,
        current_stage="done",
        artifacts=ProjectArtifacts(
            scenes_json=str(work_dir / "scenes.json"),
            episode_analysis=str(work_dir / "episode_analysis.json")
            if (work_dir / "episode_analysis.json").is_file()
            else None,
            output_video=str(final_path),
            images_dir=str(work_dir / "images"),
        ),
    )


async def run_pipeline(project_id: str, mode: str = "video") -> None:
    set_mode(mode)
    rec = task_store.get(project_id, mode=mode)
    if not rec:
        return

    work_dir = Path(rec.work_dir)
    pipeline_cfg = load_config("pipeline")
    cache_enabled = pipeline_cfg.get("cache", {}).get("enabled", True)
    fingerprint = pipeline_state.compute_fingerprint_from_record(rec)
    pstate = pipeline_state.load_or_reset_state(work_dir, fingerprint)

    if pipeline_state.is_fully_complete(
        work_dir, pstate, fingerprint, enabled=cache_enabled
    ):
        logger.info("Project %s input unchanged and complete, skipping pipeline", project_id)
        _mark_done(project_id, work_dir)
        return

    configured = set(pipeline_cfg.get("stages", STAGE_ORDER))
    stages = [s for s in STAGE_ORDER if s in configured]

    try:
        script = None
        scenes: list[Scene] = []
        durations: list[float] = []

        if "parse_scenes" in stages:
            if pipeline_state.should_skip_stage(
                work_dir, "parse_scenes", pstate, fingerprint, enabled=cache_enabled
            ):
                logger.info("Skipping parse_scenes for %s (input unchanged)", project_id)
                script = llm_scene.load_scene_script(work_dir)
                scenes = script.scenes
                _update_stage(project_id, "parse_scenes", 10)
            else:
                _update_stage(project_id, "parse_scenes", 5)
                script = await llm_scene.parse_novel_to_scenes(
                    rec.text,
                    rec.novel_name,
                    narrative_mode=rec.narrative_mode,
                    supporting_names=rec.supporting_names or None,
                    episode=rec.episode,
                )
                script.characters = character_refs.resolve_canonical_characters(
                    rec.novel_name, script.characters
                )
                novel_meta.ensure_protagonist_resolved(rec.novel_name, script.characters)
                script.characters = novel_meta.enforce_locked_protagonist_on_characters(
                    rec.novel_name, script.characters
                )
                script = await scene_normalizer.normalize_script(
                    script,
                    rec.novel_name,
                    rec.text,
                    rec.narrative_mode,
                    work_dir=work_dir,
                    supporting_names=rec.supporting_names or None,
                )
                script.characters = character_refs.merge_with_novel_registry(
                    rec.novel_name, script.characters
                )
                script.locations = character_refs.merge_locations(
                    rec.novel_name, script.locations
                )
                character_refs.save_registry(
                    rec.novel_name, script.characters, script.locations
                )
                knowledge_graph.merge_episode(
                    rec.novel_name,
                    rec.episode,
                    script,
                    project_id=project_id,
                )
                knowledge_graph.merge_graph_delta(
                    rec.novel_name, rec.episode, script.graph_delta
                )
                knowledge_graph.export_to_json(rec.novel_name)
                scenes_path = llm_scene.save_scene_script(work_dir, script)
                analysis_path = llm_scene.save_episode_analysis(
                    work_dir, script.episode_analysis
                )
                scenes = script.scenes
                _update_stage(project_id, "parse_scenes", 10)
                task_store.update(
                    project_id,
                    artifacts=ProjectArtifacts(
                        scenes_json=str(scenes_path),
                        episode_analysis=str(analysis_path) if analysis_path else None,
                    ),
                )
                if cache_enabled and pipeline_state.verify_stage_artifacts(
                    work_dir, "parse_scenes"
                ):
                    pstate = pipeline_state.mark_stage_complete(
                        work_dir, pstate, "parse_scenes", fingerprint
                    )
        else:
            script = llm_scene.load_scene_script(work_dir)
            scenes = script.scenes

        scenes = pipeline_state.hydrate_scene_paths(work_dir, scenes)
        if script:
            script.scenes = scenes

        characters = script.characters if script else []
        locations = script.locations if script else []

        if "generate_images" in stages:
            if pipeline_state.should_skip_stage(
                work_dir, "generate_images", pstate, fingerprint, enabled=cache_enabled
            ):
                logger.info("Skipping generate_images for %s (input unchanged)", project_id)
                _update_stage(project_id, "generate_images", 30)
            else:
                _update_stage(project_id, "generate_images", 20)
                scenes = await image_provider.generate_all_images(
                    work_dir,
                    characters,
                    scenes,
                    rec.novel_name,
                    locations=locations,
                )
                # Persist updated paths
                script.scenes = scenes
                script.characters = characters
                llm_scene.save_scene_script(work_dir, script)
                character_refs.save_registry(
                    rec.novel_name, characters, locations
                )
                _update_stage(project_id, "generate_images", 30)
                task_store.update(
                    project_id,
                    artifacts=ProjectArtifacts(
                        scenes_json=str(work_dir / "scenes.json"),
                        images_dir=str(work_dir / "images"),
                    ),
                )
                if cache_enabled and pipeline_state.verify_stage_artifacts(
                    work_dir, "generate_images"
                ):
                    pstate = pipeline_state.mark_stage_complete(
                        work_dir, pstate, "generate_images", fingerprint
                    )

        clip_paths: list[Path] = []

        if "tts" in stages:
            if pipeline_state.should_skip_stage(
                work_dir, "tts", pstate, fingerprint, enabled=cache_enabled
            ):
                logger.info("Skipping tts for %s (input unchanged)", project_id)
                default_dur = pipeline_cfg.get("scene_duration_sec", 4)
                durations = await pipeline_state.load_durations_from_audio(
                    work_dir, scenes, default_dur=default_dur
                )
                _update_stage(project_id, "tts", 65)
            else:
                _update_stage(project_id, "tts", 60)
                audio_dir = work_dir / "audio"
                durations = []
                for i, scene in enumerate(scenes):
                    audio_path = audio_dir / f"{scene.id}.mp3"
                    char_map = {c.id: c for c in characters}
                    scene = graph_context.validate_scene_speaker(scene)
                    dur = await tts_provider.synthesize_scene(
                        scene,
                        audio_path,
                        char_map=char_map,
                        novel_name=rec.novel_name,
                    )
                    scenes[i] = scene
                    durations.append(dur)
                script.scenes = scenes
                llm_scene.save_scene_script(work_dir, script)
                _update_stage(project_id, "tts", 65)
                if cache_enabled and pipeline_state.verify_stage_artifacts(
                    work_dir, "tts"
                ):
                    pstate = pipeline_state.mark_stage_complete(
                        work_dir, pstate, "tts", fingerprint
                    )

        default_dur = pipeline_cfg.get("scene_duration_sec", 4)
        if not durations:
            durations = [default_dur] * len(scenes)

        if "motion_clips" in stages:
            if pipeline_state.should_skip_stage(
                work_dir, "motion_clips", pstate, fingerprint, enabled=cache_enabled
            ):
                logger.info("Skipping motion_clips for %s (input unchanged)", project_id)
                clip_paths = [
                    Path(s.clip_path)
                    for s in scenes
                    if s.clip_path and Path(s.clip_path).is_file()
                ]
                _update_stage(project_id, "motion_clips", 75)
            else:
                _update_stage(project_id, "motion_clips", 65)
                clips_dir = work_dir / "clips"
                anime_mode = get_mode() == "anime"
                for i, scene in enumerate(scenes):
                    img = Path(scene.image_path or work_dir / "images" / f"{scene.id}.png")
                    dur = durations[i] if i < len(durations) else default_dur
                    dur = max(dur, default_dur * 0.5)

                    if anime_mode:
                        clip = await animation_provider.animate_scene(
                            scene,
                            img,
                            clips_dir,
                            dur,
                            novel_name=rec.novel_name,
                        )
                        scene.clip_path = str(clip)
                        clip_paths.append(clip)
                        continue

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
                if cache_enabled and pipeline_state.verify_stage_artifacts(
                    work_dir, "motion_clips"
                ):
                    pstate = pipeline_state.mark_stage_complete(
                        work_dir, pstate, "motion_clips", fingerprint
                    )

        if "subtitles" in stages:
            if pipeline_state.should_skip_stage(
                work_dir, "subtitles", pstate, fingerprint, enabled=cache_enabled
            ):
                logger.info("Skipping subtitles for %s (input unchanged)", project_id)
                _update_stage(project_id, "subtitles", 75)
            else:
                _update_stage(project_id, "subtitles", 72)
                subs_dir = work_dir / "subs"
                for i, scene in enumerate(scenes):
                    dur = durations[i] if i < len(durations) else default_dur
                    subtitle.build_scene_ass(
                        scene,
                        dur,
                        subs_dir / f"{scene.id}.ass",
                        novel_name=rec.novel_name,
                        char_map={c.id: c for c in characters},
                    )
                subtitle.build_full_ass(
                    scenes,
                    durations,
                    subs_dir / "full.ass",
                    novel_name=rec.novel_name,
                    char_map={c.id: c for c in characters},
                )
                _update_stage(project_id, "subtitles", 75)
                if cache_enabled and pipeline_state.verify_stage_artifacts(
                    work_dir, "subtitles"
                ):
                    pstate = pipeline_state.mark_stage_complete(
                        work_dir, pstate, "subtitles", fingerprint
                    )

        if "assemble" in stages:
            if pipeline_state.should_skip_stage(
                work_dir, "assemble", pstate, fingerprint, enabled=cache_enabled
            ):
                logger.info("Skipping assemble for %s (input unchanged)", project_id)
                _mark_done(project_id, work_dir)
            else:
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
                if cache_enabled and pipeline_state.verify_stage_artifacts(
                    work_dir, "assemble"
                ):
                    pstate = pipeline_state.mark_stage_complete(
                        work_dir, pstate, "assemble", fingerprint
                    )
                _mark_done(project_id, work_dir)
                logger.info("Project %s completed: %s", project_id, final_path)

    except Exception as e:
        logger.exception("Pipeline failed for %s", project_id)
        task_store.update(
            project_id,
            mode=get_mode(),
            status=ProjectStatus.FAILED,
            error=str(e),
            current_stage="failed",
        )

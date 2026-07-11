from __future__ import annotations

import argparse
import logging
from pathlib import Path

from moviepy.editor import AudioClip, AudioFileClip, CompositeAudioClip, afx, concatenate_audioclips

from audio_utils import split_tempo_adjust_parts, tempo_adjust
from caption_generator import generate_caption
from config import configure_logging, settings
from file_manager import FileManager, RunPaths
from image_generator import ImageGenerator
from image_prompt_generator import ImagePromptGenerator
from story_generator import StoryGenerator
from story_metadata import StoryMetadata, load_metadata, save_metadata, split_story_header
from subtitle_generator import SubtitleGenerator
from usage_tracker import UsageTracker
from video_builder import VideoBuilder
from voice_generator import VoiceGenerator


logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Automatisierter deutscher Short-Video-Generator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Kompletten Video-Workflow starten")
    generate.add_argument("--story-only", action="store_true", help="Nur Story erzeugen")
    generate.add_argument("--keep-story", action="store_true", help="Vorhandene Story im Run behalten, Rest neu erzeugen")
    generate.add_argument("--skip-images", action="store_true", help="Vorhandene Bilder im Run-Ordner nutzen")
    generate.add_argument("--skip-voice", action="store_true", help="Vorhandenes voiceover.mp3 nutzen")
    generate.add_argument("--run-id", help="Optional vorhandenen Run nutzen, z. B. mit --skip-images")
    generate.add_argument("--city", help="Stadt nur fuer diesen neuen Run fest vorgeben")

    build = subparsers.add_parser("build", help="Video aus vorhandenem Run bauen")
    build.add_argument("--run-id", required=True, help="Run-ID, z. B. 2026-06-09_001")

    args = parser.parse_args()
    manager = FileManager(settings.resolved_output_dir)
    if args.command == "generate":
        if args.run_id:
            run_paths = manager.get_run(args.run_id)
            logger.info("Using run %s at %s", run_paths.run_id, run_paths.root)
        elif args.skip_images or args.skip_voice:
            run_paths = manager.latest_run()
            logger.info("Using latest run %s at %s", run_paths.run_id, run_paths.root)
        else:
            run_paths = manager.create_run()
            logger.info("Created run %s at %s", run_paths.run_id, run_paths.root)
        generate_run(
            run_paths,
            story_only=args.story_only,
            keep_story=args.keep_story,
            skip_images=args.skip_images,
            skip_voice=args.skip_voice,
            city=args.city,
        )
    elif args.command == "build":
        run_paths = manager.get_run(args.run_id)
        build_video_from_existing(run_paths)


def generate_run(
    run_paths: RunPaths,
    story_only: bool,
    keep_story: bool,
    skip_images: bool,
    skip_voice: bool,
    city: str | None = None,
) -> None:
    usage_tracker = UsageTracker(
        run_paths.usage_report,
        settings.openai_text_input_usd_per_1m,
        settings.openai_text_output_usd_per_1m,
        settings.openai_image_estimated_usd_per_image,
    )
    if (keep_story or skip_images or skip_voice) and run_paths.story.exists():
        story = run_paths.story.read_text(encoding="utf-8")
        logger.info("Using existing story: %s", run_paths.story)
    elif keep_story:
        raise RuntimeError(f"--keep-story gesetzt, aber Story fehlt: {run_paths.story}")
    else:
        story = StoryGenerator(run_paths.story, usage_tracker=usage_tracker, city=city).generate_story()
    if story_only:
        usage_tracker.save()
        logger.info("Story-only run finished: %s", run_paths.story)
        return

    metadata, story_body = split_story_header(story)

    if skip_voice:
        if not run_paths.voiceover.exists():
            raise RuntimeError(f"--skip-voice gesetzt, aber {run_paths.voiceover} existiert nicht.")
        audio_path = run_paths.voiceover
        saved_metadata = load_metadata(run_paths.metadata)
        if saved_metadata:
            metadata = saved_metadata
    else:
        voice_generator = VoiceGenerator(usage_tracker=usage_tracker)
        voice_generator.generate_voiceover("Hood Storys aus deutschen Städten.", run_paths.cover_title_voiceover)
        voice_generator.generate_voiceover(f"Folge {metadata.episode_number}: {metadata.city}.", run_paths.cover_episode_voiceover)
        voice_generator.generate_voiceover(
            story_body,
            run_paths.story_voiceover,
            alignment_path=run_paths.story_alignment,
        )
        audio_path, metadata = build_audio_track(run_paths, metadata)
    log_audio_duration(audio_path)

    if skip_images:
        image_paths = existing_images(run_paths.images)
    else:
        prompt_specs = ImagePromptGenerator(run_paths.image_prompts, usage_tracker=usage_tracker).generate_image_prompts(story)
        image_paths = ImageGenerator(usage_tracker=usage_tracker).generate_images(
            [spec.prompt for spec in prompt_specs],
            run_paths.images,
        )
    if len(image_paths) != settings.total_image_count:
        raise RuntimeError(f"Fuer den Video-Bau werden genau {settings.total_image_count} Bilder benoetigt.")

    save_metadata(run_paths.metadata, metadata)
    generate_caption(metadata, run_paths.caption)
    subtitle_audio = run_paths.story_voiceover_timed if run_paths.story_voiceover_timed.exists() else audio_path
    SubtitleGenerator().generate_srt(
        story_body,
        subtitle_audio,
        run_paths.subtitles_srt,
        metadata.story_start_seconds,
        alignment_path=run_paths.story_alignment,
        tempo_factor=settings.voice_speed,
    )
    VideoBuilder().build_video(
        image_paths,
        audio_path,
        run_paths.subtitles_srt,
        run_paths.final_video,
        run_paths.metadata,
        run_paths.image_prompts,
        run_paths.story_alignment,
    )
    usage_tracker.save()
    logger.info("Finished video: %s", run_paths.final_video)


def build_video_from_existing(run_paths: RunPaths) -> None:
    image_paths = existing_images(run_paths.images)
    if not run_paths.voiceover.exists():
        raise RuntimeError(f"Voiceover fehlt: {run_paths.voiceover}")
    if run_paths.cover_title_voiceover.exists() and run_paths.cover_episode_voiceover.exists() and run_paths.story_voiceover.exists():
        story = run_paths.story.read_text(encoding="utf-8")
        metadata, _ = split_story_header(story)
        _, metadata = build_audio_track(run_paths, metadata)
        save_metadata(run_paths.metadata, metadata)
    if not run_paths.story.exists():
        raise RuntimeError("Story fehlt. Untertitel koennen nicht neu erzeugt werden.")
    story = run_paths.story.read_text(encoding="utf-8")
    metadata, story_body = split_story_header(story)
    saved_metadata = load_metadata(run_paths.metadata)
    if saved_metadata:
        metadata = StoryMetadata(
            episode_number=metadata.episode_number,
            city=metadata.city,
            cover_text=metadata.cover_text,
            story_start_seconds=saved_metadata.story_start_seconds,
            cover_duration_seconds=saved_metadata.cover_duration_seconds,
            transition_duration_seconds=saved_metadata.transition_duration_seconds,
        )
    subtitle_audio = run_paths.story_voiceover_timed if run_paths.story_voiceover_timed.exists() else run_paths.voiceover
    SubtitleGenerator().generate_srt(
        story_body,
        subtitle_audio,
        run_paths.subtitles_srt,
        metadata.story_start_seconds,
        alignment_path=run_paths.story_alignment,
        tempo_factor=settings.voice_speed,
    )
    save_metadata(run_paths.metadata, metadata)
    generate_caption(metadata, run_paths.caption)
    VideoBuilder().build_video(
        image_paths,
        run_paths.voiceover,
        run_paths.subtitles_srt,
        run_paths.final_video,
        run_paths.metadata,
        run_paths.image_prompts,
        run_paths.story_alignment,
    )


def existing_images(images_dir: Path) -> list[Path]:
    paths = sorted(
        path for path in images_dir.glob("image_*.*")
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    if len(paths) > settings.total_image_count:
        cover = paths[0]
        story_images = paths[1:]
        needed_story_images = settings.total_image_count - 1
        selected_story_images = [
            story_images[round(index * (len(story_images) - 1) / (needed_story_images - 1))]
            for index in range(needed_story_images)
        ]
        selected = [cover, *selected_story_images]
        logger.info(
            "Vorhandener Run hat %s Bilder. Nutze Cover plus %s gleichmaessig ausgewaehlte Storybilder.",
            len(paths),
            needed_story_images,
        )
        return selected
    if len(paths) != settings.total_image_count:
        raise RuntimeError(f"Erwartet {settings.total_image_count} vorhandene Bilder in {images_dir}, gefunden: {len(paths)}")
    return paths


def build_audio_track(run_paths: RunPaths, metadata: StoryMetadata) -> tuple[Path, StoryMetadata]:
    tempo_adjust(run_paths.cover_title_voiceover, run_paths.cover_title_voiceover_timed, settings.voice_speed)
    tempo_adjust(run_paths.cover_episode_voiceover, run_paths.cover_episode_voiceover_timed, settings.voice_speed)
    tempo_adjust(run_paths.story_voiceover, run_paths.story_voiceover_timed, settings.voice_speed)
    title = AudioFileClip(str(run_paths.cover_title_voiceover_timed))
    episode = AudioFileClip(str(run_paths.cover_episode_voiceover_timed))
    story = AudioFileClip(str(run_paths.story_voiceover_timed))
    logger.info(
        "Audio speed %.2fx: title=%.2fs episode=%.2fs story=%.2fs outro=%.2fs",
        settings.voice_speed,
        title.duration,
        episode.duration,
        story.duration,
        settings.outro_duration,
    )
    story = story.fx(afx.audio_fadeout, settings.audio_boundary_fade_seconds)
    story_end_padding = AudioClip(
        lambda t: 0,
        duration=settings.story_end_padding_seconds,
        fps=44100,
    )
    outro_silence = AudioClip(lambda t: 0, duration=settings.outro_duration, fps=44100)
    voice_track = concatenate_audioclips([title, episode, story, story_end_padding, outro_silence])
    audio_layers = [voice_track]
    transition_reload = None
    transition_boom = None
    transition_path = resolve_asset(settings.cover_transition_sound)
    if transition_path.exists():
        split_tempo_adjust_parts(
            transition_path,
            run_paths.cover_transition_reload_processed,
            run_paths.cover_transition_boom_processed,
            settings.cover_transition_sound_start_seconds,
            settings.cover_transition_split_seconds,
            settings.cover_transition_first_speed,
            settings.cover_transition_second_speed,
        )
        transition_reload = AudioFileClip(str(run_paths.cover_transition_reload_processed))
        transition_boom = AudioFileClip(str(run_paths.cover_transition_boom_processed))
        cover_end = title.duration + episode.duration
        reload_start = title.duration
        reload_end = reload_start + transition_reload.duration
        boom_start = max(
            0.0,
            cover_end - settings.cover_transition_sync_advance_seconds,
        )
        audio_layers.append(
            transition_reload.volumex(settings.cover_transition_reload_volume).set_start(reload_start)
        )
        audio_layers.append(
            transition_boom.volumex(settings.cover_transition_volume).set_start(boom_start)
        )
        logger.info(
            "SFX timeline: reload %.2f-%.2fs, boom starts %.2fs, cover ends %.2fs",
            reload_start,
            reload_end,
            boom_start,
            cover_end,
        )
    combined = CompositeAudioClip(audio_layers).set_duration(voice_track.duration)
    combined.write_audiofile(str(run_paths.voiceover), fps=44100, logger=None)
    cover_duration = float(title.duration + episode.duration)
    updated_metadata = StoryMetadata(
        episode_number=metadata.episode_number,
        city=metadata.city,
        cover_text=metadata.cover_text,
        story_start_seconds=cover_duration,
        cover_duration_seconds=cover_duration,
        transition_duration_seconds=0.0,
    )
    for clip in [title, episode, story, story_end_padding, outro_silence, *audio_layers]:
        clip.close()
    if transition_reload is not None:
        transition_reload.close()
    if transition_boom is not None:
        transition_boom.close()
    combined.close()
    return run_paths.voiceover, updated_metadata


def resolve_asset(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path(__file__).resolve().parent / path


def log_audio_duration(audio_path: Path) -> None:
    with AudioFileClip(str(audio_path)) as audio:
        duration = float(audio.duration)
    logger.info("Finale Videodauer anhand Audio: %.2f Sekunden", duration)


if __name__ == "__main__":
    main()

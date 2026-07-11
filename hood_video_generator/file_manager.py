from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    root: Path
    images: Path
    audio: Path
    subtitles: Path
    story: Path
    image_prompts: Path
    image_scene_plan: Path
    voiceover: Path
    cover_voiceover: Path
    cover_title_voiceover: Path
    cover_title_voiceover_timed: Path
    cover_episode_voiceover: Path
    cover_episode_voiceover_timed: Path
    story_voiceover: Path
    story_alignment: Path
    story_voiceover_timed: Path
    cover_transition_processed: Path
    cover_transition_reload_processed: Path
    cover_transition_boom_processed: Path
    subtitles_srt: Path
    subtitles_json: Path
    subtitle_groups: Path
    metadata: Path
    usage_report: Path
    caption: Path
    posting_plan: Path
    weekly_posting_plan: Path
    final_video: Path


class FileManager:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_run(self) -> RunPaths:
        today = datetime.now().strftime("%Y-%m-%d")
        existing = sorted(self.output_dir.glob(f"{today}_*"))
        next_number = len([path for path in existing if path.is_dir()]) + 1
        run_id = f"{today}_{next_number:03d}"
        return self._create_paths(run_id, create_dirs=False)

    def get_run(self, run_id: str) -> RunPaths:
        return self._create_paths(run_id, create_dirs=True)

    def latest_run(self) -> RunPaths:
        runs = sorted(
            path for path in self.output_dir.iterdir()
            if path.is_dir() and path.name != "_subtitle_cache"
        )
        if not runs:
            raise RuntimeError("Kein vorhandener Run-Ordner gefunden.")
        return self._create_paths(runs[-1].name, create_dirs=True)

    def _create_paths(self, run_id: str, create_dirs: bool) -> RunPaths:
        root = self.output_dir / run_id
        images = root / "images"
        audio = root / "audio"
        subtitles = root / "subtitles"
        if create_dirs:
            for path in (root, images, audio, subtitles):
                path.mkdir(parents=True, exist_ok=True)
        return RunPaths(
            run_id=run_id,
            root=root,
            images=images,
            audio=audio,
            subtitles=subtitles,
            story=root / "story.txt",
            image_prompts=root / "image_prompts.json",
            image_scene_plan=root / "image_scene_plan.json",
            voiceover=audio / "voiceover.mp3",
            cover_voiceover=audio / "cover_voiceover.mp3",
            cover_title_voiceover=audio / "cover_title_voiceover.mp3",
            cover_title_voiceover_timed=audio / "cover_title_voiceover_timed.mp3",
            cover_episode_voiceover=audio / "cover_episode_voiceover.mp3",
            cover_episode_voiceover_timed=audio / "cover_episode_voiceover_timed.mp3",
            story_voiceover=audio / "story_voiceover.mp3",
            story_alignment=audio / "story_alignment.json",
            story_voiceover_timed=audio / "story_voiceover_timed.mp3",
            cover_transition_processed=audio / "cover_transition_processed.mp3",
            cover_transition_reload_processed=audio / "cover_transition_reload_processed.mp3",
            cover_transition_boom_processed=audio / "cover_transition_boom_processed.mp3",
            subtitles_srt=subtitles / "subtitles.srt",
            subtitles_json=subtitles / "subtitles.json",
            subtitle_groups=root / "subtitle_groups.json",
            metadata=root / "metadata.json",
            usage_report=root / "usage_report.json",
            caption=root / "caption.txt",
            posting_plan=root / "posting_plan.json",
            weekly_posting_plan=self.output_dir / "weekly_posting_plan.json",
            final_video=root / "final_video.mp4",
        )

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


HEADER_RE = re.compile(
    r"^\s*Hood Storys aus deutschen St(?:ä|Ã¤|ÃƒÂ¤|ae)dten\s+Folge\s+(\d+)\s*:\s*(.+?)\s*(?:\r?\n|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StoryMetadata:
    run_id: str = ""
    episode_number: int = 1
    city: str = ""
    cover_text: str = ""
    bundesland: str = ""
    created_at: str = ""
    planned_post_date: str = ""
    planned_post_time: str = ""
    actual_post_date: str = ""
    actual_post_time: str = ""
    video_length_seconds: float = 0.0
    story_length_chars: int = 0
    hook_text: str = ""
    story_start_seconds: float = 0.0
    cover_duration_seconds: float = 0.0
    transition_duration_seconds: float = 0.0
    caption_text: str = ""
    city_hashtag: str = ""
    city_story_hashtag: str = ""
    used_hashtags: tuple[str, ...] = ()
    used_local_mentions: tuple[str, ...] = ()
    caption_hook: str = ""
    caption_question: str = ""
    hook_category: str = ""
    story_type: str = ""
    local_places_used: tuple[str, ...] = ()
    hashtags: tuple[str, ...] = ()
    subtitle_mode: str = ""
    visual_style_version: str = "dynamic_visual_beats_v1"
    sound_design_version: str = "local_sound_design_v1"
    trend_experiment_applied: bool = False
    is_trend_experiment: bool = False
    trend_id: str = ""
    trend_type: str = ""
    trend_name: str = ""
    quality_score: int = 0
    final_video_path: str = ""
    manual_upload_status: str = "generated"


def split_story_header(story: str) -> tuple[StoryMetadata, str]:
    normalized_story = normalize_text(story)
    match = HEADER_RE.search(normalized_story)
    if not match:
        metadata = StoryMetadata(
            episode_number=1,
            city="deutschen Städten",
            cover_text="Hood Storys aus deutschen Städten",
        )
        return metadata, normalized_story.strip()

    episode_number = int(match.group(1))
    city = normalize_text(match.group(2).strip())
    body = normalized_story[match.end():].strip()
    cover_text = f"Hood Storys aus deutschen Städten. Folge {episode_number}: {city}."
    return StoryMetadata(episode_number=episode_number, city=city, cover_text=cover_text), body


def save_metadata(path: Path, metadata: StoryMetadata) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(metadata), ensure_ascii=False, indent=2), encoding="utf-8")


def load_metadata(path: Path) -> StoryMetadata | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return StoryMetadata(
        run_id=normalize_text(str(data.get("run_id", ""))),
        episode_number=int(data.get("episode_number", 1)),
        city=normalize_text(str(data.get("city", ""))),
        cover_text=normalize_text(str(data.get("cover_text", ""))),
        bundesland=normalize_text(str(data.get("bundesland", ""))),
        created_at=normalize_text(str(data.get("created_at", ""))),
        planned_post_date=normalize_text(str(data.get("planned_post_date", ""))),
        planned_post_time=normalize_text(str(data.get("planned_post_time", ""))),
        actual_post_date=normalize_text(str(data.get("actual_post_date", ""))),
        actual_post_time=normalize_text(str(data.get("actual_post_time", ""))),
        video_length_seconds=float(data.get("video_length_seconds", 0.0)),
        story_length_chars=int(data.get("story_length_chars", 0)),
        hook_text=normalize_text(str(data.get("hook_text", ""))),
        story_start_seconds=float(data.get("story_start_seconds", 0.0)),
        cover_duration_seconds=float(data.get("cover_duration_seconds", 0.0)),
        transition_duration_seconds=float(data.get("transition_duration_seconds", 0.0)),
        caption_text=normalize_text(str(data.get("caption_text", ""))),
        city_hashtag=normalize_text(str(data.get("city_hashtag", ""))),
        city_story_hashtag=normalize_text(str(data.get("city_story_hashtag", ""))),
        used_hashtags=tuple(str(value) for value in data.get("used_hashtags", [])),
        used_local_mentions=tuple(str(value) for value in data.get("used_local_mentions", [])),
        caption_hook=normalize_text(str(data.get("caption_hook", ""))),
        caption_question=normalize_text(str(data.get("caption_question", ""))),
        hook_category=normalize_text(str(data.get("hook_category", ""))),
        story_type=normalize_text(str(data.get("story_type", ""))),
        local_places_used=tuple(str(value) for value in data.get("local_places_used", [])),
        hashtags=tuple(str(value) for value in data.get("hashtags", [])),
        subtitle_mode=normalize_text(str(data.get("subtitle_mode", ""))),
        visual_style_version=normalize_text(str(data.get("visual_style_version", "dynamic_visual_beats_v1"))),
        sound_design_version=normalize_text(str(data.get("sound_design_version", "local_sound_design_v1"))),
        trend_experiment_applied=bool(data.get("trend_experiment_applied", data.get("is_trend_experiment", False))),
        is_trend_experiment=bool(data.get("is_trend_experiment", False)),
        trend_id=normalize_text(str(data.get("trend_id", ""))),
        trend_type=normalize_text(str(data.get("trend_type", ""))),
        trend_name=normalize_text(str(data.get("trend_name", ""))),
        quality_score=int(data.get("quality_score", 0)),
        final_video_path=normalize_text(str(data.get("final_video_path", ""))),
        manual_upload_status=normalize_text(str(data.get("manual_upload_status", "generated"))),
    )


def normalize_text(value: str) -> str:
    replacements = {
        "Ã¤": "ä",
        "Ã¶": "ö",
        "Ã¼": "ü",
        "ÃŸ": "ß",
        "Ã„": "Ä",
        "Ã–": "Ö",
        "Ãœ": "Ü",
        "â€œ": '"',
        "â€ž": '"',
        "â€": '"',
        "â€“": "-",
        "â€™": "'",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value

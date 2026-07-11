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
    episode_number: int
    city: str
    cover_text: str
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
        episode_number=int(data["episode_number"]),
        city=normalize_text(str(data["city"])),
        cover_text=normalize_text(str(data["cover_text"])),
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

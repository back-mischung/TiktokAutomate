from __future__ import annotations

import json
import re
from pathlib import Path

from config import ROOT_DIR
from story_metadata import StoryMetadata


HASHTAGS = [
    "#hoodstory",
    "#deutschestory",
    "#tiktokstory",
    "#urbanstory",
    "#deutschland",
    "#deutschestädte",
    "#nacht",
    "#viral",
    "#fyp",
    "#fürdich",
]


def generate_caption(metadata: StoryMetadata, output_path: Path) -> Path:
    city_hashtag = "#" + re.sub(r"[^\wäöüÄÖÜß]", "", metadata.city, flags=re.UNICODE)
    mentions = load_city_mentions(metadata.city)
    tags = [*HASHTAGS, city_hashtag]
    text = (
        f"Folge {metadata.episode_number}: {metadata.city}. "
        "Manchmal reicht eine einzige Nacht, damit sich eine ganze Stadt anders anfühlt. "
        "Welche Stadt soll als nächstes dran sein?\n\n"
        f"{' '.join(tags)}"
    )
    if mentions:
        text += f"\n\n{' '.join(mentions)}"
    output_path.write_text(text, encoding="utf-8")
    return output_path


def load_city_mentions(city: str) -> list[str]:
    path = ROOT_DIR / "city_creator_mentions.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    matching = next(
        (value for key, value in data.items() if key.casefold() == city.casefold()),
        [],
    )
    if not isinstance(matching, list):
        return []
    mentions: list[str] = []
    for value in matching[:3]:
        handle = str(value).strip()
        if handle:
            mentions.append(handle if handle.startswith("@") else f"@{handle}")
    return mentions

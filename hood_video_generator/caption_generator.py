from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

from config import ROOT_DIR
from story_metadata import StoryMetadata, normalize_text


OPTIONAL_HASHTAGS = [
    "#MysteryStory",
    "#DeutscheStory",
    "#FiktiveStory",
    "#KIStory",
    "#StorytimeDeutsch",
]

QUESTION_TEMPLATES = [
    "{city} oder {other_city} als Nächstes?",
    "Kennst du die Ecke {place}?",
    "Welche Stadt soll als Nächstes drankommen?",
    "Welche deutsche Stadt soll als Nächstes kommen?",
]

CITY_CHOICES = [
    "Regensburg",
    "Nürnberg",
    "München",
    "Dortmund",
    "Essen",
    "Leipzig",
    "Bremen",
    "Köln",
    "Dresden",
    "Wuppertal",
]

STATE_BY_CITY = {
    "Aachen": "NordrheinWestfalen",
    "Augsburg": "Bayern",
    "Berlin": "Berlin",
    "Bielefeld": "NordrheinWestfalen",
    "Bochum": "NordrheinWestfalen",
    "Bonn": "NordrheinWestfalen",
    "Bremen": "Bremen",
    "Chemnitz": "Sachsen",
    "Dortmund": "NordrheinWestfalen",
    "Dresden": "Sachsen",
    "Duisburg": "NordrheinWestfalen",
    "Düsseldorf": "NordrheinWestfalen",
    "Erfurt": "Thueringen",
    "Erlangen": "Bayern",
    "Essen": "NordrheinWestfalen",
    "Frankfurt am Main": "Hessen",
    "Freiburg im Breisgau": "BadenWuerttemberg",
    "Freising": "Bayern",
    "Hamburg": "Hamburg",
    "Hannover": "Niedersachsen",
    "Karlsruhe": "BadenWuerttemberg",
    "Kiel": "SchleswigHolstein",
    "Köln": "NordrheinWestfalen",
    "Leipzig": "Sachsen",
    "Lübeck": "SchleswigHolstein",
    "Mainz": "RheinlandPfalz",
    "Mannheim": "BadenWuerttemberg",
    "Mönchengladbach": "NordrheinWestfalen",
    "München": "Bayern",
    "Münster": "NordrheinWestfalen",
    "Nürnberg": "Bayern",
    "Potsdam": "Brandenburg",
    "Regensburg": "Bayern",
    "Rostock": "MecklenburgVorpommern",
    "Saarbrücken": "Saarland",
    "Stuttgart": "BadenWuerttemberg",
    "Wiesbaden": "Hessen",
    "Wuppertal": "NordrheinWestfalen",
    "Würzburg": "Bayern",
}


def generate_caption(metadata: StoryMetadata, output_path: Path, story_text: str = "") -> StoryMetadata:
    story_text = normalize_text(story_text).strip()
    city_hashtag = "#" + hashtag_slug(metadata.city)
    city_story_hashtag = city_hashtag + "Story"
    state_hashtag = "#" + state_for_city(metadata.city)
    local_place = extract_local_place(story_text, metadata.city)
    caption_hook = build_caption_hook(metadata.city, story_text, local_place)
    caption_question = build_caption_question(metadata.city, local_place, metadata.episode_number)
    used_hashtags = [
        "#HoodStory",
        "#UrbanStory",
        "#TikTokStory",
        city_hashtag,
        city_story_hashtag,
        state_hashtag,
        *select_optional_hashtags(story_text),
    ]
    used_local_mentions = load_city_mentions(metadata.city)
    text = f"{caption_hook}\n\n{caption_question}\n\n{' '.join(used_hashtags)}"
    if used_local_mentions:
        text += f"\n\n{' '.join(used_local_mentions)}"
    output_path.write_text(text, encoding="utf-8")
    return replace(
        metadata,
        caption_text=text,
        city_hashtag=city_hashtag,
        city_story_hashtag=city_story_hashtag,
        used_hashtags=tuple(used_hashtags),
        used_local_mentions=tuple(used_local_mentions),
        caption_hook=caption_hook,
        caption_question=caption_question,
    )


def build_caption_hook(city: str, story_text: str, local_place: str) -> str:
    first_sentence = first_story_sentence(story_text)
    hook = remove_city_prefix(first_sentence, city)
    hook = shorten(hook, 96)
    if local_place and local_place.casefold() not in hook.casefold():
        hook = f"{local_place}: {hook}"
    return f"{city}: {hook} Fiktive KI-Story."


def build_caption_question(city: str, local_place: str, episode_number: int) -> str:
    index = episode_number % len(QUESTION_TEMPLATES)
    other_city = next((candidate for candidate in CITY_CHOICES if candidate.casefold() != city.casefold()), "Nürnberg")
    place = f"am {local_place}" if local_place else f"in {city}"
    return QUESTION_TEMPLATES[index].format(city=city, other_city=other_city, place=place)


def first_story_sentence(story_text: str) -> str:
    cleaned = re.sub(r"\s+", " ", story_text).strip()
    match = re.search(r"^(.+?[.!?])(?:\s|$)", cleaned)
    return match.group(1).strip() if match else shorten(cleaned, 110)


def extract_local_place(story_text: str, city: str) -> str:
    candidates = re.findall(
        r"\b(?:am|an der|an den|auf dem|auf der|im|in der|beim|zum|zur)\s+([A-ZÄÖÜ][\wäöüÄÖÜß-]+(?:\s+[A-ZÄÖÜ][\wäöüÄÖÜß-]+){0,4})",
        story_text,
    )
    ignored = {city.casefold(), "Bruder".casefold(), "Bro".casefold(), "Digga".casefold()}
    for candidate in candidates:
        cleaned = candidate.strip(" .,!?;:")
        if cleaned and cleaned.casefold() not in ignored and len(cleaned) >= 4:
            return cleaned
    return ""


def select_optional_hashtags(story_text: str) -> list[str]:
    lowered = story_text.lower()
    tags = ["#FiktiveStory", "#KIStory"]
    if any(word in lowered for word in ["stimme", "schatten", "plötzlich", "ploetzlich", "angst"]):
        tags = ["#MysteryStory", "#FiktiveStory"]
    elif any(word in lowered for word in ["bruder", "digga", "bro"]):
        tags = ["#StorytimeDeutsch", "#KIStory"]
    return tags[:2]


def state_for_city(city: str) -> str:
    return STATE_BY_CITY.get(city, "Deutschland")


def hashtag_slug(value: str) -> str:
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return re.sub(r"[^A-Za-z0-9]", "", value)


def shorten(value: str, max_length: int) -> str:
    value = value.strip()
    if len(value) <= max_length:
        return value
    shortened = value[: max_length - 1].rsplit(" ", 1)[0].rstrip(" .,;:")
    return shortened + "."


def remove_city_prefix(value: str, city: str) -> str:
    return re.sub(rf"^\s*{re.escape(city)}\s*[:,\-]\s*", "", value, flags=re.IGNORECASE).strip()


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
    for value in matching[:2]:
        handle = str(value).strip()
        if handle:
            mentions.append(handle if handle.startswith("@") else f"@{handle}")
    return mentions

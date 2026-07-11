from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path

from moviepy.editor import VideoFileClip

from config import settings
from file_manager import RunPaths
from story_metadata import StoryMetadata, save_metadata


POSTING_SLOTS = [
    ("Montag", 0, time(20, 0), "mo_2000"),
    ("Dienstag", 1, time(20, 30), "optional_di_2030"),
    ("Mittwoch", 2, time(21, 30), "mi_2130"),
    ("Donnerstag", 3, time(20, 30), "optional_do_2030"),
    ("Freitag", 4, time(18, 30), "fr_1830"),
    ("Samstag", 5, time(17, 0), "sa_1700"),
    ("Sonntag", 6, time(9, 0), "so_0900"),
    ("Sonntag", 6, time(13, 0), "so_1300"),
]

CORE_SLOT_KEYS = {"mo_2000", "mi_2130", "fr_1830", "sa_1700", "so_0900", "so_1300"}
BLOCKED_HASHTAGS = {"#viral", "#fyp", "#fürdich", "#fuerdich"}

STATE_BY_CITY = {
    "Augsburg": "Bayern",
    "Duisburg": "NordrheinWestfalen",
    "Erlangen": "Bayern",
    "Freising": "Bayern",
    "München": "Bayern",
    "Nuernberg": "Bayern",
    "Nürnberg": "Bayern",
    "Petershausen bei Jetzendorf": "Bayern",
    "Regensburg": "Bayern",
}

HOOK_CATEGORIES = [
    ("Nachricht", ["nachricht", "handy", "sms", "chat", "vibrierte"]),
    ("Anruf", ["anruf", "klingelte", "telefon"]),
    ("Bahnhof/Unterführung", ["bahnhof", "unterführung", "unterfuehrung", "gleis", "bahnsteig"]),
    ("Tür/Treppenhaus", ["tür", "tuer", "treppenhaus", "klingel", "haustür", "haustuer"]),
    ("fremdes Auto", ["auto", "kennzeichen", "wagen", "scheinwerfer"]),
    ("Verfolger", ["verfolg", "rannte", "lief hinter", "schritte"]),
    ("Doppelgänger", ["doppelgänger", "doppelgaenger", "sah aus wie ich"]),
    ("verlorener Gegenstand", ["schlüssel", "schluessel", "tasche", "handy lag", "gefunden"]),
    ("Warnung", ["warnung", "geh nicht", "bleib weg", "polizei"]),
    ("unmögliche Situation", ["plötzlich", "ploetzlich", "auf einmal", "stand da", "ich schwöre", "ich schwoere"]),
]


def create_or_update_posting_plan(
    run_paths: RunPaths,
    metadata: StoryMetadata,
    story_text: str,
    overwrite: bool = False,
) -> StoryMetadata:
    if run_paths.posting_plan.exists() and not overwrite:
        update_weekly_posting_plan(run_paths.weekly_posting_plan, run_paths.root.parent)
        return metadata

    quality_score, warnings, video_length = evaluate_quality(run_paths, metadata, story_text)
    hook_text = first_story_sentence(story_text)
    hook_category = detect_hook_category(story_text)
    existing_plans = load_existing_plans(run_paths.root.parent, exclude=run_paths.root)
    slot = choose_posting_slot(existing_plans, metadata.city, hook_category)
    caption_text = run_paths.caption.read_text(encoding="utf-8") if run_paths.caption.exists() else ""
    hashtags = extract_hashtags(caption_text)
    status = status_for_run(quality_score, run_paths.final_video.exists())
    plan = {
        "episode_number": metadata.episode_number,
        "city": metadata.city,
        "recommended_post_date": slot["date"],
        "recommended_post_time": slot["time"],
        "weekday": slot["weekday"],
        "posting_slot": slot["slot"],
        "video_length_seconds": round(video_length, 2),
        "quality_score": quality_score,
        "quality_warnings": warnings,
        "hook_text": hook_text,
        "hook_category": hook_category,
        "caption_text": caption_text,
        "hashtags": hashtags,
        "is_ready_for_tiktok_draft_upload": quality_score >= 60,
        "status": status,
    }
    run_paths.posting_plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    update_weekly_posting_plan(run_paths.weekly_posting_plan, run_paths.root.parent)
    metadata = replace(metadata, hook_category=hook_category)
    save_metadata(run_paths.metadata, metadata)
    return metadata


def evaluate_quality(run_paths: RunPaths, metadata: StoryMetadata, story_text: str) -> tuple[int, list[str], float]:
    warnings: list[str] = []
    score = 100
    story_text = story_text.strip()

    def penalize(condition: bool, points: int, message: str) -> None:
        nonlocal score
        if condition:
            score -= points
            warnings.append(message)

    penalize(not story_text, 25, "Storytext ist leer.")
    penalize(not (settings.story_min_chars <= len(story_text) <= settings.story_max_chars), 12, f"Storylaenge ist {len(story_text)} Zeichen.")
    penalize(is_generic_hook(first_story_sentence(story_text)), 10, "Hook wirkt zu allgemein.")
    penalize(not metadata.city or metadata.city == "deutschen Städten", 15, "Stadt ist nicht sauber gesetzt.")
    local_places = extract_local_places(story_text, metadata.city)
    penalize(len(local_places) < 2, 8, "Weniger als 2 lokale Orte oder Strassen erkannt.")
    image_count = count_images(run_paths.images)
    penalize(image_count != settings.total_image_count, 15, f"Erwartet 8 Bilder, gefunden: {image_count}.")
    penalize(not run_paths.story_voiceover.exists(), 10, "Story-Voiceover fehlt.")
    penalize(not run_paths.subtitles_srt.exists(), 8, "Untertitel-Datei fehlt.")
    penalize(not run_paths.final_video.exists(), 15, "Finale MP4 fehlt.")
    penalize(not run_paths.caption.exists(), 8, "caption.txt fehlt.")

    caption = run_paths.caption.read_text(encoding="utf-8") if run_paths.caption.exists() else ""
    caption_lower = caption.lower()
    penalize(metadata.city.casefold() not in caption.casefold(), 8, "Caption enthaelt den Stadtnamen nicht.")
    penalize("fiktive ki-story" not in caption_lower, 8, "Caption enthaelt keinen Hinweis auf fiktive KI-Story.")
    penalize(any(tag in caption_lower for tag in BLOCKED_HASHTAGS), 8, "Caption enthaelt gesperrte generische Hashtags.")

    video_length = video_duration(run_paths.final_video)
    penalize(video_length <= 0, 10, "Videolaenge konnte nicht gelesen werden.")
    penalize(video_length > 0 and not (40 <= video_length <= 75), 10, f"Videolaenge ist {video_length:.1f}s.")
    anchor_warnings = image_prompt_warnings(run_paths.image_prompts)
    for warning in anchor_warnings:
        penalize(True, 7, warning)

    return max(0, min(100, score)), warnings, video_length


def choose_posting_slot(existing_plans: list[dict], city: str, hook_category: str) -> dict:
    now = datetime.now()
    existing_keys = {(plan.get("recommended_post_date"), plan.get("posting_slot")) for plan in existing_plans}
    city_recent = [plan.get("city", "") for plan in existing_plans[-3:]]
    category_recent = [plan.get("hook_category", "") for plan in existing_plans[-3:]]
    state_recent = [state_for_city(plan.get("city", "")) for plan in existing_plans[-3:]]
    city_state = state_for_city(city)

    for week_offset in range(0, 8):
        monday = (now.date() - timedelta(days=now.weekday())) + timedelta(days=7 * week_offset)
        week_plans = [
            plan for plan in existing_plans
            if parse_date(plan.get("recommended_post_date", "")) and parse_date(plan.get("recommended_post_date", "")).isocalendar()[:2] == monday.isocalendar()[:2]
        ]
        use_optional = len(week_plans) >= 5
        for weekday, weekday_index, slot_time, key in POSTING_SLOTS:
            if key not in CORE_SLOT_KEYS and not use_optional:
                continue
            candidate_date = monday + timedelta(days=weekday_index)
            candidate_dt = datetime.combine(candidate_date, slot_time)
            if candidate_dt <= now + timedelta(hours=2):
                continue
            if (candidate_date.isoformat(), key) in existing_keys:
                continue
            if len(week_plans) >= 6:
                break
            if city in city_recent:
                continue
            if hook_category in category_recent and len(category_recent) >= 2:
                continue
            if city_state and state_recent.count(city_state) >= 2:
                continue
            return {
                "date": candidate_date.isoformat(),
                "time": slot_time.strftime("%H:%M"),
                "weekday": weekday,
                "slot": key,
            }

    fallback_date = now.date() + timedelta(days=1)
    return {"date": fallback_date.isoformat(), "time": "20:30", "weekday": weekday_name(fallback_date), "slot": "fallback_2030"}


def update_weekly_posting_plan(path: Path, output_dir: Path) -> None:
    plans = load_existing_plans(output_dir)
    today = date.today()
    current_week = today.isocalendar()[:2]
    weekly = []
    for plan in plans:
        plan_date = parse_date(plan.get("recommended_post_date", ""))
        if not plan_date or plan_date.isocalendar()[:2] != current_week:
            continue
        weekly.append(
            {
                "datum": plan.get("recommended_post_date"),
                "uhrzeit": plan.get("recommended_post_time"),
                "folge": plan.get("episode_number"),
                "stadt": plan.get("city"),
                "hook_category": plan.get("hook_category"),
                "quality_score": plan.get("quality_score"),
                "status": plan.get("status"),
            }
        )
    weekly.sort(key=lambda item: (item["datum"] or "", item["uhrzeit"] or ""))
    path.write_text(json.dumps(weekly, ensure_ascii=False, indent=2), encoding="utf-8")


def load_existing_plans(output_dir: Path, exclude: Path | None = None) -> list[dict]:
    plans: list[dict] = []
    for path in sorted(output_dir.glob("*/posting_plan.json")):
        if exclude and path.parent == exclude:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            plans.append(data)
    plans.sort(key=lambda plan: (plan.get("recommended_post_date", ""), plan.get("recommended_post_time", "")))
    return plans


def image_prompt_warnings(path: Path) -> list[str]:
    if not path.exists():
        return ["image_prompts.json fehlt."]
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["image_prompts.json ist kein valides JSON."]
    if not isinstance(plan, list) or len(plan) != settings.total_image_count:
        return ["Bildplan hat nicht genau 8 Objekte."]
    anchors = [str(item.get("start_text", "")).strip() for item in plan[1:] if isinstance(item, dict)]
    warnings = []
    if any(not anchor for anchor in anchors):
        warnings.append("Mindestens ein start_text-Anker fehlt.")
    if len(set(anchor.casefold() for anchor in anchors)) != len(anchors):
        warnings.append("Doppelte start_text-Anker erkannt.")
    return warnings


def extract_local_places(story_text: str, city: str) -> list[str]:
    candidates = re.findall(
        r"\b(?:am|an der|an den|auf dem|auf der|im|in der|beim|zum|zur)\s+([A-ZÄÖÜ][\wäöüÄÖÜß-]+(?:\s+[A-ZÄÖÜ][\wäöüÄÖÜß-]+){0,4})",
        story_text,
    )
    places: list[str] = []
    ignored = {city.casefold(), "Bruder".casefold(), "Bro".casefold(), "Digga".casefold()}
    for candidate in candidates:
        cleaned = candidate.strip(" .,!?;:")
        if cleaned.casefold() not in ignored and cleaned not in places:
            places.append(cleaned)
    return places


def detect_hook_category(story_text: str) -> str:
    lowered = story_text.lower()
    for category, keywords in HOOK_CATEGORIES:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "unmögliche Situation"


def first_story_sentence(story_text: str) -> str:
    cleaned = re.sub(r"\s+", " ", story_text).strip()
    match = re.search(r"^(.+?[.!?])(?:\s|$)", cleaned)
    return match.group(1).strip() if match else cleaned[:120].strip()


def is_generic_hook(hook: str) -> bool:
    lowered = hook.lower()
    generic = ["es war eine nacht", "manchmal reicht", "ich war unterwegs", "alles fing an"]
    return len(hook) < 35 or any(value in lowered for value in generic)


def count_images(images_dir: Path) -> int:
    return len([path for path in images_dir.glob("image_*.*") if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}])


def video_duration(path: Path) -> float:
    if not path.exists():
        return 0.0
    try:
        with VideoFileClip(str(path)) as video:
            return float(video.duration)
    except Exception:
        return 0.0


def extract_hashtags(caption: str) -> list[str]:
    return re.findall(r"#[\wÄÖÜäöüß]+", caption, flags=re.UNICODE)


def status_for_run(quality_score: int, has_video: bool) -> str:
    if quality_score < 60:
        return "blocked_quality_score"
    if not has_video:
        return "generated"
    if quality_score < 75:
        return "needs_manual_check"
    return "ready_for_review"


def state_for_city(city: str) -> str:
    return STATE_BY_CITY.get(city, "")


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def weekday_name(value: date) -> str:
    return ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][value.weekday()]

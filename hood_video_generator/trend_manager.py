from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from file_manager import RunPaths
from story_metadata import StoryMetadata, save_metadata


DEFAULT_CONFIG = {
    "trend_experiments_enabled": True,
    "trend_experiment_ratio": 0.2,
    "allowed_trend_types": [
        "subtitle_style",
        "intro_overlay",
        "transition_style",
        "sound_style",
        "comment_reply_style",
        "search_hook_style",
    ],
    "blocked_trend_types": [
        "dangerous_challenges",
        "real_crime_claims",
        "political_ragebait",
        "fake_news",
        "harassment",
        "minor_related_content",
    ],
    "active_trends": [],
}

SAFE_COMPONENTS = {
    "subtitle_style": ["subtitles"],
    "intro_overlay": ["series_overlay"],
    "transition_style": ["visual_transitions"],
    "sound_style": ["local_sound_design"],
    "comment_reply_style": ["caption", "story_hook_note"],
    "search_hook_style": ["caption", "hook_positioning_note"],
}

KEYWORD_BY_APPLIES_TO = {
    "mystery": ["stimme", "schatten", "plötzlich", "stand da", "offen"],
    "message": ["nachricht", "handy", "whatsapp", "nummer", "display"],
    "doppelgaenger": ["doppelgänger", "doppelgaenger", "sah aus wie ich"],
    "car": ["auto", "kennzeichen", "wagen"],
    "station": ["bahnhof", "unterführung", "unterfuehrung", "gleis"],
}


def apply_trend_experiment(run_paths: RunPaths, metadata: StoryMetadata, story_text: str, overwrite: bool = False) -> StoryMetadata:
    if run_paths.trend_usage.exists() and not overwrite:
        existing = json.loads(run_paths.trend_usage.read_text(encoding="utf-8"))
        return replace(
            metadata,
            is_trend_experiment=bool(existing.get("trend_experiment_applied", False)),
            trend_id=str(existing.get("trend_id", "")),
            trend_type=str(existing.get("trend_type", "")),
            trend_name=str(existing.get("trend_name", "")),
        )

    config = load_trend_config(run_paths.trend_config)
    usage = select_trend(config, run_paths, story_text)
    run_paths.trend_usage.write_text(json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata = replace(
        metadata,
        is_trend_experiment=bool(usage["trend_experiment_applied"]),
        trend_id=str(usage.get("trend_id", "")),
        trend_type=str(usage.get("trend_type", "")),
        trend_name=str(usage.get("trend_name", "")),
    )
    save_metadata(run_paths.metadata, metadata)
    return metadata


def load_trend_config(path: Path) -> dict:
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def select_trend(config: dict, run_paths: RunPaths, story_text: str) -> dict:
    now = datetime.now()
    base_usage = {
        "trend_experiment_applied": False,
        "trend_id": "",
        "trend_type": "",
        "trend_name": "",
        "reason_for_selection": "",
        "affected_components": [],
        "risk_level": "",
        "expires_at": "",
        "applied_at": now.isoformat(timespec="seconds"),
        "skipped_reason": "",
    }
    if not bool(config.get("trend_experiments_enabled", True)):
        return {**base_usage, "skipped_reason": "trend experiments disabled"}

    active = [trend for trend in config.get("active_trends", []) if isinstance(trend, dict) and trend.get("enabled", True)]
    if not active:
        return {**base_usage, "skipped_reason": "no active trends configured"}

    existing = load_week_trend_usages(run_paths.root.parent)
    max_allowed = weekly_trend_limit(len(existing) + 1, float(config.get("trend_experiment_ratio", 0.2)))
    current_trends = sum(1 for usage in existing if usage.get("trend_experiment_applied"))
    if current_trends >= max_allowed:
        return {**base_usage, "skipped_reason": f"weekly trend ratio reached ({current_trends}/{max_allowed})"}

    allowed_types = set(config.get("allowed_trend_types", []))
    blocked_types = set(config.get("blocked_trend_types", []))
    for trend in active:
        trend_type = str(trend.get("trend_type", ""))
        trend_id = str(trend.get("trend_id", ""))
        if trend_type in blocked_types:
            continue
        if trend_type not in allowed_types:
            continue
        expires_at = str(trend.get("expires_at", ""))
        if is_expired(expires_at, now.date()):
            continue
        if str(trend.get("risk_level", "low")).lower() not in {"low", "medium"}:
            continue
        if uses_this_week(existing, trend_id) >= int(trend.get("max_uses_per_week", 1)):
            continue
        if not trend_matches_story(trend, story_text):
            continue
        return {
            **base_usage,
            "trend_experiment_applied": True,
            "trend_id": trend_id,
            "trend_type": trend_type,
            "trend_name": str(trend.get("name", "")),
            "reason_for_selection": "safe active trend fits story and weekly 80/20 ratio",
            "affected_components": SAFE_COMPONENTS.get(trend_type, []),
            "risk_level": str(trend.get("risk_level", "low")),
            "expires_at": expires_at,
            "skipped_reason": "",
        }

    return {**base_usage, "skipped_reason": "no suitable safe trend matched this story"}


def weekly_trend_limit(total_videos_this_week: int, ratio: float) -> int:
    if total_videos_this_week <= 0:
        return 0
    return max(1, math.ceil(total_videos_this_week * ratio))


def load_week_trend_usages(output_dir: Path) -> list[dict]:
    current_week = date.today().isocalendar()[:2]
    usages: list[dict] = []
    for path in sorted(output_dir.glob("*/trend_usage.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        applied_at = parse_date(str(data.get("applied_at", "")))
        if applied_at and applied_at.isocalendar()[:2] == current_week:
            usages.append(data)
    return usages


def uses_this_week(existing_usages: list[dict], trend_id: str) -> int:
    return sum(1 for usage in existing_usages if usage.get("trend_id") == trend_id and usage.get("trend_experiment_applied"))


def trend_matches_story(trend: dict, story_text: str) -> bool:
    applies_to = trend.get("applies_to", [])
    if not applies_to:
        return True
    story_lower = story_text.lower()
    for key in applies_to:
        keywords = KEYWORD_BY_APPLIES_TO.get(str(key).lower(), [str(key).lower()])
        if any(keyword in story_lower for keyword in keywords):
            return True
    return False


def is_expired(expires_at: str, today: date) -> bool:
    parsed = parse_date(expires_at)
    return bool(parsed and parsed < today)


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
COLUMNS = [
    "run_id", "episode_number", "city", "bundesland", "created_at",
    "planned_post_date", "planned_post_time", "actual_post_date", "actual_post_time",
    "video_length_seconds", "story_length_chars", "hook_text", "hook_category", "story_type",
    "local_places_used", "caption_text", "hashtags", "subtitle_mode", "visual_style_version",
    "sound_design_version", "trend_experiment_applied", "trend_id", "quality_score",
    "final_video_path", "manual_upload_status", "tiktok_url", "views_2h", "views_24h",
    "views_7d", "likes_24h", "comments_24h", "shares_24h", "saves_24h",
    "average_watch_time_seconds", "watched_full_video_percent", "profile_views", "new_followers", "notes",
]


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for name in ["manual_metrics_template.csv", "manual_metrics.csv"]:
        path = DATA / name
        if not path.exists():
            with path.open("w", newline="", encoding="utf-8") as file:
                csv.DictWriter(file, fieldnames=COLUMNS).writeheader()
            print(f"created {path}")


if __name__ == "__main__":
    main()

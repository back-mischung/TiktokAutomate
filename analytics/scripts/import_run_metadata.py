from __future__ import annotations

import csv
import json
from pathlib import Path

from create_manual_metrics_template import COLUMNS


ROOT = Path(__file__).resolve().parents[2]
ANALYTICS = ROOT / "analytics"
METRICS_PATH = ANALYTICS / "data" / "manual_metrics.csv"
OUTPUT_DIR = ROOT / "hood_video_generator" / "output"


def main() -> None:
    ensure_metrics_file()
    rows = read_rows()
    existing = {row["run_id"] for row in rows if row.get("run_id")}
    added = 0
    for metadata_path in sorted(OUTPUT_DIR.glob("*/metadata.json")):
        run_id = metadata_path.parent.name
        if run_id in existing:
            continue
        data = load_json(metadata_path)
        if not data:
            continue
        plan = load_json(metadata_path.parent / "posting_plan.json")
        row = {key: "" for key in COLUMNS}
        row.update(
            {
                "run_id": run_id,
                "episode_number": data.get("episode_number", ""),
                "city": data.get("city", ""),
                "bundesland": data.get("bundesland", ""),
                "created_at": data.get("created_at", ""),
                "planned_post_date": data.get("planned_post_date") or plan.get("recommended_post_date", ""),
                "planned_post_time": data.get("planned_post_time") or plan.get("recommended_post_time", ""),
                "video_length_seconds": data.get("video_length_seconds") or plan.get("video_length_seconds", ""),
                "story_length_chars": data.get("story_length_chars", ""),
                "hook_text": data.get("hook_text") or plan.get("hook_text", ""),
                "hook_category": data.get("hook_category") or plan.get("hook_category", ""),
                "story_type": data.get("story_type") or data.get("hook_category", ""),
                "local_places_used": join_values(data.get("local_places_used", [])),
                "subtitle_mode": data.get("subtitle_mode", ""),
                "visual_style_version": data.get("visual_style_version", ""),
                "sound_design_version": data.get("sound_design_version", ""),
                "trend_experiment_applied": data.get("trend_experiment_applied", data.get("is_trend_experiment", "")),
                "trend_id": data.get("trend_id", ""),
                "quality_score": data.get("quality_score") or plan.get("quality_score", ""),
                "caption_text": data.get("caption_text", ""),
                "hashtags": join_values(data.get("hashtags") or plan.get("hashtags", [])),
                "final_video_path": data.get("final_video_path", ""),
                "manual_upload_status": data.get("manual_upload_status", ""),
            }
        )
        rows.append(row)
        added += 1
    write_rows(rows)
    print(f"Imported {added} new runs into {METRICS_PATH}")


def ensure_metrics_file() -> None:
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not METRICS_PATH.exists():
        with METRICS_PATH.open("w", newline="", encoding="utf-8") as file:
            csv.DictWriter(file, fieldnames=COLUMNS).writeheader()


def read_rows() -> list[dict]:
    with METRICS_PATH.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_rows(rows: list[dict]) -> None:
    with METRICS_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in COLUMNS})


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def join_values(values: object) -> str:
    if isinstance(values, list):
        return " ".join(str(value) for value in values if value)
    if isinstance(values, tuple):
        return " ".join(str(value) for value in values if value)
    return str(values or "")


if __name__ == "__main__":
    main()

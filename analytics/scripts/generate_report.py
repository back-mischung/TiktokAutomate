from __future__ import annotations

import csv
import html
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
METRICS_PATH = DATA / "manual_metrics.csv"


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    enriched = enrich_rows(rows)
    summary = build_summary(enriched)
    reports = {
        "weekly_report": {"summary": summary, "videos": enriched, "recommendations": recommendations(enriched)},
        "best_hooks": group_performance(enriched, "hook_category"),
        "city_performance": group_performance(enriched, "city", secondary="bundesland"),
        "posting_time_performance": group_performance(enriched, "posting_bucket"),
        "video_length_performance": group_performance(enriched, "length_bucket"),
        "story_type_performance": group_performance(enriched, "story_type"),
        "subtitle_performance": group_performance(enriched, "subtitle_mode"),
        "sound_performance": group_performance(enriched, "sound_design_version"),
        "trend_performance": group_performance(enriched, "trend_experiment_applied"),
    }
    for name, data in reports.items():
        (REPORTS / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPORTS / "weekly_report.html").write_text(render_html(summary, enriched, reports), encoding="utf-8")
    print(f"Report written to {REPORTS / 'weekly_report.html'}")


def load_rows() -> list[dict]:
    if not METRICS_PATH.exists():
        return []
    with METRICS_PATH.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def enrich_rows(rows: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    previous: list[dict] = []
    for row in rows:
        item = dict(row)
        item["weekday"] = weekday(item.get("actual_post_date") or item.get("planned_post_date"))
        item["hour"] = hour(item.get("actual_post_time") or item.get("planned_post_time"))
        item["posting_bucket"] = posting_bucket(item["hour"])
        item["length_bucket"] = length_bucket(num(item.get("video_length_seconds")))
        item["hashtag_count"] = str((item.get("caption_text") or "").count("#"))
        views = num(item.get("views_24h"))
        likes = num(item.get("likes_24h"))
        comments = num(item.get("comments_24h"))
        shares = num(item.get("shares_24h"))
        saves = num(item.get("saves_24h"))
        followers = num(item.get("new_followers"))
        completion = num(item.get("watched_full_video_percent"))
        item["engagement_rate"] = rate(sum_values(likes, comments, shares, saves), views)
        item["share_rate"] = rate(shares, views)
        item["comment_rate"] = rate(comments, views)
        item["save_rate"] = rate(saves, views)
        item["follower_conversion_rate"] = rate(followers, views)
        score, partial = performance_score(views, shares, comments, completion, followers)
        item["performance_score"] = score
        item["performance_score_partial"] = partial
        med = medians(previous[-10:])
        comparisons = {
            "views_vs_last10_median": compare(views, med.get("views_24h")),
            "share_rate_vs_last10_median": compare(float_or_none(item["share_rate"]), med.get("share_rate")),
            "completion_vs_last10_median": compare(completion, med.get("watched_full_video_percent")),
            "follower_conversion_vs_last10_median": compare(float_or_none(item["follower_conversion_rate"]), med.get("follower_conversion_rate")),
        }
        item.update(comparisons)
        item["is_winner"] = sum(1 for value in comparisons.values() if value == "above") >= 3
        item["analytics_status"] = analytics_status(item)
        enriched.append(item)
        previous.append(item)
    return enriched


def performance_score(
    views: float | None,
    shares: float | None,
    comments: float | None,
    completion: float | None,
    followers: float | None,
) -> tuple[float, bool]:
    parts: list[tuple[float, float]] = []
    if views is not None:
        parts.append((min(1.0, views / 5000), 25))
    if views and shares is not None:
        parts.append((min(1.0, (shares / views) / 0.03), 25))
    if completion is not None:
        parts.append((min(1.0, completion / 70), 25))
    if views and followers is not None:
        parts.append((min(1.0, (followers / views) / 0.01), 15))
    if views and comments is not None:
        parts.append((min(1.0, (comments / views) / 0.02), 10))
    if not parts:
        return 0.0, True
    weight = sum(part[1] for part in parts)
    return round(sum(value * points for value, points in parts) / weight * 100, 2), weight < 100


def build_summary(rows: list[dict]) -> dict:
    completed = [row for row in rows if num(row.get("views_24h"))]
    return {
        "video_count": len(rows),
        "videos_with_metrics": len(completed),
        "avg_views_24h": avg([num(row.get("views_24h")) for row in completed]),
        "avg_engagement_rate": avg([float_or_none(row.get("engagement_rate")) for row in completed]),
        "avg_share_rate": avg([float_or_none(row.get("share_rate")) for row in completed]),
        "avg_completion_rate": avg([num(row.get("watched_full_video_percent")) for row in completed]),
        "new_followers_total": sum(num(row.get("new_followers")) or 0 for row in completed),
        "data_note": data_note(len(completed)),
    }


def group_performance(rows: list[dict], key: str, secondary: str | None = None) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        group_key = row.get(key) or "nicht eingetragen"
        if secondary:
            group_key = f"{group_key} / {row.get(secondary) or 'unbekannt'}"
        groups[str(group_key)].append(row)
    result = []
    for name, items in groups.items():
        best = max(items, key=lambda row: float(row.get("performance_score") or 0), default={})
        result.append(
            {
                "group": name,
                "count": len(items),
                "avg_views_24h": avg([num(item.get("views_24h")) for item in items]),
                "avg_comments_24h": avg([num(item.get("comments_24h")) for item in items]),
                "avg_shares_24h": avg([num(item.get("shares_24h")) for item in items]),
                "avg_new_followers": avg([num(item.get("new_followers")) for item in items]),
                "best_run": best.get("run_id", ""),
            }
        )
    return sorted(result, key=lambda item: item["avg_views_24h"] or 0, reverse=True)


def recommendations(rows: list[dict]) -> list[str]:
    recs = []
    hooks = group_performance(rows, "hook_category")
    lengths = group_performance(rows, "length_bucket")
    times = group_performance(rows, "posting_bucket")
    subtitles = group_performance(rows, "subtitle_mode")
    sounds = group_performance(rows, "sound_design_version")
    if hooks:
        recs.append(f"Mehr Videos mit Hook-Kategorie {hooks[0]['group']} testen.")
    if lengths:
        recs.append(f"Videos im Bereich {lengths[0]['group']} weiter beobachten.")
    if times:
        recs.append(f"Posting-Zeit {times[0]['group']} hatte bisher die besten Tendenzen.")
    if subtitles:
        recs.append(f"Untertitelmodus {subtitles[0]['group']} weiter testen.")
    if sounds:
        recs.append(f"Sounddesign {sounds[0]['group']} als Vergleichswert behalten.")
    if len([row for row in rows if num(row.get("views_24h"))]) < 30:
        recs.append("Fuer stabile Muster mindestens 30 Videos sammeln.")
    return recs


def render_html(summary: dict, rows: list[dict], reports: dict) -> str:
    top = sorted(rows, key=lambda row: float(row.get("performance_score") or 0), reverse=True)[:5]
    flop = sorted([row for row in rows if num(row.get("views_24h")) is not None], key=lambda row: float(row.get("performance_score") or 0))[:5]
    sections = [
        table("Top 5 Videos", top, ["episode_number", "city", "hook_text", "actual_post_time", "views_24h", "likes_24h", "comments_24h", "shares_24h", "watched_full_video_percent", "new_followers", "performance_score"]),
        table("Flop 5 Videos", flop, ["episode_number", "city", "hook_text", "views_24h", "performance_score", "analytics_status"]),
        group_table("Hook-Auswertung", reports["best_hooks"]),
        group_table("Stadt-Auswertung", reports["city_performance"]),
        group_table("Postingzeit-Auswertung", reports["posting_time_performance"]),
        group_table("Videolaengen-Auswertung", reports["video_length_performance"]),
        group_table("Storytyp-Auswertung", reports["story_type_performance"]),
        group_table("Untertitel-Auswertung", reports["subtitle_performance"]),
        group_table("Sound-Auswertung", reports["sound_performance"]),
        group_table("Trend-Auswertung", reports["trend_performance"]),
    ]
    rec_items = "".join(f"<li>{html.escape(item)}</li>" for item in reports["weekly_report"]["recommendations"])
    return f"""<!doctype html>
<html lang="de"><meta charset="utf-8"><title>Hood Story Analytics</title>
<style>body{{font-family:Arial,sans-serif;margin:32px;background:#111;color:#eee}}table{{border-collapse:collapse;width:100%;margin:16px 0}}td,th{{border:1px solid #333;padding:8px;text-align:left}}th{{background:#222}}.card{{background:#181818;padding:16px;border-radius:8px;margin:12px 0}}small{{color:#aaa}}</style>
<h1>Weekly Analytics Report</h1>
<div class="card">
<b>Videos:</b> {summary['video_count']} | <b>mit Metriken:</b> {summary['videos_with_metrics']} |
<b>Avg Views 24h:</b> {summary['avg_views_24h']} | <b>Avg Engagement:</b> {summary['avg_engagement_rate']} |
<b>Avg Shares:</b> {summary['avg_share_rate']} | <b>Follower neu:</b> {summary['new_followers_total']}<br>
<small>{html.escape(summary['data_note'])}</small>
</div>
{''.join(sections)}
<h2>Empfehlungen</h2><ul>{rec_items}</ul>
</html>"""


def table(title: str, rows: list[dict], columns: list[str]) -> str:
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(row.get(col, '')))}</td>" for col in columns) + "</tr>" for row in rows)
    head = "".join(f"<th>{html.escape(col)}</th>" for col in columns)
    return f"<h2>{html.escape(title)}</h2><table><tr>{head}</tr>{body}</table>"


def group_table(title: str, rows: list[dict]) -> str:
    return table(title, rows, ["group", "count", "avg_views_24h", "avg_comments_24h", "avg_shares_24h", "avg_new_followers", "best_run"])


def medians(rows: list[dict]) -> dict:
    return {
        "views_24h": median([num(row.get("views_24h")) for row in rows]),
        "share_rate": median([float_or_none(row.get("share_rate")) for row in rows]),
        "watched_full_video_percent": median([num(row.get("watched_full_video_percent")) for row in rows]),
        "follower_conversion_rate": median([float_or_none(row.get("follower_conversion_rate")) for row in rows]),
    }


def analytics_status(row: dict) -> str:
    if not row.get("tiktok_url") and not row.get("views_24h"):
        return "metrics_missing"
    required = ["views_24h", "likes_24h", "comments_24h", "shares_24h", "saves_24h", "watched_full_video_percent"]
    if all(row.get(field) for field in required):
        return "metrics_complete"
    if row.get("tiktok_url") and not row.get("views_24h"):
        return "manually_uploaded"
    return "metrics_partial"


def data_note(count: int) -> str:
    if count < 10:
        return "Noch wenig Daten. Empfehlungen sind nur erste Tendenzen. Fuer stabile Muster mindestens 30 Videos sammeln."
    if count < 30:
        return "Fuer stabile Muster mindestens 30 Videos sammeln."
    return "Datenbasis ist ausreichend fuer erste stabile Muster."


def weekday(value: str | None) -> str:
    if not value:
        return ""
    try:
        return ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][datetime.fromisoformat(value).weekday()]
    except ValueError:
        return ""


def hour(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.split(":", 1)[0])
    except (ValueError, IndexError):
        return None


def posting_bucket(hour_value: int | None) -> str:
    if hour_value is None:
        return "nicht eingetragen"
    if 5 <= hour_value < 11:
        return "Morgen"
    if 11 <= hour_value < 16:
        return "Mittag"
    if 16 <= hour_value < 23:
        return "Abend"
    return "Nacht"


def length_bucket(seconds: float | None) -> str:
    if seconds is None:
        return "nicht eingetragen"
    if seconds < 45:
        return "unter 45 Sekunden"
    if seconds <= 55:
        return "45 bis 55 Sekunden"
    if seconds <= 70:
        return "56 bis 70 Sekunden"
    return "ueber 70 Sekunden"


def rate(value: float | None, base: float | None) -> str:
    if value is None or not base:
        return ""
    return str(round(value / base, 4))


def compare(value: float | None, baseline: float | None) -> str:
    if value is None or baseline is None:
        return ""
    return "above" if value > baseline else "below_or_equal"


def sum_values(*values: float | None) -> float:
    return sum(value or 0 for value in values)


def num(value: str | float | int | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def float_or_none(value: str | float | int | None) -> float | None:
    return num(value)


def avg(values: list[float | None]) -> float:
    clean = [value for value in values if value is not None]
    return round(sum(clean) / len(clean), 4) if clean else 0


def median(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return statistics.median(clean) if clean else None


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from create_manual_metrics_template import COLUMNS


ROOT = Path(__file__).resolve().parents[1]
METRICS_PATH = ROOT / "data" / "manual_metrics.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Manuelle TikTok-Metriken in manual_metrics.csv eintragen")
    parser.add_argument("--run_id", required=True)
    for field in COLUMNS:
        if field != "run_id":
            parser.add_argument(f"--{field}")
    args = parser.parse_args()
    rows = read_rows()
    for row in rows:
        if row.get("run_id") == args.run_id:
            for field in COLUMNS:
                value = getattr(args, field, None)
                if value is not None:
                    row[field] = value
            write_rows(rows)
            print(f"updated {args.run_id}")
            return
    row = {key: "" for key in COLUMNS}
    for field in COLUMNS:
        value = getattr(args, field, None)
        if value is not None:
            row[field] = value
    rows.append(row)
    write_rows(rows)
    print(f"added {args.run_id}")


def read_rows() -> list[dict]:
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not METRICS_PATH.exists():
        write_rows([])
    with METRICS_PATH.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_rows(rows: list[dict]) -> None:
    with METRICS_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in COLUMNS})


if __name__ == "__main__":
    main()

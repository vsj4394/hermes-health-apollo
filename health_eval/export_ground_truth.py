"""Ground-truth export helpers shared by Lane 1 tests."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import pstdev
from typing import Iterable


def minutes_since_noon(value: str) -> int:
    """Return wall-clock minutes after noon, wrapping across midnight."""

    parsed = datetime.fromisoformat(value)
    minutes = parsed.hour * 60 + parsed.minute
    return (minutes - 12 * 60) % (24 * 60)


def bedtime_consistency(values: Iterable[str]) -> float:
    """Population stddev of bedtime starts using minutes-since-noon."""

    minutes = [minutes_since_noon(value) for value in values]
    if len(minutes) < 2:
        return 0.0
    return round(pstdev(minutes), 4)


def export_ground_truth(
    db_path: str | Path,
    output_path: str | Path | None = None,
) -> dict:
    """Export deterministic aggregate facts from a fixture database."""

    with sqlite3.connect(Path(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM daily_overview ORDER BY day"
        ).fetchall()
        food_count = conn.execute("SELECT COUNT(*) FROM food_logs").fetchone()[0]
        food_rows = conn.execute(
            """
            SELECT
                day,
                SUM(
                    CAST(
                        json_extract(items_json, '$.total_estimated_calories')
                        AS INTEGER
                    )
                ) AS total_estimated_calories
            FROM food_logs
            WHERE items_json IS NOT NULL
            GROUP BY day
            ORDER BY day
            """
        ).fetchall()

    stress_rows = sorted(
        rows,
        key=lambda row: (row["stress_high_seconds"] or 0, row["day"]),
        reverse=True,
    )
    bedtime_values = [
        row["primary_bedtime_start"]
        for row in rows
        if row["primary_bedtime_start"]
    ]
    food_by_day = {
        row["day"]: row["total_estimated_calories"] or 0
        for row in food_rows
    }
    day_of_week_by_day = {
        row["day"]: date.fromisoformat(row["day"]).strftime("%A")
        for row in rows
    }
    payload = {
        "days": len(rows),
        "food_log_days": food_count,
        "food_total_estimated_calories_by_day": food_by_day,
        "day_of_week_by_day": day_of_week_by_day,
        "highest_stress_day": stress_rows[0]["day"] if stress_rows else None,
        "highest_stress_seconds": (
            stress_rows[0]["stress_high_seconds"] if stress_rows else None
        ),
        "sleep_consistency_minutes": bedtime_consistency(bedtime_values),
        "shifted_pairs": {
            "sleep_to_next_readiness": shifted_pairs(
                rows, "sleep_score", "readiness_score", shift_days=1
            ),
            "bedtime_to_next_readiness": shifted_pairs(
                rows,
                "primary_bedtime_start",
                "readiness_score",
                shift_days=1,
                left_transform=minutes_since_noon,
            ),
        },
    }

    if output_path is not None:
        Path(output_path).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return payload


def shifted_pairs(
    rows: Iterable[sqlite3.Row],
    left_column: str,
    right_column: str,
    *,
    shift_days: int,
    left_transform=None,
) -> list[dict]:
    """Return same-fixture shifted pairs for deterministic correlation checks."""

    rows_by_day = {row["day"]: row for row in rows}
    pairs = []
    for left_row in rows:
        right_day = (
            date.fromisoformat(left_row["day"]) + timedelta(days=shift_days)
        ).isoformat()
        right_row = rows_by_day.get(right_day)
        if right_row is None:
            continue
        left_value = left_row[left_column]
        right_value = right_row[right_column]
        if left_value is None or right_value is None:
            continue
        if left_transform is not None:
            left_value = left_transform(left_value)
        pairs.append(
            {
                "left_day": left_row["day"],
                "right_day": right_day,
                "left_value": left_value,
                "right_value": right_value,
            }
        )
    return pairs

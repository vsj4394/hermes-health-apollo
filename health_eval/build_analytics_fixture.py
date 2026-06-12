"""Deterministic fixture for Plan B analytics-layer tool tests."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

VARIANTS = ("base", "thin_food", "exercise_routine")
START_DAY = date(2026, 3, 13)
DAY_COUNT = 91


def build_analytics_fixture(path: str | Path, *, variant: str = "base") -> Path:
    if variant not in VARIANTS:
        raise ValueError(f"unknown analytics fixture variant: {variant}")
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    with sqlite3.connect(db_path) as conn:
        _create_schema(conn)
        _seed_days(conn, variant=variant)
    return db_path


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES (3);

        CREATE TABLE oura_daily (
            day TEXT PRIMARY KEY,
            readiness_score INTEGER,
            sleep_score INTEGER,
            activity_score INTEGER,
            stress_high_seconds INTEGER DEFAULT 0,
            recovery_high_seconds INTEGER DEFAULT 0,
            stress_day_summary TEXT,
            resting_heart_rate REAL,
            hrv_balance REAL,
            spo2_average REAL,
            total_sleep_duration_seconds INTEGER,
            deep_sleep_duration_seconds INTEGER,
            primary_bedtime_start TEXT,
            primary_bedtime_end TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE oura_sleep_sessions (
            id TEXT PRIMARY KEY,
            day TEXT NOT NULL,
            type TEXT NOT NULL,
            bedtime_start TEXT,
            bedtime_end TEXT,
            total_sleep_duration_seconds INTEGER,
            deep_sleep_duration_seconds INTEGER,
            raw_json TEXT
        );

        CREATE TABLE oura_workouts (
            id TEXT PRIMARY KEY,
            day TEXT NOT NULL,
            activity TEXT,
            calories REAL,
            distance REAL,
            intensity TEXT,
            label TEXT,
            source TEXT,
            start_datetime TEXT,
            end_datetime TEXT,
            raw_json TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE calendar_daily (
            day TEXT PRIMARY KEY,
            meeting_count INTEGER NOT NULL DEFAULT 0,
            meeting_minutes INTEGER NOT NULL DEFAULT 0,
            first_meeting_start TEXT,
            last_meeting_end TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE email_daily (
            day TEXT PRIMARY KEY,
            received_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE food_logs (
            id TEXT PRIMARY KEY,
            day TEXT NOT NULL,
            logged_at TEXT NOT NULL,
            description TEXT NOT NULL,
            items_json TEXT
        );

        CREATE VIEW daily_overview AS
            SELECT
                od.day,
                od.readiness_score,
                od.sleep_score,
                od.activity_score,
                od.stress_high_seconds,
                od.recovery_high_seconds,
                od.stress_day_summary,
                od.resting_heart_rate,
                od.hrv_balance,
                od.spo2_average,
                od.total_sleep_duration_seconds,
                od.deep_sleep_duration_seconds,
                od.primary_bedtime_start,
                od.primary_bedtime_end,
                cd.meeting_count,
                cd.meeting_minutes,
                cd.first_meeting_start,
                cd.last_meeting_end,
                ed.received_count
            FROM oura_daily od
            LEFT JOIN calendar_daily cd ON cd.day = od.day
            LEFT JOIN email_daily ed ON ed.day = od.day;
        """
    )


def _seed_days(conn: sqlite3.Connection, *, variant: str) -> None:
    for offset in range(DAY_COUNT):
        day = START_DAY + timedelta(days=offset)
        day_text = day.isoformat()
        high_signal = offset % 9 in {1, 4, 7}
        meeting_minutes = 260 if high_signal else 35
        email_count = 90 if high_signal else 14
        stress_seconds = 7600 if high_signal else 900
        late_food = high_signal and variant != "thin_food"
        if variant == "exercise_routine":
            late_food = False

        conn.execute(
            """
            INSERT INTO oura_daily(
                day, readiness_score, sleep_score, activity_score,
                stress_high_seconds, recovery_high_seconds,
                total_sleep_duration_seconds, deep_sleep_duration_seconds,
                primary_bedtime_start, primary_bedtime_end
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                day_text,
                80 - (8 if high_signal else 0),
                84 - (9 if late_food else 0),
                76,
                stress_seconds,
                5200 if not high_signal else 2200,
                25200 - (1800 if late_food else 0),
                5400,
                f"{day_text}T23:40:00+00:00",
                (day + timedelta(days=1)).isoformat() + "T07:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO calendar_daily(day, meeting_count, meeting_minutes, first_meeting_start, last_meeting_end)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                day_text,
                6 if high_signal else 1,
                meeting_minutes,
                f"{day_text}T09:00:00+00:00",
                f"{day_text}T17:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO email_daily(day, received_count) VALUES (?, ?)",
            (day_text, email_count),
        )
        if variant != "thin_food" and offset % 2 == 0:
            conn.execute(
                """
                INSERT INTO food_logs(id, day, logged_at, description, items_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"food-{day_text}",
                    day_text,
                    f"{day_text}T21:30:00+00:00" if late_food else f"{day_text}T18:30:00+00:00",
                    "late dinner" if late_food else "early dinner",
                    json.dumps(
                        {
                            "items": [{"name": "dinner"}],
                            "total_estimated_calories": 900 if late_food else 550,
                        },
                        sort_keys=True,
                    ),
                ),
            )
        if variant == "thin_food" and offset in {0, 3, 7}:
            conn.execute(
                """
                INSERT INTO food_logs(id, day, logged_at, description, items_json)
                VALUES (?, ?, ?, 'sparse meal', ?)
                """,
                (
                    f"thin-food-{day_text}",
                    day_text,
                    f"{day_text}T19:00:00+00:00",
                    json.dumps({"items": [{"name": "meal"}]}, sort_keys=True),
                ),
            )
        if day.weekday() in {1, 5}:
            conn.execute(
                """
                INSERT INTO oura_workouts(id, day, activity, start_datetime, end_datetime)
                VALUES (?, ?, 'run', ?, ?)
                """,
                (
                    f"workout-{day_text}",
                    day_text,
                    f"{day_text}T07:00:00+00:00",
                    f"{day_text}T07:35:00+00:00",
                ),
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path")
    parser.add_argument("--variant", default="base", choices=VARIANTS)
    args = parser.parse_args()
    build_analytics_fixture(Path(args.db_path), variant=args.variant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

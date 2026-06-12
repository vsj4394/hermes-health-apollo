"""Deterministic SQLite fixture builder for Lane 1 evals."""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ANCHOR_DAY = date(2026, 6, 7)
VARIANTS = (
    "base",
    "spo2_low",
    "rhr_spike",
    "thin_5d",
    "partial_rows",
    "uncovered_context",
    "workout_stress",
    "null_result",
    "no_food_logged",
    "healthy",
)
PLAN_C_VARIANTS = (
    "routing_base",
    "calendar_email_stress",
    "food_sleep",
    "missed_workouts",
    "thin_food_sleep",
    "provenance_focus",
)
ALL_VARIANTS = VARIANTS + PLAN_C_VARIANTS


def build_golden_db(
    path: str | Path,
    seed: int = 42,
    variant: str = "base",
    days: int = 90,
) -> Path:
    """Build a deterministic golden SQLite database and return its path."""

    if variant not in ALL_VARIANTS:
        raise ValueError(f"unknown fixture variant: {variant}")

    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    rng = random.Random(seed)
    retained_days = _retained_days(variant, days)

    with sqlite3.connect(db_path) as conn:
        create_schema(conn)
        for offset in range(retained_days):
            day = ANCHOR_DAY - timedelta(days=retained_days - offset - 1)
            insert_day(conn, rng, day, offset, variant)
        if variant in PLAN_C_VARIANTS:
            seed_plan_c_rows(conn, variant, retained_days)
        conn.execute(
            "INSERT OR REPLACE INTO sync_state VALUES (?, ?, ?, ?)",
            (
                "oura",
                ANCHOR_DAY.isoformat(),
                "ok",
                f"{ANCHOR_DAY.isoformat()}T00:00:00+00:00",
            ),
        )

    return db_path


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the subset of production schema needed by deterministic evals."""

    conn.executescript(
        """
        CREATE TABLE oura_daily (
            day TEXT PRIMARY KEY,
            readiness_score INTEGER,
            sleep_score INTEGER,
            activity_score INTEGER,
            stress_high_seconds INTEGER CHECK (stress_high_seconds >= 0),
            recovery_high_seconds INTEGER CHECK (recovery_high_seconds >= 0),
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

        CREATE TABLE calendar_daily (
            day TEXT PRIMARY KEY,
            meeting_count INTEGER NOT NULL,
            meeting_minutes INTEGER NOT NULL,
            first_meeting_start TEXT,
            last_meeting_end TEXT
        );

        CREATE TABLE email_daily (
            day TEXT PRIMARY KEY,
            received_count INTEGER NOT NULL
        );

        CREATE TABLE food_logs (
            id TEXT PRIMARY KEY,
            day TEXT NOT NULL,
            logged_at TEXT NOT NULL,
            description TEXT NOT NULL,
            items_json TEXT NOT NULL
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

        CREATE TABLE sync_state (
            provider TEXT PRIMARY KEY,
            last_sync_date TEXT,
            last_status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS exercise_routines (
            id TEXT PRIMARY KEY,
            weekday INTEGER NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO schema_version VALUES (1);

        CREATE INDEX idx_sleep_day_type
            ON oura_sleep_sessions(day, type);
        CREATE INDEX idx_food_day
            ON food_logs(day);
        CREATE INDEX idx_stress_summary
            ON oura_daily(stress_day_summary);

        CREATE VIEW daily_overview AS
            SELECT
                o.day,
                o.readiness_score,
                o.sleep_score,
                o.activity_score,
                o.stress_high_seconds,
                o.recovery_high_seconds,
                o.stress_day_summary,
                o.resting_heart_rate,
                o.hrv_balance,
                o.spo2_average,
                o.total_sleep_duration_seconds,
                o.deep_sleep_duration_seconds,
                o.primary_bedtime_start,
                o.primary_bedtime_end,
                c.meeting_count,
                c.meeting_minutes,
                c.first_meeting_start,
                c.last_meeting_end,
                e.received_count
            FROM oura_daily o
            LEFT JOIN calendar_daily c ON c.day = o.day
            LEFT JOIN email_daily e ON e.day = o.day;
        """
    )


def insert_day(
    conn: sqlite3.Connection,
    rng: random.Random,
    day: date,
    offset: int,
    variant: str,
) -> None:
    """Insert one deterministic fixture day."""

    day_key = day.isoformat()
    heavy_meetings = (
        offset % 9 == 0
        or day == ANCHOR_DAY - timedelta(days=1)
        or variant in {"calendar_email_stress", "provenance_focus", "routing_base"}
    )
    meeting_count = 7 if heavy_meetings else 2 + (offset % 3)
    meeting_minutes = meeting_count * 35
    inbox_count = 95 if heavy_meetings else 20 + (offset % 11) * 3
    stress_seconds = 7200 if heavy_meetings else 1200 + (offset % 5) * 420
    recovery_seconds = max(600, 6000 - stress_seconds // 2)
    bedtime_hour = 23 if offset % 4 else 1
    bedtime_start = datetime(day.year, day.month, day.day, bedtime_hour, 20)
    if bedtime_hour < 12:
        bedtime_start += timedelta(days=1)
    bedtime_end = bedtime_start + timedelta(hours=7, minutes=10)
    sleep_score = 88 - (meeting_count * 2) + rng.randint(-2, 2)
    readiness_score = 86 - (stress_seconds // 1800) + rng.randint(-2, 2)
    resting_hr = 55 + (stress_seconds / 3600) + rng.random()
    spo2 = 97.3 + rng.random() * 0.4

    if variant == "spo2_low" and day == ANCHOR_DAY - timedelta(days=1):
        spo2 = 88.6
    if variant == "rhr_spike" and offset >= 85:
        resting_hr += 9
    if variant == "healthy":
        stress_seconds = 900
        readiness_score = 91
        sleep_score = 90
        resting_hr = 53.5
    if variant == "null_result":
        meeting_count = 0
        meeting_minutes = 0
        inbox_count = 0
    if variant in {"food_sleep", "thin_food_sleep"}:
        heavy_meetings = False
        meeting_count = 2
        meeting_minutes = 70
        inbox_count = 24
        stress_seconds = 1500
        sleep_score = 78 if offset % 3 == 0 else 88
    if variant == "missed_workouts":
        stress_seconds = 1800
        sleep_score = 84

    conn.execute(
        """
        INSERT INTO oura_daily VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            day_key,
            readiness_score,
            sleep_score,
            80 + offset % 10,
            stress_seconds,
            recovery_seconds,
            "stressful" if stress_seconds > 5000 else "normal",
            round(resting_hr, 2),
            round(42 + rng.random() * 10, 2),
            round(spo2, 2),
            430 * 60,
            (85 - meeting_count) * 60,
            bedtime_start.isoformat(),
            bedtime_end.isoformat(),
            f"{day_key}T00:00:00+00:00",
        ),
    )
    conn.execute(
        "INSERT INTO oura_sleep_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            f"sleep-{day_key}",
            day_key,
            "long_sleep",
            bedtime_start.isoformat(),
            bedtime_end.isoformat(),
            430 * 60,
            (85 - meeting_count) * 60,
            json.dumps({"fixture": True}, sort_keys=True),
        ),
    )
    conn.execute(
        "INSERT INTO calendar_daily VALUES (?, ?, ?, ?, ?)",
        (
            day_key,
            meeting_count,
            meeting_minutes,
            f"{day_key}T09:00:00",
            f"{day_key}T17:00:00" if meeting_count else None,
        ),
    )
    conn.execute(
        "INSERT INTO email_daily VALUES (?, ?)",
        (day_key, inbox_count),
    )

    should_log_food = variant != "no_food_logged" and offset % 2 == 0
    if variant == "food_sleep":
        should_log_food = offset < 14
    if variant == "thin_food_sleep":
        should_log_food = offset in {0, retained_midpoint(offset), 89}
    if should_log_food:
        calories = 1850 + (offset % 6) * 80
        if variant == "partial_rows" and offset % 10 == 0:
            calories = 0
        items_json = json.dumps(
            {
                "items": [{"name": "fixture meal", "estimated_calories": calories}],
                "total_estimated_calories": calories,
            },
            sort_keys=True,
        )
        conn.execute(
            "INSERT INTO food_logs VALUES (?, ?, ?, ?, ?)",
            (
                f"food-{day_key}",
                day_key,
                f"{day_key}T{_meal_hour_for_variant(variant, offset):02d}:20:00",
                _meal_description_for_variant(variant, offset),
                items_json,
            ),
        )

    if variant == "missed_workouts" and day.weekday() in {0, 2, 4}:
        missed_day = (day.weekday() == 0 and offset < 7) or (
            day.weekday() == 4 and offset >= 7
        )
        if not missed_day:
            conn.execute(
                """
                INSERT INTO oura_workouts (
                    id, day, activity, calories, distance, intensity, label,
                    source, start_datetime, end_datetime, raw_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"workout-{day_key}",
                    day_key,
                    "strength_training",
                    320,
                    None,
                    "moderate",
                    "planned workout",
                    "fixture",
                    f"{day_key}T07:00:00",
                    f"{day_key}T07:45:00",
                    json.dumps({"fixture": True}, sort_keys=True),
                    f"{day_key}T08:00:00+00:00",
                ),
            )


def _retained_days(variant: str, days: int) -> int:
    if variant == "thin_5d":
        return 5
    if variant in {"calendar_email_stress", "food_sleep", "missed_workouts", "provenance_focus"}:
        return 14
    return days


def seed_plan_c_rows(conn: sqlite3.Connection, variant: str, retained_days: int) -> None:
    if variant == "missed_workouts":
        for weekday, label in [(0, "Monday workout"), (2, "Wednesday workout"), (4, "Friday workout")]:
            conn.execute(
                "INSERT OR REPLACE INTO exercise_routines VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (f"routine-{weekday}", weekday, label),
            )


def _meal_hour_for_variant(variant: str, offset: int) -> int:
    if variant == "food_sleep" and offset % 3 == 0:
        return 22
    if variant == "thin_food_sleep":
        return 21
    return 19


def _meal_description_for_variant(variant: str, offset: int) -> str:
    if variant == "food_sleep" and offset % 3 == 0:
        return "late spicy dinner"
    if variant == "thin_food_sleep":
        return "sparse logged dinner"
    return "fixture dinner"


def retained_midpoint(offset: int) -> int:
    return 44

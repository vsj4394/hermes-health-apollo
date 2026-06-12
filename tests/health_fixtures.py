from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta


def seed_query_days(store, *, start: str = "2026-06-01", day_count: int = 14) -> None:
    store.initialize()
    start_day = date.fromisoformat(start)
    with sqlite3.connect(store.database_path()) as conn:
        for offset in range(day_count):
            day = start_day + timedelta(days=offset)
            day_text = day.isoformat()
            high_signal = offset in {1, 4, 7, 10}
            meeting_minutes = 240 if high_signal else 30
            email_count = 80 if high_signal else 12
            stress_seconds = 7200 if high_signal else 900
            conn.execute(
                """
                INSERT INTO oura_daily(
                    day, readiness_score, sleep_score, activity_score,
                    stress_high_seconds, recovery_high_seconds,
                    total_sleep_duration_seconds,
                    deep_sleep_duration_seconds, primary_bedtime_start,
                    primary_bedtime_end
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                    readiness_score = excluded.readiness_score,
                    sleep_score = excluded.sleep_score,
                    activity_score = excluded.activity_score,
                    stress_high_seconds = excluded.stress_high_seconds,
                    recovery_high_seconds = excluded.recovery_high_seconds,
                    total_sleep_duration_seconds = excluded.total_sleep_duration_seconds,
                    deep_sleep_duration_seconds = excluded.deep_sleep_duration_seconds,
                    primary_bedtime_start = excluded.primary_bedtime_start,
                    primary_bedtime_end = excluded.primary_bedtime_end
                """,
                (
                    day_text,
                    78 - (10 if high_signal else 0),
                    82 - (8 if high_signal else 0),
                    75,
                    stress_seconds,
                    5400 if high_signal else 1800,
                    25200 - (1800 if high_signal else 0),
                    5400,
                    f"{day_text}T23:40:00+00:00",
                    (day + timedelta(days=1)).isoformat() + "T07:00:00+00:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO calendar_daily(day, meeting_count, meeting_minutes, first_meeting_start, last_meeting_end)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                    meeting_count = excluded.meeting_count,
                    meeting_minutes = excluded.meeting_minutes,
                    first_meeting_start = excluded.first_meeting_start,
                    last_meeting_end = excluded.last_meeting_end
                """,
                (
                    day_text,
                    5 if high_signal else 1,
                    meeting_minutes,
                    f"{day_text}T09:00:00+00:00",
                    f"{day_text}T17:00:00+00:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO email_daily(day, received_count)
                VALUES (?, ?)
                ON CONFLICT(day) DO UPDATE SET received_count = excluded.received_count
                """,
                (day_text, email_count),
            )
            if offset in {0, 1, 3, 4, 6, 7, 9, 10}:
                calories = 900 if high_signal else 550
                conn.execute(
                    """
                    INSERT OR REPLACE INTO food_logs(id, day, logged_at, description, items_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        f"food-{day_text}",
                        day_text,
                        f"{day_text}T21:30:00+00:00"
                        if high_signal
                        else f"{day_text}T18:30:00+00:00",
                        "late heavy dinner" if high_signal else "early dinner",
                        json.dumps(
                            {
                                "items": [{"name": "dinner"}],
                                "total_estimated_calories": calories,
                            }
                        ),
                    ),
                )


def seed_workout_rows(store) -> None:
    store.initialize()
    with sqlite3.connect(store.database_path()) as conn:
        for day_text in ("2026-06-02", "2026-06-06", "2026-06-09"):
            conn.execute(
                """
                INSERT OR REPLACE INTO oura_workouts(id, day, activity, start_datetime, end_datetime)
                VALUES (?, ?, 'run', ?, ?)
                """,
                (
                    f"workout-{day_text}",
                    day_text,
                    f"{day_text}T07:00:00+00:00",
                    f"{day_text}T07:35:00+00:00",
                ),
            )


def seed_thin_food_fixture(store) -> None:
    seed_query_days(store, start="2026-03-13", day_count=14)
    with sqlite3.connect(store.database_path()) as conn:
        conn.execute("DELETE FROM food_logs")
        for day_text in ("2026-03-13", "2026-03-16", "2026-03-20"):
            conn.execute(
                """
                INSERT OR REPLACE INTO food_logs(id, day, logged_at, description, items_json)
                VALUES (?, ?, ?, 'single sparse meal', ?)
                """,
                (
                    f"thin-food-{day_text}",
                    day_text,
                    f"{day_text}T19:00:00+00:00",
                    json.dumps({"items": [{"name": "meal"}]}),
                ),
            )

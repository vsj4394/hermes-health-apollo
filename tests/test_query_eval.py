from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str):
    package_name = "hermes_plugins.health_data"
    sys.modules.setdefault("hermes_plugins", types.ModuleType("hermes_plugins"))
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        package.__path__ = [str(ROOT)]
        sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(
        f"{package_name}.{name}", ROOT / f"{name}.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def modules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return {
        "store": load_module("store"),
        "query": load_module("query"),
    }


def insert_day(
    conn: sqlite3.Connection,
    *,
    day: str,
    sleep_score: int,
    readiness_score: int,
    stress_seconds: int,
    meeting_minutes: int,
    email_count: int,
    bedtime_start: str,
    deep_sleep_seconds: int = 5400,
    calories: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO oura_daily(
            day,
            readiness_score,
            sleep_score,
            stress_high_seconds,
            recovery_high_seconds,
            resting_heart_rate,
            hrv_balance,
            total_sleep_duration_seconds,
            deep_sleep_duration_seconds,
            primary_bedtime_start,
            primary_bedtime_end
        )
        VALUES (?, ?, ?, ?, 3600, 56.5, 48.0, 27000, ?, ?, ?)
        """,
        (
            day,
            readiness_score,
            sleep_score,
            stress_seconds,
            deep_sleep_seconds,
            bedtime_start,
            f"{day}T07:00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO calendar_daily(day, meeting_count, meeting_minutes)
        VALUES (?, ?, ?)
        """,
        (day, meeting_minutes // 30, meeting_minutes),
    )
    conn.execute(
        "INSERT INTO email_daily(day, received_count) VALUES (?, ?)",
        (day, email_count),
    )
    if calories is not None:
        conn.execute(
            """
            INSERT INTO food_logs(id, day, logged_at, description, items_json)
            VALUES (?, ?, ?, 'fixture meal', ?)
            """,
            (
                f"food-{day}",
                day,
                f"{day}T18:30:00",
                json.dumps({"items": [], "total_estimated_calories": calories}),
            ),
        )


def seed_query_days(store):
    store.initialize()
    with sqlite3.connect(store.database_path()) as conn:
        insert_day(
            conn,
            day="2026-06-01",
            sleep_score=72,
            readiness_score=70,
            stress_seconds=1800,
            meeting_minutes=60,
            email_count=20,
            bedtime_start="2026-06-01T23:50:00",
            calories=1800,
        )
        insert_day(
            conn,
            day="2026-06-02",
            sleep_score=83,
            readiness_score=76,
            stress_seconds=5400,
            meeting_minutes=240,
            email_count=80,
            bedtime_start="2026-06-03T00:10:00",
            calories=2250,
        )
        insert_day(
            conn,
            day="2026-06-03",
            sleep_score=91,
            readiness_score=88,
            stress_seconds=900,
            meeting_minutes=30,
            email_count=10,
            bedtime_start="2026-06-03T23:55:00",
        )


def test_date_range_adds_derived_day_fields_and_sleep_consistency(modules):
    store = modules["store"]
    query = modules["query"]
    seed_query_days(store)

    result = query.health_query(
        {"query_type": "date_range", "start": "2026-06-01", "end": "2026-06-03"}
    )

    assert [day["day_of_week"] for day in result["days"]] == [
        "Monday",
        "Tuesday",
        "Wednesday",
    ]
    assert result["days"][1]["food_total_estimated_calories"] == 2250
    assert result["days"][2]["food_total_estimated_calories"] == 0
    assert result["sleep_consistency_minutes"] == pytest.approx(
        query.sleep_consistency_minutes(
            [
                "2026-06-01T23:50:00",
                "2026-06-03T00:10:00",
                "2026-06-03T23:55:00",
            ]
        )
    )


def test_stress_days_returns_sorted_derived_rows(modules):
    store = modules["store"]
    query = modules["query"]
    seed_query_days(store)

    result = query.health_query({"query_type": "stress_days", "limit": 2})

    assert [day["day"] for day in result["days"]] == ["2026-06-02", "2026-06-01"]
    assert result["days"][0]["day_of_week"] == "Tuesday"
    assert result["days"][0]["food_total_estimated_calories"] == 2250


def test_correlate_returns_shifted_pairs_for_next_day_outcomes(modules):
    store = modules["store"]
    query = modules["query"]
    seed_query_days(store)

    result = query.health_query(
        {
            "query_type": "correlate",
            "left": "sleep_score",
            "right": "readiness_score",
            "start": "2026-06-01",
            "end": "2026-06-03",
            "shift_days": 1,
        }
    )

    assert result["left"] == "sleep_score"
    assert result["right"] == "readiness_score"
    assert result["shift_days"] == 1
    assert result["pairs"] == [
        {
            "left_day": "2026-06-01",
            "right_day": "2026-06-02",
            "left_value": 72,
            "right_value": 76,
        },
        {
            "left_day": "2026-06-02",
            "right_day": "2026-06-03",
            "left_value": 83,
            "right_value": 88,
        },
    ]


def test_correlate_can_use_food_calories_from_items_json(modules):
    store = modules["store"]
    query = modules["query"]
    seed_query_days(store)

    result = query.health_query(
        {
            "query_type": "correlate",
            "left": "food_total_estimated_calories",
            "right": "stress_high_seconds",
            "start": "2026-06-01",
            "end": "2026-06-03",
        }
    )

    assert result["pairs"] == [
        {
            "left_day": "2026-06-01",
            "right_day": "2026-06-01",
            "left_value": 1800,
            "right_value": 1800,
        },
        {
            "left_day": "2026-06-02",
            "right_day": "2026-06-02",
            "left_value": 2250,
            "right_value": 5400,
        },
        {
            "left_day": "2026-06-03",
            "right_day": "2026-06-03",
            "left_value": 0,
            "right_value": 900,
        },
    ]


def test_correlate_converts_bedtime_to_numeric_minutes(modules):
    store = modules["store"]
    query = modules["query"]
    seed_query_days(store)

    result = query.health_query(
        {
            "query_type": "correlate",
            "left": "bedtime_minutes_since_noon",
            "right": "readiness_score",
            "start": "2026-06-01",
            "end": "2026-06-03",
            "shift_days": 1,
        }
    )

    assert result["pairs"] == [
        {
            "left_day": "2026-06-01",
            "right_day": "2026-06-02",
            "left_value": 710.0,
            "right_value": 76,
        },
        {
            "left_day": "2026-06-02",
            "right_day": "2026-06-03",
            "left_value": 730.0,
            "right_value": 88,
        },
    ]
    assert result["correlation"] == pytest.approx(1.0)


def test_heart_rate_query_returns_samples_and_summary(modules):
    store = modules["store"]
    query = modules["query"]
    store.initialize()
    with sqlite3.connect(store.database_path()) as conn:
        conn.executemany(
            """
            INSERT INTO oura_heart_rate(timestamp, timestamp_unix, bpm, source)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("2026-06-10T00:05:00.000+00:00", 1781049900000, 58, "sleep"),
                ("2026-06-10T00:10:00.000+00:00", 1781050200000, 62, "sleep"),
                ("2026-06-10T15:00:00.000+00:00", 1781103600000, 82, "awake"),
            ],
        )

    result = query.health_query(
        {
            "query_type": "heart_rate",
            "start": "2026-06-10",
            "end": "2026-06-10",
            "source": "sleep",
            "limit": 10,
        }
    )

    assert result["sample_count"] == 2
    assert result["min_bpm"] == 58
    assert result["max_bpm"] == 62
    assert result["avg_bpm"] == pytest.approx(60.0)
    assert result["by_source"] == {"sleep": 2}
    assert [sample["bpm"] for sample in result["samples"]] == [58, 62]


def test_new_oura_document_queries_and_coverage(modules):
    store = modules["store"]
    query = modules["query"]
    store.initialize()
    with sqlite3.connect(store.database_path()) as conn:
        conn.execute(
            """
            INSERT INTO oura_workouts(
                id, day, activity, calories, distance, intensity, source,
                start_datetime, end_datetime
            )
            VALUES (
                'workout-1', '2026-06-10', 'cycling', 450, 12000,
                'hard', 'confirmed', '2026-06-10T17:00:00',
                '2026-06-10T18:00:00'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO oura_sessions(id, day, type, heart_rate_json)
            VALUES ('session-1', '2026-06-10', 'meditation', ?)
            """,
            (json.dumps({"interval": 5, "items": [61, 59]}),),
        )
        conn.execute(
            """
            INSERT INTO oura_tags(id, day, text, timestamp, tags_json)
            VALUES ('tag-1', '2026-06-10', 'late meal', '2026-06-10T21:00:00', ?)
            """,
            (json.dumps(["meal"]),),
        )
        conn.execute(
            """
            INSERT INTO oura_daily_resilience(id, day, level)
            VALUES ('resilience-1', '2026-06-10', 'solid')
            """
        )

    workouts = query.health_query(
        {
            "query_type": "workouts",
            "start": "2026-06-10",
            "end": "2026-06-10",
        }
    )
    sessions = query.health_query({"query_type": "sessions", "limit": 5})
    tags = query.health_query({"query_type": "tags", "limit": 5})
    coverage = query.health_query({"query_type": "coverage"})["coverage"]

    assert workouts["workouts"][0]["activity"] == "cycling"
    assert sessions["sessions"][0]["heart_rate"] == {
        "interval": 5,
        "items": [61, 59],
    }
    assert tags["tags"][0]["tags"] == ["meal"]
    assert coverage["workouts"] == {
        "row_count": 1,
        "first_day": "2026-06-10",
        "last_day": "2026-06-10",
    }
    assert coverage["daily_resilience"]["row_count"] == 1

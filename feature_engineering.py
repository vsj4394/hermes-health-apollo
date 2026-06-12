from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from . import query, semantic_layer, store
from .feature_registry import FEATURE_DEFINITIONS, FEATURE_VERSION, FeatureDefinition


def materialize_features(
    *,
    feature_keys: list[str],
    start: str,
    end: str,
    grain: str,
) -> dict:
    unknown = [key for key in feature_keys if key not in FEATURE_DEFINITIONS]
    if unknown:
        raise ValueError(f"Unsupported feature keys: {', '.join(sorted(unknown))}")
    semantic_layer.refresh_canonical_facts(start=start, end=end)
    with sqlite3.connect(store.database_path()) as conn:
        conn.row_factory = sqlite3.Row
        semantic_layer.ensure_canonical_schema(conn)
        for feature_key in feature_keys:
            definition = FEATURE_DEFINITIONS[feature_key]
            if definition.grain != grain:
                raise ValueError(
                    f"Feature {feature_key} requires grain {definition.grain}, got {grain}"
                )
            _materialize_feature(conn, definition, start, end)
        conn.commit()
    return query_feature_rows(feature_keys=feature_keys, start=start, end=end, grain=grain)


def query_feature_rows(
    *,
    feature_keys: list[str],
    start: str,
    end: str,
    grain: str,
) -> dict:
    with sqlite3.connect(store.database_path()) as conn:
        conn.row_factory = sqlite3.Row
        semantic_layer.ensure_canonical_schema(conn)
        rows = conn.execute(
            f"""
            SELECT feature_key, feature_ts, value_number, value_text, provenance_json, feature_id
            FROM features
            WHERE grain = ?
              AND feature_ts BETWEEN ? AND ?
              AND feature_version = ?
              AND feature_key IN ({",".join("?" for _ in feature_keys)})
            ORDER BY feature_ts, feature_key
            """,
            (grain, start, end, FEATURE_VERSION, *feature_keys),
        ).fetchall()
    by_day: dict[str, dict[str, Any]] = {
        day: {"day": day, **{key: None for key in feature_keys}, "provenance": {}}
        for day in semantic_layer.iter_days(start, end)
    }
    for row in rows:
        target = by_day[row["feature_ts"]]
        target[row["feature_key"]] = _feature_value(row)
        provenance = json.loads(row["provenance_json"] or "{}")
        if provenance:
            target["provenance"][row["feature_key"]] = provenance
    for row in by_day.values():
        if not row["provenance"]:
            row.pop("provenance")
    return {
        "features": feature_keys,
        "grain": grain,
        "start": start,
        "end": end,
        "rows": list(by_day.values()),
    }


def _materialize_feature(
    conn: sqlite3.Connection,
    definition: FeatureDefinition,
    start: str,
    end: str,
) -> None:
    for day in semantic_layer.iter_days(start, end):
        value, provenance = _build_feature_value(conn, definition.key, day)
        _upsert_feature(conn, definition, day, value, provenance)


def _build_feature_value(
    conn: sqlite3.Connection,
    feature_key: str,
    day: str,
) -> tuple[int | float | str | None, dict[str, Any]]:
    if feature_key in {
        "sleep_score",
        "readiness_score",
        "stress_high_seconds",
        "recovery_high_seconds",
        "sleep_duration_seconds",
        "deep_sleep_seconds",
    }:
        source_column = {
            "sleep_duration_seconds": "total_sleep_duration_seconds",
            "deep_sleep_seconds": "deep_sleep_duration_seconds",
        }.get(feature_key, feature_key)
        row = conn.execute(
            f"SELECT {source_column} FROM oura_daily WHERE day = ?",
            (day,),
        ).fetchone()
        return _present_or_missing(
            None if row is None else row[0],
            source_tables=("oura_daily",),
            missing="null",
        )
    if feature_key == "bedtime_minutes_since_noon":
        row = conn.execute(
            "SELECT primary_bedtime_start FROM oura_daily WHERE day = ?",
            (day,),
        ).fetchone()
        value = None if row is None or row[0] is None else query._minutes_since_noon(row[0])
        return _present_or_missing(value, source_tables=("oura_daily",), missing="null")
    if feature_key in {"meeting_minutes", "meeting_count"}:
        row = conn.execute(
            f"SELECT {feature_key} FROM calendar_daily WHERE day = ?",
            (day,),
        ).fetchone()
        return _present_or_missing(
            0 if row is None or row[0] is None else row[0],
            source_tables=("calendar_daily",),
            missing="zero",
        )
    if feature_key == "email_received_count":
        row = conn.execute(
            "SELECT received_count FROM email_daily WHERE day = ?",
            (day,),
        ).fetchone()
        return _present_or_missing(
            0 if row is None or row[0] is None else row[0],
            source_tables=("email_daily",),
            missing="zero",
        )
    if feature_key in {
        "meal_count",
        "food_total_estimated_calories",
        "last_meal_hour",
        "late_meal_flag",
    }:
        return _food_feature(conn, feature_key, day)
    if feature_key in {"workout_count", "exercise_minutes"}:
        return _workout_feature(conn, feature_key, day)
    if feature_key == "days_since_workout":
        return _days_since_workout(conn, day)
    if feature_key == "missed_planned_workout":
        return _missed_planned_workout(conn, day)
    raise ValueError(f"Unsupported feature key: {feature_key}")


def _food_feature(
    conn: sqlite3.Connection,
    feature_key: str,
    day: str,
) -> tuple[int | float | None, dict[str, Any]]:
    rows = conn.execute(
        "SELECT logged_at, items_json FROM food_logs WHERE day = ? ORDER BY logged_at",
        (day,),
    ).fetchall()
    if not rows:
        return None, {"coverage": "missing"}
    if feature_key == "meal_count":
        return len(rows), {"coverage": "present", "source_tables": ["food_logs"]}
    if feature_key == "food_total_estimated_calories":
        values = [
            _json_number(row["items_json"], "total_estimated_calories")
            for row in rows
        ]
        known = [value for value in values if value is not None]
        if not known:
            return None, {"coverage": "missing"}
        return sum(known), {"coverage": "present", "source_tables": ["food_logs"]}
    last_logged_at = rows[-1]["logged_at"]
    parsed = datetime.fromisoformat(str(last_logged_at).replace("Z", "+00:00"))
    hour = parsed.hour + parsed.minute / 60
    if feature_key == "last_meal_hour":
        return hour, {"coverage": "present", "source_tables": ["food_logs"]}
    return int(hour >= 20), {"coverage": "present", "source_tables": ["food_logs"]}


def _workout_feature(
    conn: sqlite3.Connection,
    feature_key: str,
    day: str,
) -> tuple[int | float, dict[str, Any]]:
    rows = conn.execute(
        "SELECT start_datetime, end_datetime FROM oura_workouts WHERE day = ?",
        (day,),
    ).fetchall()
    if feature_key == "workout_count":
        return len(rows), {"coverage": "present", "source_tables": ["oura_workouts"]}
    minutes = 0.0
    for row in rows:
        if not row["start_datetime"] or not row["end_datetime"]:
            continue
        start = datetime.fromisoformat(str(row["start_datetime"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(row["end_datetime"]).replace("Z", "+00:00"))
        minutes += max(0.0, (end - start).total_seconds() / 60)
    return minutes, {"coverage": "present", "source_tables": ["oura_workouts"]}


def _days_since_workout(
    conn: sqlite3.Connection,
    day: str,
) -> tuple[int | None, dict[str, Any]]:
    row = conn.execute(
        "SELECT MAX(day) FROM oura_workouts WHERE day <= ?",
        (day,),
    ).fetchone()
    if row is None or row[0] is None:
        return None, {"coverage": "missing"}
    from datetime import date

    delta = date.fromisoformat(day) - date.fromisoformat(row[0])
    return delta.days, {"coverage": "present", "source_tables": ["oura_workouts"]}


def _missed_planned_workout(
    conn: sqlite3.Connection,
    day: str,
) -> tuple[int | None, dict[str, Any]]:
    habit = conn.execute(
        """
        SELECT attributes_json FROM entities
        WHERE entity_type = 'habit'
        ORDER BY canonical_key
        LIMIT 1
        """
    ).fetchone()
    if habit is None:
        return None, {"coverage": "missing"}
    expected = set(json.loads(habit[0] or "{}").get("expected_weekdays") or [])
    from datetime import date

    if date.fromisoformat(day).weekday() not in expected:
        return 0, {"coverage": "present", "source_tables": ["entities", "oura_workouts"]}
    workout_count, _provenance = _workout_feature(conn, "workout_count", day)
    return int(workout_count == 0), {
        "coverage": "present",
        "source_tables": ["entities", "oura_workouts"],
    }


def _upsert_feature(
    conn: sqlite3.Connection,
    definition: FeatureDefinition,
    day: str,
    value: int | float | str | None,
    provenance: dict[str, Any],
) -> None:
    feature_id = f"{definition.key}:{definition.grain}:global:{day}:{FEATURE_VERSION}"
    conn.execute(
        "DELETE FROM features WHERE feature_id = ?",
        (feature_id,),
    )
    conn.execute(
        """
        INSERT INTO features(
            feature_id, feature_key, grain, entity_scope, entity_id,
            feature_ts, window_start, window_end, value_number, value_text,
            provenance_json, feature_version
        )
        VALUES (?, ?, ?, 'global', NULL, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            feature_id,
            definition.key,
            definition.grain,
            day,
            f"{day}T00:00:00",
            f"{day}T23:59:59",
            value if isinstance(value, (int, float)) else None,
            value if isinstance(value, str) else None,
            json.dumps(provenance, sort_keys=True),
            FEATURE_VERSION,
        ),
    )


def _present_or_missing(
    value: Any,
    *,
    source_tables: tuple[str, ...],
    missing: str,
) -> tuple[Any, dict[str, Any]]:
    if value is None and missing != "zero":
        return None, {"coverage": "missing"}
    return value, {"coverage": "present", "source_tables": list(source_tables)}


def _json_number(items_json: str | None, key: str) -> int | float | None:
    if not items_json:
        return None
    value = json.loads(items_json).get(key)
    return value if isinstance(value, (int, float)) else None


def _feature_value(row: sqlite3.Row) -> int | float | str | None:
    if row["value_text"] is not None:
        return row["value_text"]
    value = row["value_number"]
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value

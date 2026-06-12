from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Iterable


DAILY_COLUMNS = (
    "readiness_score",
    "sleep_score",
    "activity_score",
    "stress_high_seconds",
    "recovery_high_seconds",
    "stress_day_summary",
    "resting_heart_rate",
    "hrv_balance",
    "spo2_average",
    "total_sleep_duration_seconds",
    "deep_sleep_duration_seconds",
    "primary_bedtime_start",
    "primary_bedtime_end",
)

SLEEP_TYPES_FOR_PRIMARY = {"long_sleep", "sleep"}

EXTRA_ROW_SPECS = {
    "heart_rate": {
        "table": "oura_heart_rate",
        "primary_key": "timestamp",
        "columns": (
            "timestamp",
            "timestamp_unix",
            "bpm",
            "source",
            "producer_timestamp",
            "raw_json",
        ),
    },
    "ring_battery": {
        "table": "oura_ring_battery",
        "primary_key": "timestamp",
        "columns": (
            "timestamp",
            "timestamp_unix",
            "producer_timestamp",
            "level",
            "charging",
            "in_charger",
            "raw_json",
        ),
    },
    "personal_info": {
        "table": "oura_personal_info",
        "primary_key": "id",
        "columns": (
            "id",
            "age",
            "weight",
            "height",
            "biological_sex",
            "email",
            "raw_json",
        ),
    },
    "workouts": {
        "table": "oura_workouts",
        "primary_key": "id",
        "columns": (
            "id",
            "day",
            "activity",
            "calories",
            "distance",
            "intensity",
            "label",
            "source",
            "start_datetime",
            "end_datetime",
            "raw_json",
        ),
    },
    "sessions": {
        "table": "oura_sessions",
        "primary_key": "id",
        "columns": (
            "id",
            "day",
            "type",
            "start_datetime",
            "end_datetime",
            "mood",
            "heart_rate_json",
            "heart_rate_variability_json",
            "motion_count_json",
            "raw_json",
        ),
    },
    "tags": {
        "table": "oura_tags",
        "primary_key": "id",
        "columns": ("id", "day", "text", "timestamp", "tags_json", "raw_json"),
    },
    "enhanced_tags": {
        "table": "oura_enhanced_tags",
        "primary_key": "id",
        "columns": (
            "id",
            "start_day",
            "end_day",
            "start_time",
            "end_time",
            "tag_type_code",
            "comment",
            "custom_name",
            "raw_json",
        ),
    },
    "daily_resilience": {
        "table": "oura_daily_resilience",
        "primary_key": "id",
        "columns": ("id", "day", "level", "contributors_json", "raw_json"),
    },
    "daily_cardiovascular_age": {
        "table": "oura_daily_cardiovascular_age",
        "primary_key": "id",
        "columns": ("id", "day", "vascular_age", "pulse_wave_velocity", "raw_json"),
    },
    "vo2_max": {
        "table": "oura_vo2_max",
        "primary_key": "id",
        "columns": ("id", "day", "timestamp", "vo2_max", "raw_json"),
    },
    "sleep_time": {
        "table": "oura_sleep_time",
        "primary_key": "id",
        "columns": (
            "id",
            "day",
            "recommendation",
            "status",
            "optimal_bedtime_json",
            "raw_json",
        ),
    },
    "rest_mode_periods": {
        "table": "oura_rest_mode_periods",
        "primary_key": "id",
        "columns": (
            "id",
            "start_day",
            "end_day",
            "start_time",
            "end_time",
            "episodes_json",
            "raw_json",
        ),
    },
    "ring_configuration": {
        "table": "oura_ring_configuration",
        "primary_key": "id",
        "columns": (
            "id",
            "color",
            "design",
            "firmware_version",
            "hardware_type",
            "set_up_at",
            "size",
            "raw_json",
        ),
    },
}


def normalize_daily(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload)


def normalize_daily_rows(
    *,
    daily_sleep: Iterable[dict[str, Any]] = (),
    readiness: Iterable[dict[str, Any]] = (),
    stress: Iterable[dict[str, Any]] = (),
    activity: Iterable[dict[str, Any]] = (),
    spo2: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    for item in daily_sleep:
        row = _row_for_day(rows, item)
        row["sleep_score"] = item.get("score")
        row["total_sleep_duration_seconds"] = _first_present(
            item, "total_sleep_duration", "total_sleep_duration_seconds"
        )
        row["deep_sleep_duration_seconds"] = _first_present(
            item, "deep_sleep_duration", "deep_sleep_duration_seconds"
        )

    for item in readiness:
        row = _row_for_day(rows, item)
        row["readiness_score"] = item.get("score")
        row["hrv_balance"] = _first_present(
            item,
            "hrv_balance",
            ("contributors", "hrv_balance"),
        )
        row["resting_heart_rate"] = _first_present(
            item,
            "resting_heart_rate",
            "resting_hr",
            "resting_hr_bpm",
            ("contributors", "resting_heart_rate"),
        )

    for item in stress:
        row = _row_for_day(rows, item)
        row["stress_high_seconds"] = _first_present(
            item, "stress_high_seconds", "stress_high"
        )
        row["recovery_high_seconds"] = _first_present(
            item, "recovery_high_seconds", "recovery_high"
        )
        row["stress_day_summary"] = _first_present(item, "stress_day_summary", "day_summary")

    for item in activity:
        row = _row_for_day(rows, item)
        row["activity_score"] = item.get("score")

    for item in spo2:
        row = _row_for_day(rows, item)
        row["spo2_average"] = _first_present(
            item,
            "spo2_average",
            ("spo2_percentage", "average"),
        )

    return [rows[day] for day in sorted(rows)]


def normalize_sleep_sessions(
    payload: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for item in payload:
        session_id = item.get("id")
        day = item.get("day")
        session_type = item.get("type")
        if not session_id or not day or not session_type:
            continue
        sessions.append(
            {
                "id": str(session_id),
                "day": str(day),
                "type": str(session_type),
                "bedtime_start": item.get("bedtime_start"),
                "bedtime_end": item.get("bedtime_end"),
                "total_sleep_duration_seconds": _first_present(
                    item, "total_sleep_duration", "total_sleep_duration_seconds"
                ),
                "deep_sleep_duration_seconds": _first_present(
                    item, "deep_sleep_duration", "deep_sleep_duration_seconds"
                ),
                "raw_json": json.dumps(item, sort_keys=True),
            }
        )
    return sessions


def normalize_extra_rows(rows: dict[str, Iterable[dict[str, Any]]]) -> dict[str, list[dict]]:
    sleep_rows = list(rows.get("sleep", []))
    session_rows = list(rows.get("sessions", []))
    return {
        "heart_rate": [
            *normalize_heart_rate(rows.get("heart_rate", [])),
            *normalize_sampled_heart_rate(sleep_rows, source="sleep"),
            *normalize_sampled_heart_rate(session_rows, source="session"),
        ],
        "ring_battery": normalize_ring_battery(rows.get("ring_battery", [])),
        "personal_info": normalize_personal_info(rows.get("personal_info", [])),
        "workouts": normalize_workouts(rows.get("workouts", [])),
        "sessions": normalize_sessions(session_rows),
        "tags": normalize_tags(rows.get("tags", [])),
        "enhanced_tags": normalize_enhanced_tags(rows.get("enhanced_tags", [])),
        "daily_resilience": normalize_daily_resilience(
            rows.get("daily_resilience", [])
        ),
        "daily_cardiovascular_age": normalize_daily_cardiovascular_age(
            rows.get("daily_cardiovascular_age", [])
        ),
        "vo2_max": normalize_vo2_max(rows.get("vo2_max", [])),
        "sleep_time": normalize_sleep_time(rows.get("sleep_time", [])),
        "rest_mode_periods": normalize_rest_mode_periods(
            rows.get("rest_mode_periods", [])
        ),
        "ring_configuration": normalize_ring_configuration(
            rows.get("ring_configuration", [])
        ),
    }


def normalize_heart_rate(payload: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        timestamp = item.get("timestamp")
        bpm = item.get("bpm")
        source = item.get("source")
        if not timestamp or bpm is None or not source:
            continue
        records.append(
            {
                "timestamp": str(timestamp),
                "timestamp_unix": item.get("timestamp_unix"),
                "bpm": bpm,
                "source": str(source),
                "producer_timestamp": item.get("producer_timestamp"),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_ring_battery(payload: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        timestamp = item.get("timestamp")
        level = item.get("level")
        if not timestamp or level is None:
            continue
        records.append(
            {
                "timestamp": str(timestamp),
                "timestamp_unix": item.get("timestamp_unix"),
                "producer_timestamp": item.get("producer_timestamp"),
                "level": level,
                "charging": _bool_int(item.get("charging")),
                "in_charger": _bool_int(item.get("in_charger")),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_sampled_heart_rate(
    payload: Iterable[dict[str, Any]],
    *,
    source: str,
) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        parent_id = item.get("id")
        sample = item.get("heart_rate")
        if not isinstance(sample, dict):
            continue
        timestamp = sample.get("timestamp")
        interval = sample.get("interval")
        values = sample.get("items")
        if not timestamp or not interval or not isinstance(values, list):
            continue
        try:
            start = _parse_sample_datetime(str(timestamp))
            interval_seconds = int(interval)
        except (TypeError, ValueError):
            continue
        for index, bpm in enumerate(values):
            if bpm is None:
                continue
            sample_time = start + timedelta(seconds=interval_seconds * index)
            records.append(
                {
                    "timestamp": sample_time.isoformat(),
                    "timestamp_unix": _timestamp_unix_ms(sample_time),
                    "bpm": bpm,
                    "source": source,
                    "producer_timestamp": None,
                    "raw_json": _raw_json(
                        {
                            "parent_id": parent_id,
                            "source": source,
                            "index": index,
                            "timestamp": sample_time.isoformat(),
                            "bpm": bpm,
                        }
                    ),
                }
            )
    return records


def normalize_personal_info(payload: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        record_id = item.get("id")
        if not record_id:
            continue
        records.append(
            {
                "id": str(record_id),
                "age": item.get("age"),
                "weight": item.get("weight"),
                "height": item.get("height"),
                "biological_sex": item.get("biological_sex"),
                "email": item.get("email"),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_workouts(payload: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        record_id = item.get("id")
        day = item.get("day")
        if not record_id or not day:
            continue
        records.append(
            {
                "id": str(record_id),
                "day": str(day),
                "activity": item.get("activity"),
                "calories": item.get("calories"),
                "distance": item.get("distance"),
                "intensity": item.get("intensity"),
                "label": item.get("label"),
                "source": item.get("source"),
                "start_datetime": item.get("start_datetime"),
                "end_datetime": item.get("end_datetime"),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_sessions(payload: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        record_id = item.get("id")
        day = item.get("day")
        if not record_id or not day:
            continue
        records.append(
            {
                "id": str(record_id),
                "day": str(day),
                "type": item.get("type"),
                "start_datetime": item.get("start_datetime"),
                "end_datetime": item.get("end_datetime"),
                "mood": item.get("mood"),
                "heart_rate_json": _json_or_none(item.get("heart_rate")),
                "heart_rate_variability_json": _json_or_none(
                    item.get("heart_rate_variability")
                ),
                "motion_count_json": _json_or_none(item.get("motion_count")),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_tags(payload: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        record_id = item.get("id")
        day = item.get("day")
        if not record_id or not day:
            continue
        records.append(
            {
                "id": str(record_id),
                "day": str(day),
                "text": item.get("text"),
                "timestamp": item.get("timestamp"),
                "tags_json": _json_or_none(item.get("tags")),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_enhanced_tags(payload: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        record_id = item.get("id")
        start_day = item.get("start_day")
        start_time = item.get("start_time")
        if not record_id or not start_day or not start_time:
            continue
        records.append(
            {
                "id": str(record_id),
                "start_day": str(start_day),
                "end_day": item.get("end_day"),
                "start_time": str(start_time),
                "end_time": item.get("end_time"),
                "tag_type_code": item.get("tag_type_code"),
                "comment": item.get("comment"),
                "custom_name": item.get("custom_name"),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_daily_resilience(payload: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        record_id = item.get("id")
        day = item.get("day")
        if not record_id or not day:
            continue
        records.append(
            {
                "id": str(record_id),
                "day": str(day),
                "level": item.get("level"),
                "contributors_json": _json_or_none(item.get("contributors")),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_daily_cardiovascular_age(
    payload: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        record_id = item.get("id")
        day = item.get("day")
        if not record_id or not day:
            continue
        records.append(
            {
                "id": str(record_id),
                "day": str(day),
                "vascular_age": item.get("vascular_age"),
                "pulse_wave_velocity": item.get("pulse_wave_velocity"),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_vo2_max(payload: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        record_id = item.get("id")
        day = item.get("day")
        if not record_id or not day:
            continue
        records.append(
            {
                "id": str(record_id),
                "day": str(day),
                "timestamp": item.get("timestamp"),
                "vo2_max": item.get("vo2_max"),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_sleep_time(payload: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        record_id = item.get("id")
        day = item.get("day")
        if not record_id or not day:
            continue
        records.append(
            {
                "id": str(record_id),
                "day": str(day),
                "recommendation": item.get("recommendation"),
                "status": item.get("status"),
                "optimal_bedtime_json": _json_or_none(item.get("optimal_bedtime")),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_rest_mode_periods(
    payload: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        record_id = item.get("id")
        start_day = item.get("start_day")
        if not record_id or not start_day:
            continue
        records.append(
            {
                "id": str(record_id),
                "start_day": str(start_day),
                "end_day": item.get("end_day"),
                "start_time": item.get("start_time"),
                "end_time": item.get("end_time"),
                "episodes_json": _json_or_none(item.get("episodes")),
                "raw_json": _raw_json(item),
            }
        )
    return records


def normalize_ring_configuration(
    payload: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for item in payload:
        record_id = item.get("id")
        if not record_id:
            continue
        records.append(
            {
                "id": str(record_id),
                "color": item.get("color"),
                "design": item.get("design"),
                "firmware_version": item.get("firmware_version"),
                "hardware_type": item.get("hardware_type"),
                "set_up_at": item.get("set_up_at"),
                "size": item.get("size"),
                "raw_json": _raw_json(item),
            }
        )
    return records


def upsert_oura_rows(
    conn: sqlite3.Connection,
    daily_rows: Iterable[dict[str, Any]],
    sleep_sessions: Iterable[dict[str, Any]],
    extra_rows: dict[str, Iterable[dict[str, Any]]] | None = None,
) -> None:
    daily_by_day = {str(row["day"]): dict(row) for row in daily_rows if row.get("day")}
    sessions = [dict(session) for session in sleep_sessions]
    for session in sessions:
        day = str(session["day"])
        daily_by_day.setdefault(day, _blank_daily_row(day))

    primary_by_day = canonical_primary_sleep_by_day(sessions)
    for day, primary in primary_by_day.items():
        row = daily_by_day.setdefault(day, _blank_daily_row(day))
        row["primary_bedtime_start"] = primary.get("bedtime_start")
        row["primary_bedtime_end"] = primary.get("bedtime_end")
        row["total_sleep_duration_seconds"] = primary.get("total_sleep_duration_seconds")
        row["deep_sleep_duration_seconds"] = primary.get("deep_sleep_duration_seconds")

    for session in sessions:
        conn.execute(
            """
            INSERT INTO oura_sleep_sessions(
                id, day, type, bedtime_start, bedtime_end,
                total_sleep_duration_seconds, deep_sleep_duration_seconds, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                day = excluded.day,
                type = excluded.type,
                bedtime_start = excluded.bedtime_start,
                bedtime_end = excluded.bedtime_end,
                total_sleep_duration_seconds = excluded.total_sleep_duration_seconds,
                deep_sleep_duration_seconds = excluded.deep_sleep_duration_seconds,
                raw_json = excluded.raw_json
            """,
            (
                session["id"],
                session["day"],
                session["type"],
                session.get("bedtime_start"),
                session.get("bedtime_end"),
                session.get("total_sleep_duration_seconds"),
                session.get("deep_sleep_duration_seconds"),
                session.get("raw_json"),
            ),
        )

    for row in daily_by_day.values():
        _upsert_daily_row(conn, row)

    for name, rows in (extra_rows or {}).items():
        spec = EXTRA_ROW_SPECS[name]
        _upsert_records(
            conn,
            table=str(spec["table"]),
            primary_key=str(spec["primary_key"]),
            columns=tuple(spec["columns"]),
            records=rows,
        )


def canonical_primary_sleep_by_day(
    sessions: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    primary: dict[str, dict[str, Any]] = {}
    for session in sessions:
        if session.get("type") not in SLEEP_TYPES_FOR_PRIMARY:
            continue
        day = str(session.get("day"))
        if not day:
            continue
        if day not in primary or _duration(session) > _duration(primary[day]):
            primary[day] = session
    return primary


def _upsert_daily_row(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    values = [row.get(column) for column in DAILY_COLUMNS]
    update_clause = ", ".join(
        f"{column} = COALESCE(excluded.{column}, oura_daily.{column})"
        for column in DAILY_COLUMNS
    )
    conn.execute(
        f"""
        INSERT INTO oura_daily(day, {", ".join(DAILY_COLUMNS)})
        VALUES ({", ".join("?" for _ in range(len(DAILY_COLUMNS) + 1))})
        ON CONFLICT(day) DO UPDATE SET
            {update_clause},
            updated_at = CURRENT_TIMESTAMP
        """,
        [row["day"], *values],
    )


def _upsert_records(
    conn: sqlite3.Connection,
    *,
    table: str,
    primary_key: str,
    columns: tuple[str, ...],
    records: Iterable[dict[str, Any]],
) -> None:
    update_columns = [column for column in columns if column != primary_key]
    update_clause = ", ".join(
        f"{column} = excluded.{column}" for column in update_columns
    )
    update_clause = f"{update_clause}, updated_at = CURRENT_TIMESTAMP"
    placeholders = ", ".join("?" for _ in columns)
    for record in records:
        conn.execute(
            f"""
            INSERT INTO {table}({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT({primary_key}) DO UPDATE SET
                {update_clause}
            """,
            [record.get(column) for column in columns],
        )


def _blank_daily_row(day: str) -> dict[str, Any]:
    return {"day": day, **{column: None for column in DAILY_COLUMNS}}


def _row_for_day(
    rows: dict[str, dict[str, Any]],
    item: dict[str, Any],
) -> dict[str, Any]:
    day = str(item.get("day") or item.get("date") or "")
    if not day:
        raise ValueError("Oura daily payload is missing a day.")
    return rows.setdefault(day, _blank_daily_row(day))


def _first_present(item: dict[str, Any], *keys: str | tuple[str, ...]) -> Any:
    for key in keys:
        if isinstance(key, tuple):
            value = _nested_get(item, key)
        else:
            value = item.get(key)
        if value is not None:
            return value
    return None


def _nested_get(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    current: Any = item
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _duration(session: dict[str, Any]) -> int:
    value = session.get("total_sleep_duration_seconds")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def _raw_json(item: dict[str, Any]) -> str:
    return json.dumps(item, sort_keys=True)


def _bool_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(bool(value))


def _parse_sample_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _timestamp_unix_ms(value: datetime) -> int | None:
    if value.tzinfo is None:
        return None
    return int(value.timestamp() * 1000)

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


# Mirrors the per-test-file loader convention used elsewhere in this suite
# (e.g. tests/test_health_observation_schema.py); there is no shared conftest.
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
    module = importlib.import_module(spec.name) if spec.name in sys.modules else None
    if module is None:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


@pytest.fixture()
def modules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return {
        "store": load_module("store"),
        "sync_control": load_module("sync_control"),
        "google_health": load_module("google_health"),
    }


def _sample_response():
    return {
        "dataType": "com.google.heart_rate.bpm",
        "userId": "health-user-1",
        "point": [
            {
                "startTime": "2026-06-12T10:00:00Z",
                "endTime": "2026-06-12T10:00:00Z",
                "value": [{"fpVal": 62.0}],
                "dataSource": {
                    "recordingMethod": "automatically_recorded",
                    "platform": "FITBIT",
                    "application": {"packageName": "com.fitbit"},
                    "device": {"type": "WATCH", "uid": "dev-1"},
                },
            }
        ],
    }


def _interval_response():
    return {
        "dataType": "com.google.step_count.delta",
        "userId": "health-user-1",
        "point": [
            {
                "startTime": "2026-06-12T10:00:00Z",
                "endTime": "2026-06-12T10:05:00Z",
                "value": [{"intVal": 540}],
                "dataSource": {"platform": "FITBIT"},
            }
        ],
    }


def _session_response():
    return {
        "dataType": "com.google.sleep.segment",
        "userId": "health-user-1",
        "point": [
            {
                "id": "sleep-session-1",
                "startTime": "2026-06-12T23:10:00Z",
                "endTime": "2026-06-13T06:40:00Z",
                "dataSource": {"platform": "FITBIT"},
            }
        ],
    }


def _daily_response():
    return {
        "dataType": "com.google.step_count.daily",
        "userId": "health-user-1",
        "point": [
            {
                "day": "2026-06-12",
                "value": [{"intVal": 8088}],
                "dataSource": {"platform": "GOOGLE_WEB_API"},
            }
        ],
    }


def test_sample_datapoint_persists_with_provenance_and_lineage(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    with store.connect() as conn:
        google_health.persist_google_health(conn, responses=[_sample_response()])

        row = conn.execute(
            """
            SELECT observation_key, provider_user_id, provider_data_type,
                   metric, metric_unit, value_number, sample_time, provenance_json
            FROM health_sample_observations
            """
        ).fetchall()
        assert len(row) == 1
        (
            observation_key,
            provider_user_id,
            provider_data_type,
            metric,
            metric_unit,
            value_number,
            sample_time,
            provenance_json,
        ) = tuple(row[0])
        assert provider_user_id == "health-user-1"
        assert provider_data_type == "com.google.heart_rate.bpm"
        assert metric == "heart_rate"
        assert metric_unit == "bpm"
        assert value_number == 62.0
        assert sample_time == "2026-06-12T10:00:00Z"
        assert json.loads(provenance_json)["platform"] == "FITBIT"

        # Raw payload persisted and linked back to the canonical row.
        lineage = conn.execute(
            """
            SELECT rr.object_type
            FROM record_lineage rl
            JOIN raw_records rr ON rr.raw_record_id = rl.raw_record_id
            WHERE rl.canonical_table = 'health_sample_observations'
              AND rl.canonical_id = ?
            """,
            (observation_key,),
        ).fetchall()
        assert len(lineage) == 1


def test_interval_datapoint_persists(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    with store.connect() as conn:
        google_health.persist_google_health(conn, responses=[_interval_response()])

        rows = conn.execute(
            """
            SELECT metric, metric_unit, value_number, start_time, end_time
            FROM health_interval_observations
            """
        ).fetchall()
        assert len(rows) == 1
        metric, metric_unit, value_number, start_time, end_time = tuple(rows[0])
        assert metric == "steps"
        assert metric_unit == "count"
        assert value_number == 540
        assert start_time == "2026-06-12T10:00:00Z"
        assert end_time == "2026-06-12T10:05:00Z"


def test_session_datapoint_persists(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    with store.connect() as conn:
        google_health.persist_google_health(conn, responses=[_session_response()])

        rows = conn.execute(
            """
            SELECT session_key, session_type, day, start_time, end_time, duration_seconds
            FROM health_sessions
            """
        ).fetchall()
        assert len(rows) == 1
        session_key, session_type, day, start_time, end_time, duration = tuple(rows[0])
        assert session_type == "sleep"
        assert day == "2026-06-12"
        assert start_time == "2026-06-12T23:10:00Z"
        assert end_time == "2026-06-13T06:40:00Z"
        assert duration == 7 * 3600 + 30 * 60


def test_daily_rollup_persists_with_aggregation_kind(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    with store.connect() as conn:
        google_health.persist_google_health(conn, responses=[_daily_response()])

        rows = conn.execute(
            """
            SELECT day, metric, value_number, aggregation_kind
            FROM daily_health_metrics
            """
        ).fetchall()
        assert len(rows) == 1
        day, metric, value_number, aggregation_kind = tuple(rows[0])
        assert day == "2026-06-12"
        assert metric == "steps"
        assert value_number == 8088
        assert aggregation_kind == "provider_daily_summary"


def test_name_absent_points_get_deterministic_distinct_keys(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    response = _sample_response()
    response["point"].append(
        {
            "startTime": "2026-06-12T10:01:00Z",
            "endTime": "2026-06-12T10:01:00Z",
            "value": [{"fpVal": 64.0}],
            "dataSource": {"platform": "FITBIT"},
        }
    )

    with store.connect() as conn:
        # Neither point carries DataPoint.name; both must still persist distinctly.
        google_health.persist_google_health(conn, responses=[response])
        count = conn.execute(
            "SELECT COUNT(*) FROM health_sample_observations"
        ).fetchone()[0]
    assert count == 2


def test_reingest_is_idempotent(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    responses = [
        _sample_response(),
        _interval_response(),
        _session_response(),
        _daily_response(),
    ]
    with store.connect() as conn:
        google_health.persist_google_health(conn, responses=responses)
        google_health.persist_google_health(conn, responses=responses)

        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "health_sample_observations",
                "health_interval_observations",
                "health_sessions",
                "daily_health_metrics",
                "raw_records",
                "record_lineage",
            )
        }
    assert counts["health_sample_observations"] == 1
    assert counts["health_interval_observations"] == 1
    assert counts["health_sessions"] == 1
    assert counts["daily_health_metrics"] == 1
    assert counts["raw_records"] == 4
    assert counts["record_lineage"] == 4


def test_unregistered_datatype_is_skipped(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    unknown = {
        "dataType": "com.google.unsupported.metric",
        "userId": "health-user-1",
        "point": [
            {
                "startTime": "2026-06-12T10:00:00Z",
                "endTime": "2026-06-12T10:00:00Z",
                "value": [{"fpVal": 1.0}],
            }
        ],
    }
    with store.connect() as conn:
        # No registry entry -> skipped quietly, no rows, no raw records.
        google_health.persist_google_health(conn, responses=[unknown])
        sample = conn.execute(
            "SELECT COUNT(*) FROM health_sample_observations"
        ).fetchone()[0]
        raw = conn.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0]
    assert sample == 0
    assert raw == 0


def test_derive_key_is_collision_safe(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    # Two distinct points whose data_type/name/time parts would collide under a naive
    # ':'-join ("...bpm:a:b:2026-06-12T11:00:00Z" for both). They must persist as two
    # rows, not silently overwrite each other.
    response = {
        "dataType": "com.google.heart_rate.bpm",
        "userId": "health-user-1",
        "point": [
            {
                "name": "a:b",
                "startTime": "2026-06-12T11:00:00Z",
                "endTime": "2026-06-12T11:00:00Z",
                "value": [{"fpVal": 1.0}],
            },
            {
                "name": "a",
                "startTime": "b:2026-06-12T11:00:00Z",
                "endTime": "b:2026-06-12T11:00:00Z",
                "value": [{"fpVal": 2.0}],
            },
        ],
    }
    with store.connect() as conn:
        google_health.persist_google_health(conn, responses=[response])
        count = conn.execute(
            "SELECT COUNT(*) FROM health_sample_observations"
        ).fetchone()[0]
    assert count == 2


def test_out_of_order_interval_is_skipped_without_aborting_batch(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    bad_interval = {
        "dataType": "com.google.step_count.delta",
        "userId": "health-user-1",
        "point": [
            {
                "startTime": "2026-06-12T10:05:00Z",
                "endTime": "2026-06-12T10:00:00Z",
                "value": [{"intVal": 10}],
            }
        ],
    }
    with store.connect() as conn:
        # The reversed interval must be skipped, and must NOT abort the good sample
        # response that follows it in the same batch.
        google_health.persist_google_health(
            conn, responses=[bad_interval, _sample_response()]
        )
        interval_count = conn.execute(
            "SELECT COUNT(*) FROM health_interval_observations"
        ).fetchone()[0]
        sample_count = conn.execute(
            "SELECT COUNT(*) FROM health_sample_observations"
        ).fetchone()[0]
    assert interval_count == 0
    assert sample_count == 1


def test_int_zero_value_is_preserved_as_true_zero(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    response = {
        "dataType": "com.google.step_count.delta",
        "userId": "health-user-1",
        "point": [
            {
                "startTime": "2026-06-12T10:00:00Z",
                "endTime": "2026-06-12T10:05:00Z",
                "value": [{"intVal": 0}],
            }
        ],
    }
    with store.connect() as conn:
        # A recorded zero is a true zero, not missing data.
        google_health.persist_google_health(conn, responses=[response])
        value = conn.execute(
            "SELECT value_number FROM health_interval_observations"
        ).fetchone()[0]
    assert value == 0.0


def test_provider_aggregation_kind_is_ignored_and_does_not_abort_batch(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    daily_bogus = {
        "dataType": "com.google.step_count.daily",
        "userId": "health-user-1",
        "point": [
            {
                "day": "2026-06-12",
                "aggregationKind": "hourly_bucket",
                "value": [{"intVal": 8088}],
            }
        ],
    }
    with store.connect() as conn:
        # An out-of-set provider aggregationKind must not reach the CHECK column and
        # must not abort the good sample response queued after it.
        google_health.persist_google_health(
            conn, responses=[daily_bogus, _sample_response()]
        )
        daily = conn.execute(
            "SELECT aggregation_kind FROM daily_health_metrics"
        ).fetchall()
        sample_count = conn.execute(
            "SELECT COUNT(*) FROM health_sample_observations"
        ).fetchone()[0]
    assert len(daily) == 1
    assert tuple(daily[0])[0] == "provider_daily_summary"
    assert sample_count == 1


def test_non_numeric_value_does_not_abort_batch(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    bad_value = {
        "dataType": "com.google.heart_rate.bpm",
        "userId": "health-user-1",
        "point": [
            {
                "startTime": "2026-06-12T09:00:00Z",
                "endTime": "2026-06-12T09:00:00Z",
                "value": [{"fpVal": "abc"}],
            }
        ],
    }
    with store.connect() as conn:
        # A non-numeric value persists with a NULL value_number rather than raising
        # and aborting the good interval response that follows it.
        google_health.persist_google_health(
            conn, responses=[bad_value, _interval_response()]
        )
        sample = conn.execute(
            "SELECT value_number FROM health_sample_observations"
        ).fetchall()
        interval_count = conn.execute(
            "SELECT COUNT(*) FROM health_interval_observations"
        ).fetchone()[0]
    assert len(sample) == 1
    assert tuple(sample[0])[0] is None
    assert interval_count == 1


def _set_profile_timezone(conn, tz_name):
    conn.execute(
        """
        INSERT INTO health_profile(
            id, timezone, goals_json, already_uses_json, privacy_json, routine_json
        )
        VALUES ('default', ?, '[]', '[]', '{}', '{}')
        ON CONFLICT(id) DO UPDATE SET timezone = excluded.timezone
        """,
        (tz_name,),
    )


def test_session_day_uses_profile_timezone_tokyo(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    with store.connect() as conn:
        _set_profile_timezone(conn, "Asia/Tokyo")
        # 2026-06-12T23:10:00Z is 2026-06-13 08:10 in Tokyo (UTC+9): the session
        # belongs to the user's local day 06-13, not the UTC day 06-12.
        google_health.persist_google_health(conn, responses=[_session_response()])
        day = conn.execute("SELECT day FROM health_sessions").fetchone()[0]
    assert day == "2026-06-13"


def test_session_day_uses_profile_timezone_california(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    session = {
        "dataType": "com.google.sleep.segment",
        "userId": "health-user-1",
        "point": [
            {
                "id": "sleep-ca-1",
                "startTime": "2026-06-13T05:00:00Z",
                "endTime": "2026-06-13T12:30:00Z",
                "dataSource": {"platform": "FITBIT"},
            }
        ],
    }
    with store.connect() as conn:
        _set_profile_timezone(conn, "America/Los_Angeles")
        # 2026-06-13T05:00:00Z is 2026-06-12 22:00 PDT (UTC-7): local day 06-12.
        google_health.persist_google_health(conn, responses=[session])
        day = conn.execute("SELECT day FROM health_sessions").fetchone()[0]
    assert day == "2026-06-12"


def test_invalid_profile_timezone_falls_back_to_utc_day(modules):
    store = modules["store"]
    google_health = modules["google_health"]
    store.initialize()

    with store.connect() as conn:
        _set_profile_timezone(conn, "Not/AZone")
        # An unknown timezone must not raise; fall back to the UTC calendar day.
        google_health.persist_google_health(conn, responses=[_session_response()])
        day = conn.execute("SELECT day FROM health_sessions").fetchone()[0]
    assert day == "2026-06-12"

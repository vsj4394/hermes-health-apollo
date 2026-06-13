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

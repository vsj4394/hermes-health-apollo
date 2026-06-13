from __future__ import annotations

import importlib.util
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
        "semantic_layer": load_module("semantic_layer"),
    }


def test_store_connect_enforces_foreign_keys(modules):
    store = modules["store"]
    store.initialize()

    with store.connect() as conn:
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert enabled == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO source_scopes(
                    scope_id, source_id, scope_key, scope_label, granted_at,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "scope-missing-source",
                    "missing-source",
                    "health.activity.read",
                    "Activity",
                    "2026-06-12T10:00:00Z",
                    "{}",
                    "2026-06-12T10:00:00Z",
                    "2026-06-12T10:00:00Z",
                ),
            )


def test_google_health_default_source_is_registered(modules):
    store = modules["store"]
    sync_control = modules["sync_control"]
    store.initialize()

    with store.connect() as conn:
        source_id = sync_control.ensure_default_source(conn, "google_health")
        row = conn.execute(
            """
            SELECT source_slug, provider, connection_name, status, sync_mode
            FROM health_sources
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()

    assert tuple(row) == (
        "google_health",
        "google_health",
        "Google Health",
        "disconnected",
        "pull",
    )


def test_health_canonical_tables_exist(modules):
    store = modules["store"]
    store.initialize()

    expected = {
        "health_sample_observations",
        "health_interval_observations",
        "health_sessions",
        "daily_health_metrics",
    }
    with store.connect() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert expected <= existing


def test_health_observation_indexes_exist(modules):
    store = modules["store"]
    store.initialize()

    expected = {
        "idx_health_sample_observations_metric_time",
        "idx_health_sample_observations_time",
        "idx_health_interval_observations_metric_time",
        "idx_health_interval_observations_time",
        "idx_health_sessions_source_day",
        "idx_health_sessions_type_day",
        "idx_daily_health_metrics_day_metric",
        "idx_daily_health_metrics_source_day",
    }
    with store.connect() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }

    assert expected <= existing


def test_sample_observation_source_and_identity_contracts(modules):
    store = modules["store"]
    sync_control = modules["sync_control"]
    store.initialize()

    with store.connect() as conn:
        google_source = sync_control.ensure_default_source(conn, "google_health")
        second_source = sync_control.ensure_source(
            conn,
            source_slug="secondary_health_source",
            provider="test_provider",
            connection_name="Secondary Health Source",
            status="connected",
            sync_mode="pull",
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO health_sample_observations(
                    source_id, observation_key, provider_data_type, metric,
                    sample_time, value_number, metric_unit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "not-a-real-source",
                    "heart-rate:2026-06-12T10:00:00Z",
                    "heart-rate",
                    "heart_rate_bpm",
                    "2026-06-12T10:00:00Z",
                    72.0,
                    "bpm",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO health_sample_observations(
                    source_id, observation_key, provider_data_type, metric,
                    sample_time, value_number, metric_unit
                )
                VALUES (?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    google_source,
                    "heart-rate",
                    "heart_rate_bpm",
                    "2026-06-12T10:00:00Z",
                    72.0,
                    "bpm",
                ),
            )

        for source_id in (google_source, second_source):
            conn.execute(
                """
                INSERT INTO health_sample_observations(
                    source_id, observation_key, provider_data_type, metric,
                    sample_time, value_number, metric_unit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    "same-derived-key",
                    "heart-rate",
                    "heart_rate_bpm",
                    "2026-06-12T10:00:00Z",
                    72.0,
                    "bpm",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO health_sample_observations(
                    source_id, observation_key, provider_data_type, metric,
                    sample_time, value_number, metric_unit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    google_source,
                    "same-derived-key",
                    "heart-rate",
                    "heart_rate_bpm",
                    "2026-06-12T10:01:00Z",
                    73.0,
                    "bpm",
                ),
            )

        count = conn.execute(
            "SELECT COUNT(*) FROM health_sample_observations"
        ).fetchone()[0]

    assert count == 2


def test_interval_observation_contracts(modules):
    store = modules["store"]
    sync_control = modules["sync_control"]
    store.initialize()

    with store.connect() as conn:
        source_id = sync_control.ensure_default_source(conn, "google_health")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO health_interval_observations(
                    source_id, observation_key, provider_data_type, metric,
                    start_time, end_time, value_number, metric_unit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "not-a-real-source",
                    "steps:bad-source",
                    "step-count",
                    "steps",
                    "2026-06-12T10:00:00Z",
                    "2026-06-12T10:05:00Z",
                    100.0,
                    "count",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO health_interval_observations(
                    source_id, observation_key, provider_data_type, metric,
                    start_time, end_time, value_number, metric_unit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    "steps:reversed",
                    "step-count",
                    "steps",
                    "2026-06-12T10:05:00Z",
                    "2026-06-12T10:00:00Z",
                    100.0,
                    "count",
                ),
            )

        conn.execute(
            """
            INSERT INTO health_interval_observations(
                source_id, observation_key, provider_data_type, metric,
                start_time, end_time, value_number, metric_unit
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                "steps:2026-06-12T10:00:00Z:2026-06-12T10:05:00Z",
                "step-count",
                "steps",
                "2026-06-12T10:00:00Z",
                "2026-06-12T10:05:00Z",
                100.0,
                "count",
            ),
        )

        count = conn.execute(
            "SELECT COUNT(*) FROM health_interval_observations"
        ).fetchone()[0]

    assert count == 1


def test_session_key_is_required_and_source_scoped(modules):
    store = modules["store"]
    sync_control = modules["sync_control"]
    store.initialize()

    with store.connect() as conn:
        google_source = sync_control.ensure_default_source(conn, "google_health")
        second_source = sync_control.ensure_source(
            conn,
            source_slug="secondary_session_source",
            provider="test_provider",
            connection_name="Secondary Session Source",
            status="connected",
            sync_mode="pull",
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO health_sessions(
                    source_id, session_key, session_type, day, start_time
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "not-a-real-source",
                    "unknown-source-session",
                    "sleep",
                    "2026-06-12",
                    "2026-06-11T22:30:00Z",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO health_sessions(
                    source_id, session_key, session_type, day, start_time
                )
                VALUES (?, NULL, ?, ?, ?)
                """,
                (
                    google_source,
                    "sleep",
                    "2026-06-12",
                    "2026-06-11T22:30:00Z",
                ),
            )

        for source_id in (google_source, second_source):
            conn.execute(
                """
                INSERT INTO health_sessions(
                    source_id, session_key, session_type, day, start_time,
                    end_time, duration_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    "same-session-key",
                    "sleep",
                    "2026-06-12",
                    "2026-06-11T22:30:00Z",
                    "2026-06-12T06:30:00Z",
                    28800,
                ),
            )

        count = conn.execute("SELECT COUNT(*) FROM health_sessions").fetchone()[0]

    assert count == 2


def test_daily_health_metrics_identity_and_aggregation_kind(modules):
    store = modules["store"]
    sync_control = modules["sync_control"]
    store.initialize()

    with store.connect() as conn:
        source_id = sync_control.ensure_default_source(conn, "google_health")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO daily_health_metrics(
                    day, source_id, metric, aggregation_kind, value_number, metric_unit
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "2026-06-12",
                    "not-a-real-source",
                    "steps",
                    "provider_daily_summary",
                    8088,
                    "count",
                ),
            )
        conn.execute(
            """
            INSERT INTO daily_health_metrics(
                day, source_id, metric, aggregation_kind, value_number, metric_unit
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-06-12",
                source_id,
                "steps",
                "provider_daily_summary",
                8088,
                "count",
            ),
        )
        conn.execute(
            """
            INSERT INTO daily_health_metrics(
                day, source_id, metric, aggregation_kind, value_number, metric_unit
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-06-12",
                source_id,
                "steps",
                "provider_rollup",
                8000,
                "count",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO daily_health_metrics(
                    day, source_id, metric, aggregation_kind, value_number, metric_unit
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "2026-06-12",
                    source_id,
                    "steps",
                    "provider_daily_summary",
                    9000,
                    "count",
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO daily_health_metrics(
                    day, source_id, metric, aggregation_kind, value_number, metric_unit
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "2026-06-12",
                    source_id,
                    "steps",
                    "unknown_aggregation",
                    9000,
                    "count",
                ),
            )

        count = conn.execute("SELECT COUNT(*) FROM daily_health_metrics").fetchone()[0]

    assert count == 2

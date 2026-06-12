from __future__ import annotations

import importlib
import sqlite3
import sys
import types
from pathlib import Path

import pytest

from tests.health_fixtures import seed_query_days, seed_workout_rows


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str):
    package_name = "hermes_plugins.health_data"
    sys.modules.setdefault("hermes_plugins", types.ModuleType("hermes_plugins"))
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        package.__path__ = [str(ROOT)]
        sys.modules[package_name] = package
    sys.modules.pop(f"{package_name}.{name}", None)
    return importlib.import_module(f"{package_name}.{name}")


@pytest.fixture()
def modules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return {
        "store": load_module("store"),
        "semantic_layer": load_module("semantic_layer"),
    }


def test_ensure_canonical_schema_creates_analysis_tables_and_indexes(modules):
    store = modules["store"]
    semantic = modules["semantic_layer"]
    store.initialize()

    with sqlite3.connect(store.database_path()) as conn:
        semantic.ensure_canonical_schema(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            )
        }

    assert {
        "entities",
        "events",
        "event_entities",
        "observations",
        "features",
        "analysis_runs",
        "idx_events_type_day",
        "idx_observations_signal_day",
        "idx_features_lookup",
    }.issubset(tables)


def test_canonical_tables_enforce_uniqueness_for_projection_targets(modules):
    store = modules["store"]
    semantic = modules["semantic_layer"]
    store.initialize()

    with sqlite3.connect(store.database_path()) as conn:
        semantic.ensure_canonical_schema(conn)
        conn.execute(
            """
            INSERT INTO entities(entity_id, entity_type, canonical_key, display_name, privacy_class)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("food:coffee", "food", "coffee", "coffee", "private"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO entities(entity_id, entity_type, canonical_key, display_name, privacy_class)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("food:coffee:duplicate", "food", "coffee", "coffee", "private"),
            )


def test_refresh_canonical_facts_projects_food_workout_sleep_and_daily_context(modules):
    store = modules["store"]
    semantic = modules["semantic_layer"]
    seed_query_days(store)
    seed_workout_rows(store)

    semantic.refresh_canonical_facts(start="2026-06-01", end="2026-06-03")

    with sqlite3.connect(store.database_path()) as conn:
        event_rows = {
            tuple(row)
            for row in conn.execute(
                "SELECT event_type, provider, day FROM events ORDER BY event_type, day"
            )
        }
        observation_rows = {
            tuple(row)
            for row in conn.execute(
                """
                SELECT signal_name, day, CAST(value_number AS INTEGER)
                FROM observations
                ORDER BY signal_name, day
                """
            )
        }

    assert ("meal", "manual_food", "2026-06-01") in event_rows
    assert ("workout", "oura", "2026-06-02") in event_rows
    assert ("sleep_session", "oura", "2026-06-03") in event_rows
    assert ("calendar_day", "google_workspace", "2026-06-02") in event_rows
    assert ("email_day", "google_workspace", "2026-06-02") in event_rows
    assert ("stress_high_seconds", "2026-06-02", 7200) in observation_rows
    assert ("sleep_score", "2026-06-03", 82) in observation_rows

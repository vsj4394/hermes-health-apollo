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
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def modules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return {
        "store": load_module("store"),
        "query": load_module("query"),
        "food": load_module("food"),
    }


def test_migrations_create_spec_tables_and_view(modules):
    store = modules["store"]

    store.initialize()

    with sqlite3.connect(store.database_path()) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(oura_daily)")
        }

    assert {
        "oura_daily",
        "oura_sleep_sessions",
        "calendar_daily",
        "email_daily",
        "food_logs",
        "sync_state",
        "schema_version",
        "daily_overview",
    }.issubset(tables)
    assert {"primary_bedtime_start", "primary_bedtime_end"}.issubset(columns)


def test_sync_guard_is_database_backed_and_released(modules):
    store = modules["store"]
    store.initialize()

    with store.sync_guard("oura"):
        with pytest.raises(store.SyncAlreadyRunning):
            with store.sync_guard("oura"):
                pass

    with sqlite3.connect(store.database_path()) as conn:
        status = conn.execute(
            "SELECT last_status FROM sync_state WHERE provider = 'oura'"
        ).fetchone()[0]

    assert status == "ok"


def test_sync_guard_marks_error_after_body_failure(modules):
    store = modules["store"]
    store.initialize()

    with pytest.raises(RuntimeError, match="boom"):
        with store.sync_guard("oura"):
            raise RuntimeError("boom")

    with sqlite3.connect(store.database_path()) as conn:
        status = conn.execute(
            "SELECT last_status FROM sync_state WHERE provider = 'oura'"
        ).fetchone()[0]

    assert status == "error"
    with store.sync_guard("oura"):
        pass


def test_sleep_consistency_uses_minutes_since_noon_across_midnight(modules):
    query = modules["query"]

    values = [
        "2026-06-01T23:50:00-04:00",
        "2026-06-02T00:10:00-04:00",
        "2026-06-02T23:55:00-04:00",
    ]

    assert query.sleep_consistency_minutes(values) == pytest.approx(8.498, rel=1e-3)


def test_date_range_reads_food_calories_from_items_json(modules):
    store = modules["store"]
    query = modules["query"]
    store.initialize()

    with sqlite3.connect(store.database_path()) as conn:
        conn.execute(
            """
            INSERT INTO oura_daily(day, readiness_score, sleep_score, stress_high_seconds)
            VALUES ('2026-06-06', 78, 82, 3600)
            """
        )
        conn.execute(
            """
            INSERT INTO food_logs(id, day, logged_at, description, items_json)
            VALUES (?, '2026-06-06', '2026-06-06T18:00:00Z', 'dinner', ?)
            """,
            (
                "food-1",
                json.dumps(
                    {
                        "items": [{"name": "rice bowl"}],
                        "total_estimated_calories": 640,
                    }
                ),
            ),
        )

    rows = query.health_query(
        {"query_type": "date_range", "start": "2026-06-06", "end": "2026-06-06"}
    )

    assert rows["days"][0]["food_total_estimated_calories"] == 640


def test_malformed_food_analysis_returns_description_without_food_row(modules):
    store = modules["store"]
    food = modules["food"]
    store.initialize()

    result = food.log_food(
        day="2026-06-06",
        description="photo showed a sandwich",
        analysis_text="```json\n{bad json}\n```",
    )

    with sqlite3.connect(store.database_path()) as conn:
        rows = conn.execute("SELECT description, items_json FROM food_logs").fetchall()

    assert result["items_json"] is None
    assert rows == []

from __future__ import annotations

import importlib
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
        "analysis_tools": load_module("analysis_tools"),
    }


def test_health_feature_query_materializes_daily_features(modules):
    store = modules["store"]
    semantic = modules["semantic_layer"]
    analysis_tools = modules["analysis_tools"]
    seed_query_days(store)
    semantic.refresh_canonical_facts(start="2026-06-01", end="2026-06-14")

    result = analysis_tools.health_feature_query(
        {
            "features": [
                "sleep_score",
                "meeting_minutes",
                "email_received_count",
                "meal_count",
                "late_meal_flag",
            ],
            "start": "2026-06-01",
            "end": "2026-06-03",
            "grain": "day",
        }
    )

    rows = result["rows"]
    assert rows[0]["day"] == "2026-06-01"
    assert rows[1]["meeting_minutes"] == 240
    assert rows[1]["email_received_count"] == 80
    assert rows[1]["meal_count"] == 1
    assert rows[1]["late_meal_flag"] == 1
    assert "provenance" in rows[1]


def test_feature_missingness_is_null_for_unlogged_food_not_zero(modules):
    store = modules["store"]
    semantic = modules["semantic_layer"]
    analysis_tools = modules["analysis_tools"]
    seed_query_days(store)
    semantic.refresh_canonical_facts(start="2026-06-01", end="2026-06-14")

    result = analysis_tools.health_feature_query(
        {
            "features": ["meal_count", "food_total_estimated_calories"],
            "start": "2026-06-03",
            "end": "2026-06-03",
            "grain": "day",
        }
    )

    assert result["rows"] == [
        {
            "day": "2026-06-03",
            "meal_count": None,
            "food_total_estimated_calories": None,
            "provenance": {
                "meal_count": {"coverage": "missing"},
                "food_total_estimated_calories": {"coverage": "missing"},
            },
        }
    ]


def test_feature_registry_includes_recovery_high_seconds_for_recovery_analysis(modules):
    store = modules["store"]
    analysis_tools = modules["analysis_tools"]
    seed_query_days(store)
    seed_workout_rows(store)

    result = analysis_tools.health_feature_query(
        {
            "features": ["workout_count", "recovery_high_seconds"],
            "start": "2026-06-01",
            "end": "2026-06-02",
            "grain": "day",
        }
    )

    assert result["rows"][1]["workout_count"] == 1
    assert result["rows"][1]["recovery_high_seconds"] == 5400

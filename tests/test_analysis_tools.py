from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

from tests.health_fixtures import (
    seed_query_days,
    seed_thin_food_fixture,
    seed_workout_rows,
)


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


def seed_workout_habit(store, semantic, *, expected_weekdays: list[int] | None = None):
    import json
    import sqlite3

    expected_weekdays = expected_weekdays or [1, 3, 5]
    store.initialize()
    with sqlite3.connect(store.database_path()) as conn:
        semantic.ensure_canonical_schema(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO entities(
                entity_id, entity_type, canonical_key, display_name, attributes_json, privacy_class
            )
            VALUES (?, 'habit', 'fixture-workout-routine', 'Fixture workout routine', ?, 'private')
            """,
            (
                "habit:fixture-workout-routine",
                json.dumps({"expected_weekdays": expected_weekdays}, sort_keys=True),
            ),
        )


def test_health_analysis_plan_routes_supported_questions():
    analysis_tools = load_module("analysis_tools")

    assert analysis_tools.health_analysis_plan(
        {"question": "Which foods seem to hurt my sleep?", "today": "2026-06-11"}
    ) == {
        "question": "Which foods seem to hurt my sleep?",
        "candidate_analyses": [
            {
                "analysis_id": "food_sleep_association",
                "display_name": "Food and sleep association",
                "default_window_days": 90,
                "requires_follow_up": False,
            }
        ],
        "needs_sync": False,
        "next_tools": ["health_coverage", "health_analyze"],
    }


@pytest.mark.parametrize(
    ("method_name", "args", "missing_fields"),
    [
        ("health_feature_query", {}, ["features", "start", "end"]),
        ("health_analysis_plan", {}, ["question"]),
        ("health_analyze", {}, ["analysis_id", "start", "end"]),
        ("health_analysis_explain", {}, ["analysis_run_id"]),
    ],
)
def test_analysis_tools_return_structured_errors_for_missing_required_args(
    method_name: str,
    args: dict,
    missing_fields: list[str],
):
    analysis_tools = load_module("analysis_tools")

    result = getattr(analysis_tools, method_name)(args)

    assert result["ok"] is False
    assert result["error"] == "Missing required arguments."
    assert result["missing"] == missing_fields


def test_health_analysis_plan_directs_broad_workload_wellbeing_question():
    analysis_tools = load_module("analysis_tools")

    result = analysis_tools.health_analysis_plan(
        {
            "question": (
                "Over the last 30 days, do heavier meeting or email days line up "
                "with worse stress, sleep, or readiness?"
            ),
            "today": "2026-06-30",
        }
    )

    assert result["candidate_analyses"] == [
        {
            "analysis_id": "calendar_email_stress_association",
            "display_name": "Calendar and email stress association",
            "default_window_days": 90,
            "requires_follow_up": False,
        }
    ]
    assert result["routing_confidence"] == "high"
    assert result["next_tools"] == ["health_analyze"]
    assert result["direct_tool"] == {
        "name": "health_analyze",
        "args": {
            "analysis_id": "calendar_email_stress_association",
            "question": result["question"],
            "start": "2026-06-01",
            "end": "2026-06-30",
            "target": "stress_sleep_readiness",
            "params": {"route": "broad_workload_wellbeing"},
        },
    }


def test_health_analyze_calendar_email_stress_returns_results_and_caveats(modules):
    store = modules["store"]
    semantic = modules["semantic_layer"]
    analysis_tools = modules["analysis_tools"]
    seed_query_days(store)
    semantic.refresh_canonical_facts(start="2026-06-01", end="2026-06-14")

    result = analysis_tools.health_analyze(
        {
            "analysis_id": "calendar_email_stress_association",
            "start": "2026-06-01",
            "end": "2026-06-14",
            "target": "stress_high_seconds",
            "params": {},
        }
    )

    assert result["eligible"] is True
    assert result["method"] == "cohort_contrast"
    assert result["sample_size"]["outcome_days"] == 14
    assert result["results"]["meeting_minutes"]["higher_signal_mean"] == 240
    assert result["results"]["email_received_count"]["higher_signal_mean"] == 80
    assert "associated with" in result["answer_hints"][0]
    assert result["analysis_run_id"]


def test_health_analyze_refuses_on_thin_food_sleep_data(modules):
    store = modules["store"]
    semantic = modules["semantic_layer"]
    analysis_tools = modules["analysis_tools"]
    seed_thin_food_fixture(store)
    semantic.refresh_canonical_facts(start="2026-03-13", end="2026-06-11")

    result = analysis_tools.health_analyze(
        {
            "analysis_id": "food_sleep_association",
            "start": "2026-03-13",
            "end": "2026-06-11",
            "target": "sleep_score",
            "params": {},
        }
    )

    assert result["eligible"] is False
    assert result["reason"] == "minimum_sample_size_not_met"
    assert result["sample_size"]["meal_logged_nights"] == 3
    assert result["caveats"] == [
        "Only 3 meal-logged nights are available; 4 exposed and 4 unexposed nights are required."
    ]


def test_health_analyze_exercise_adherence_lists_missed_routine_days(modules):
    store = modules["store"]
    semantic = modules["semantic_layer"]
    analysis_tools = modules["analysis_tools"]
    seed_query_days(store)
    seed_workout_rows(store)
    seed_workout_habit(store, semantic, expected_weekdays=[1, 3, 5])

    result = analysis_tools.health_analyze(
        {
            "analysis_id": "exercise_adherence",
            "start": "2026-06-01",
            "end": "2026-06-14",
            "params": {},
        }
    )

    assert result["eligible"] is True
    assert result["method"] == "adherence"
    assert "2026-06-04" in result["results"]["missed_days"]
    assert result["sample_size"]["routine_days"] >= 6


def test_health_analysis_explain_returns_feature_keys_and_provenance(modules):
    import sqlite3

    store = modules["store"]
    semantic = modules["semantic_layer"]
    analysis_tools = modules["analysis_tools"]
    feature_engineering = load_module("feature_engineering")
    seed_query_days(store)
    semantic.refresh_canonical_facts(start="2026-06-01", end="2026-06-14")
    analyzed = analysis_tools.health_analyze(
        {
            "analysis_id": "calendar_email_stress_association",
            "question": "Did heavy work days line up with worse stress or sleep?",
            "start": "2026-06-01",
            "end": "2026-06-14",
            "target": "stress_high_seconds",
            "params": {},
        }
    )
    seed_query_days(store, start="2026-07-01", day_count=2)
    feature_engineering.materialize_features(
        feature_keys=[
            "meeting_minutes",
            "email_received_count",
            "stress_high_seconds",
            "sleep_score",
            "readiness_score",
        ],
        start="2026-07-01",
        end="2026-07-02",
        grain="day",
    )

    explanation = analysis_tools.health_analysis_explain(
        {"analysis_run_id": analyzed["analysis_run_id"]}
    )
    with sqlite3.connect(store.database_path()) as conn:
        stored_question = conn.execute(
            "SELECT question FROM analysis_runs WHERE run_id = ?",
            (analyzed["analysis_run_id"],),
        ).fetchone()[0]

    assert stored_question == "Did heavy work days line up with worse stress or sleep?"
    assert explanation["analysis_id"] == "calendar_email_stress_association"
    assert explanation["question"] == "Did heavy work days line up with worse stress or sleep?"
    assert explanation["feature_keys"] == [
        "meeting_minutes",
        "email_received_count",
        "stress_high_seconds",
        "sleep_score",
        "readiness_score",
    ]
    assert explanation["source_tables"] == ["calendar_daily", "email_daily", "oura_daily"]
    assert explanation["row_counts"]["feature_rows"] >= 3
    assert explanation["caveats"]
    assert explanation["source_refs"]
    assert {"feature_id", "feature_key", "feature_ts", "provenance"}.issubset(
        explanation["source_refs"][0]
    )
    assert all(
        "2026-06-01" <= source_ref["feature_ts"] <= "2026-06-14"
        for source_ref in explanation["source_refs"]
    )
    assert explanation["coverage"]["oura"]["row_count"] == 14

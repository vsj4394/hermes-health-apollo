"""Deterministic Plan B analytics-platform lane tests."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sqlite3
import sys
import types
from pathlib import Path

from .build_analytics_fixture import build_analytics_fixture

ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str):
    package_name = "hermes_plugins.health_data"
    sys.modules.setdefault("hermes_plugins", types.ModuleType("hermes_plugins"))
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        package.__path__ = [str(ROOT)]
        sys.modules[package_name] = package
    sys.modules.pop(f"{package_name}.{name}", None)
    return importlib.import_module(f"{package_name}.{name}")


def _load_analysis_plugin(tmp_path: Path, *, variant: str = "base"):
    home = tmp_path / "home"
    home.mkdir()
    db_path = build_analytics_fixture(tmp_path / "fixture.db", variant=variant)
    shutil.copy2(db_path, home / "health.db")
    os.environ["HERMES_HOME"] = str(home)
    return types.SimpleNamespace(
        store=_load_module("store"),
        semantic_layer=_load_module("semantic_layer"),
        health_coverage=_load_module("analysis_tools").health_coverage,
        health_event_query=_load_module("analysis_tools").health_event_query,
        health_feature_query=_load_module("analysis_tools").health_feature_query,
        health_analysis_catalog=_load_module("analysis_tools").health_analysis_catalog,
        health_analysis_plan=_load_module("analysis_tools").health_analysis_plan,
        health_analyze=_load_module("analysis_tools").health_analyze,
        health_analysis_explain=_load_module("analysis_tools").health_analysis_explain,
    )


def _seed_habit(plugin) -> None:
    with sqlite3.connect(plugin.store.database_path()) as conn:
        plugin.semantic_layer.ensure_canonical_schema(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO entities(
                entity_id, entity_type, canonical_key, display_name, attributes_json, privacy_class
            )
            VALUES (?, 'habit', 'fixture-workout-routine', 'Fixture workout routine', ?, 'private')
            """,
            (
                "habit:fixture-workout-routine",
                json.dumps({"expected_weekdays": [1, 3, 5]}, sort_keys=True),
            ),
        )


def test_hap_e01_normal_chat_health_routing_contract(tmp_path):
    plugin = _load_analysis_plugin(tmp_path)

    plan = plugin.health_analysis_plan(
        {"question": "How did I sleep last night?", "today": "2026-06-11"}
    )
    features = plugin.health_feature_query(
        {
            "features": ["sleep_score", "sleep_duration_seconds"],
            "start": "2026-06-10",
            "end": "2026-06-10",
            "grain": "day",
        }
    )

    assert plan["next_tools"] == ["health_coverage", "health_analyze"]
    assert features["rows"][0]["sleep_score"] is not None
    assert features["rows"][0]["sleep_duration_seconds"] is not None


def test_hap_e03_coverage_before_analysis(tmp_path):
    plugin = _load_analysis_plugin(tmp_path)

    plan = plugin.health_analysis_plan(
        {"question": "Why was I stressed yesterday?", "today": "2026-06-11"}
    )
    coverage = plugin.health_coverage(
        {
            "domains": ["oura", "calendar", "email"],
            "start": "2026-06-10",
            "end": "2026-06-10",
        }
    )
    result = plugin.health_analyze(
        {
            "analysis_id": "calendar_email_stress_association",
            "start": "2026-03-13",
            "end": "2026-06-11",
            "target": "stress_high_seconds",
            "params": {},
        }
    )

    assert plan["candidate_analyses"][0]["analysis_id"] == "calendar_email_stress_association"
    assert coverage["coverage"]["calendar"]["row_count"] > 0
    assert result["eligible"] is True
    assert result["answer_hints"][0].startswith(
        "The strongest pattern in this window is associated with"
    )


def test_hap_e04_calendar_email_stress_association(tmp_path):
    plugin = _load_analysis_plugin(tmp_path)

    result = plugin.health_analyze(
        {
            "analysis_id": "calendar_email_stress_association",
            "start": "2026-03-13",
            "end": "2026-06-11",
            "target": "stress_high_seconds",
            "params": {},
        }
    )

    assert result["sample_size"]["outcome_days"] == 91
    assert result["results"]["meeting_minutes"]["higher_signal_mean"] > result["results"]["meeting_minutes"]["lower_signal_mean"]
    assert result["results"]["email_received_count"]["higher_signal_mean"] > result["results"]["email_received_count"]["lower_signal_mean"]
    assert result["results"]["workload_outcomes"]["stress_high_seconds"]["heavier_workday_mean"] > result["results"]["workload_outcomes"]["stress_high_seconds"]["lighter_workday_mean"]


def test_hap_e13_broad_workload_wellbeing_uses_direct_analysis_path(tmp_path):
    plugin = _load_analysis_plugin(tmp_path)
    question = (
        "Over the last 30 days, do heavier meeting or email days line up "
        "with worse stress, sleep, or readiness?"
    )

    plan = plugin.health_analysis_plan({"question": question, "today": "2026-06-11"})
    result = plugin.health_analyze(plan["direct_tool"]["args"])

    assert plan["candidate_analyses"] == [
        {
            "analysis_id": "calendar_email_stress_association",
            "display_name": "Calendar and email stress association",
            "default_window_days": 90,
            "requires_follow_up": False,
        }
    ]
    assert plan["next_tools"] == ["health_analyze"]
    assert plan["direct_tool"]["args"]["question"] == question
    assert plan["direct_tool"]["args"]["start"] == "2026-05-13"
    assert result["eligible"] is True
    assert result["results"]["workload_outcomes"]["sleep_score"]["heavier_workday_mean"] < result["results"]["workload_outcomes"]["sleep_score"]["lighter_workday_mean"]
    assert result["results"]["workload_outcomes"]["readiness_score"]["heavier_workday_mean"] < result["results"]["workload_outcomes"]["readiness_score"]["lighter_workday_mean"]


def test_hap_e06_food_sleep_association(tmp_path):
    plugin = _load_analysis_plugin(tmp_path)

    result = plugin.health_analyze(
        {
            "analysis_id": "food_sleep_association",
            "start": "2026-03-13",
            "end": "2026-06-11",
            "target": "sleep_score",
            "params": {},
        }
    )

    assert result["eligible"] is True
    assert result["sample_size"]["meal_logged_nights"] >= 4
    assert result["sample_size"]["unexposed_days"] >= 4
    assert "associated with" in result["answer_hints"][0]


def test_hap_e07_missed_exercise_days(tmp_path):
    plugin = _load_analysis_plugin(tmp_path, variant="exercise_routine")
    _seed_habit(plugin)

    result = plugin.health_analyze(
        {
            "analysis_id": "exercise_adherence",
            "start": "2026-03-13",
            "end": "2026-06-11",
            "params": {},
        }
    )

    assert result["eligible"] is True
    assert result["results"]["missed_days"]
    assert result["sample_size"]["routine_days"] >= 6


def test_hap_e11_thin_data_refusal(tmp_path):
    plugin = _load_analysis_plugin(tmp_path, variant="thin_food")

    result = plugin.health_analyze(
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


def test_hap_e12_explain_answer_provenance(tmp_path):
    plugin = _load_analysis_plugin(tmp_path)
    question = "Why did you say meetings were linked to stress?"
    result = plugin.health_analyze(
        {
            "analysis_id": "calendar_email_stress_association",
            "question": question,
            "start": "2026-03-13",
            "end": "2026-06-11",
            "target": "stress_high_seconds",
            "params": {},
        }
    )

    explanation = plugin.health_analysis_explain(
        {"analysis_run_id": result["analysis_run_id"]}
    )

    assert explanation["analysis_id"] == "calendar_email_stress_association"
    assert explanation["question"] == question
    assert explanation["feature_keys"] == [
        "meeting_minutes",
        "email_received_count",
        "stress_high_seconds",
        "sleep_score",
        "readiness_score",
    ]
    assert explanation["source_tables"] == ["calendar_daily", "email_daily", "oura_daily"]
    assert explanation["row_counts"]["feature_rows"] >= 3
    assert explanation["coverage"]["oura"]["row_count"] == 91
    assert explanation["caveats"]
    assert explanation["source_refs"]
    assert explanation["source_refs"][0]["provenance"]["source_tables"]

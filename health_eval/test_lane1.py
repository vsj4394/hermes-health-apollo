"""Lane 1 deterministic smoke tests."""

from __future__ import annotations

import builtins
import filecmp
import sqlite3
from pathlib import Path

from .build_fixture import build_golden_db
from . import checker, reference_templates
from .checker import check_no_food_fabrication
from .export_ground_truth import export_ground_truth, minutes_since_noon
from .render_references import render_references
from .run import (
    EvalAgent,
    EvalPluginContext,
    _score_question,
    build_scorecard,
    plugin_manager_status,
    suite_passes,
)


def test_fixture_reproducible(tmp_path):
    first = build_golden_db(tmp_path / "first.db")
    second = build_golden_db(tmp_path / "second.db")
    first_truth = export_ground_truth(first, tmp_path / "first.json")
    second_truth = export_ground_truth(second, tmp_path / "second.json")

    assert first_truth == second_truth
    assert filecmp.cmp(tmp_path / "first.json", tmp_path / "second.json")


def test_ground_truth_exports_shifted_pairs_and_derived_daily_facts(tmp_path):
    db_path = build_golden_db(tmp_path / "fixture.db")

    facts = export_ground_truth(db_path)

    assert facts["shifted_pairs"]["sleep_to_next_readiness"]
    assert facts["shifted_pairs"]["sleep_to_next_readiness"][0].keys() == {
        "left_day",
        "right_day",
        "left_value",
        "right_value",
    }
    assert facts["food_total_estimated_calories_by_day"]
    assert facts["day_of_week_by_day"]["2026-06-07"] == "Sunday"


def test_minutes_since_noon_wraps_midnight():
    assert minutes_since_noon("2026-06-08T23:30:00") == 690
    assert minutes_since_noon("2026-06-09T01:30:00") == 810


def test_no_food_variant_blocks_calorie_fabrication(tmp_path):
    db_path = build_golden_db(tmp_path / "no-food.db", variant="no_food_logged")

    result = check_no_food_fabrication(db_path, "You had 2100 calories.")

    assert result["passed"] is False
    assert result["has_food_data"] is False


def test_reference_placeholders_render(tmp_path):
    db_path = build_golden_db(tmp_path / "fixture.db")

    references = render_references(db_path)

    assert "t1_01" in references
    assert references["t1_01"]["reference_answer"]


def test_question_contract_covers_all_25_ids():
    QUESTIONS = reference_templates.QUESTIONS

    assert len(QUESTIONS) == 25
    assert set(QUESTIONS) == {
        *(f"t1_{index:02d}" for index in range(1, 16)),
        *(f"t2_{index:02d}" for index in range(1, 11)),
    }


def test_variant_question_matrix_covers_lane1_contract():
    QUESTION_MATRIX = getattr(reference_templates, "QUESTION_MATRIX", {})
    QUESTIONS = reference_templates.QUESTIONS

    assert set(QUESTION_MATRIX) == {
        "base",
        "spo2_low",
        "rhr_spike",
        "thin_5d",
        "partial_rows",
        "uncovered_context",
        "workout_stress",
        "null_result",
        "no_food_logged",
        "healthy",
    }
    assert set(QUESTION_MATRIX["base"]) == set(QUESTIONS)
    assert {"t1_04", "t1_05", "t1_07", "t1_12", "t1_13", "t1_14", "t1_15"}.issubset(
        QUESTION_MATRIX["no_food_logged"]
    )
    assert "t2_07" in QUESTION_MATRIX["rhr_spike"]
    assert {"t1_01", "t1_02", "t1_03", "t1_04", "t1_05"}.issubset(
        QUESTION_MATRIX["thin_5d"]
    )
    assert {"t2_07", "t2_08"}.issubset(QUESTION_MATRIX["spo2_low"])
    assert {"t2_07", "t2_08"}.issubset(QUESTION_MATRIX["healthy"])


def test_references_include_checker_metadata_for_each_question(tmp_path):
    db_path = build_golden_db(tmp_path / "fixture.db")

    references = render_references(db_path)
    QUESTIONS = reference_templates.QUESTIONS

    assert set(references) == set(QUESTIONS)
    for question_id, reference in references.items():
        assert reference["ground_truth_facts"]
        assert reference["must_include"]
        assert reference["pass_criteria"]
        assert "common_failures" in reference
        assert reference["question"] == QUESTIONS[question_id]


def test_checker_type_map_tracks_dates_numbers_and_calories():
    CHECKER_TYPE_MAP = getattr(checker, "CHECKER_TYPE_MAP", {})

    assert CHECKER_TYPE_MAP["date"]["columns"] == ["day"]
    assert CHECKER_TYPE_MAP["calories"]["columns"] == [
        "food_total_estimated_calories"
    ]
    assert CHECKER_TYPE_MAP["calories"]["unit_factor"] == 1
    assert CHECKER_TYPE_MAP["stress_seconds"]["columns"] == [
        "stress_high_seconds"
    ]


def test_fixture_schema_matches_production_metric_names(tmp_path):
    db_path = build_golden_db(tmp_path / "fixture.db")

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(daily_overview)")
        }
        sleep_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(oura_sleep_sessions)")
        }

    assert {"hrv_balance", "resting_heart_rate", "activity_score"}.issubset(columns)
    assert "hrv_ms" not in columns
    assert "resting_hr_bpm" not in columns
    assert {"total_sleep_duration_seconds", "deep_sleep_duration_seconds"}.issubset(
        sleep_columns
    )
    assert "total_sleep_minutes" not in sleep_columns


def test_scorecard_gate_covers_core_thresholds(tmp_path):
    db_path = build_golden_db(tmp_path / "fixture.db")
    scorecard = build_scorecard(db_path)

    assert scorecard["suite_pass"] is True
    assert scorecard["agent_model_id"] == "deterministic-health-tool-agent-v1"
    assert scorecard["judge_model_id"] == "deterministic-reference-judge-v1"
    assert scorecard["judge_prompt_hash"]
    manager_status = scorecard["plugin_manager_status"]
    if manager_status.get("reason") == "hermes_cli_unavailable":
        assert scorecard["plugin_manager_loaded"] is False
        assert manager_status["status"] == "skipped"
    else:
        assert scorecard["plugin_manager_loaded"] is True
        assert manager_status["tools"] >= 3
    assert len(scorecard["questions"]) == 25
    assert len(scorecard["adversarial"]) >= 10
    assert all(
        any(call["tool"] == "health_query" for call in run["tool_trace"])
        for question in scorecard["questions"]
        for run in question["runs"]
    )
    assert suite_passes(scorecard) is True


def test_scorecard_fails_when_tool_returns_no_rows(tmp_path):
    db_path = build_golden_db(tmp_path / "fixture.db")
    references = render_references(db_path)
    ctx = EvalPluginContext()
    ctx.register_tool("health_query", lambda _args: {"days": []})
    agent = EvalAgent(ctx, references)

    scored = _score_question(agent, "t1_01", reference_templates.QUESTIONS["t1_01"], 1)

    assert scored["pass_rate"] == 0
    assert scored["runs"][0]["dimension_scores"]["data_correctness"] < 32


def test_scorecard_copies_supplied_db_without_mutating_parent(tmp_path):
    db_path = build_golden_db(tmp_path / "fixture.db")
    sentinel = tmp_path / "plugins" / "health-data" / "sentinel.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("keep", encoding="utf-8")

    scorecard = build_scorecard(db_path)

    assert scorecard["suite_pass"] is True
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "config.yaml").exists()


def test_plugin_manager_status_degrades_without_hermes_cli(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "hermes_cli.plugins":
            raise ModuleNotFoundError("No module named 'hermes_cli'", name="hermes_cli")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    status = plugin_manager_status()

    assert status["loaded"] is False
    assert status["plugin"]["reason"] == "hermes_cli_unavailable"


def test_judge_prompt_file_is_present():
    assert (Path(__file__).with_name("judge_prompt.txt")).exists()


def test_scorecard_gate_rejects_empty_placeholder():
    assert suite_passes(
        {"questions": [], "adversarial": [], "suite_pass": False}
    ) is False

from __future__ import annotations

from .build_fixture import build_golden_db
from .run import build_scorecard


def test_plan_c_trace_orders_plan_then_coverage_then_analysis(tmp_path):
    db_path = build_golden_db(tmp_path / "fixture.db", variant="calendar_email_stress")
    scorecard = build_scorecard(db_path, suite="plan_c", repeats=1)

    hap_e03 = next(item for item in scorecard["questions"] if item["id"] == "hap_e03")
    tool_names = [call["tool"] for call in hap_e03["runs"][0]["tool_trace"]]

    assert tool_names[:3] == [
        "health_analysis_plan",
        "health_coverage",
        "health_analyze",
    ]


def test_plan_c_thin_food_variant_refuses_analysis(tmp_path):
    db_path = build_golden_db(tmp_path / "fixture.db", variant="thin_food_sleep")
    scorecard = build_scorecard(db_path, suite="plan_c", repeats=1)

    hap_e11 = next(item for item in scorecard["questions"] if item["id"] == "hap_e11")
    run = hap_e11["runs"][0]

    assert run["tool_result"]["reason"] == "minimum_sample_size_not_met"
    assert run["pass"] is True


def test_plan_c_smoke_scorecard_passes_with_case_variants():
    scorecard = build_scorecard(suite="plan_c", repeats=1)

    assert scorecard["suite"] == "plan_c"
    assert scorecard["suite_pass"] is True

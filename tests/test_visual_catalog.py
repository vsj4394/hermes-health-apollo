from __future__ import annotations

import json
import re
from pathlib import Path


def test_cli_visual_specs_reference_existing_mockups():
    specs_path = Path("visuals/cli/visual_specs.json")
    specs = json.loads(specs_path.read_text(encoding="utf-8"))

    assert specs
    for spec in specs:
        assert spec["id"]
        assert spec["triggers"]
        assert spec["privacy_default"]
        mockup = specs_path.parent / spec["mockup"]
        assert mockup.exists(), spec["id"]


def test_cli_visual_mockups_do_not_use_real_identity_markers():
    mockup_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("visuals/cli/mockups").glob("*.txt")
    )

    assert "@" not in mockup_text
    assert "/Users/" not in mockup_text
    assert "client_secret" not in mockup_text


def test_health_visuals_skill_is_mirrored_for_package_assets():
    repo_skill = Path("skills/health-visuals/SKILL.md").read_text(encoding="utf-8")
    asset_skill = Path("health_data_assets/skills/health-visuals/SKILL.md").read_text(
        encoding="utf-8"
    )
    repo_reference = Path(
        "skills/health-visuals/references/cli_visual_patterns.md"
    ).read_text(encoding="utf-8")
    asset_reference = Path(
        "health_data_assets/skills/health-visuals/references/cli_visual_patterns.md"
    ).read_text(encoding="utf-8")

    assert repo_skill == asset_skill
    assert repo_reference == asset_reference
    assert "If no visual fits, synthesize a new visual" in repo_skill


def test_visual_catalog_routes_existing_requests_by_trigger():
    specs = _visual_specs()

    examples = {
        "show me a meeting stress leaderboard for my last 30 days": {
            "meeting_stress_leaderboard"
        },
        "which coworker raises heart rate the most": {"attendee_effect_board"},
        "show me a leaderboard of which coworkers make my heart rate spike, with names and meeting titles": {
            "meeting_stress_leaderboard",
            "attendee_effect_board",
        },
        "make a recovery gate for tomorrow's calendar": {"recovery_gate"},
        "give me a day shape terminal barcode for yesterday": {"day_shape_barcode"},
        "matrix of meetings email stress outcomes": {"workload_outcome_matrix"},
        "show data coverage and missing data before charting": {"coverage_trust_ledger"},
    }
    for prompt, expected_ids in examples.items():
        assert expected_ids.issubset(_matching_visual_ids(prompt, specs))


def test_health_visuals_fallback_covers_unmatched_visual_requests():
    specs = _visual_specs()
    prompt = "make a terminal visual for caffeine timing, sleep latency, and next-day readiness"

    assert _matching_visual_ids(prompt, specs) == set()

    skill = Path("skills/health-visuals/SKILL.md").read_text(encoding="utf-8")
    assert "If no visual fits, synthesize a new visual" in skill
    assert "triggers:" in skill
    assert "Add or update a `visual_specs.json` entry" in skill
    assert "Add `mockups/<visual_id>.txt`" in skill
    assert "health_event_query" in skill


def test_non_visual_health_question_does_not_match_visual_catalog():
    specs = _visual_specs()

    assert _matching_visual_ids("why did I sleep badly last night?", specs) == set()


def test_health_visuals_skill_metadata_contains_trigger_terms():
    skill = Path("skills/health-visuals/SKILL.md").read_text(encoding="utf-8").lower()

    for term in ("terminal", "cli", "dashboard", "leaderboard", "chart", "visualization"):
        assert term in skill


def test_biometric_ranking_prompts_forbid_raw_third_party_detail():
    skill = Path("skills/health-visuals/SKILL.md").read_text(encoding="utf-8")
    brief = Path("visuals/cli/prompts/health_visual_brief.md").read_text(encoding="utf-8")
    guardrails = Path("visuals/cli/prompts/interpretation_guardrails.md").read_text(
        encoding="utf-8"
    )
    meeting_mockup = Path("visuals/cli/mockups/meeting_stress_leaderboard.txt").read_text(
        encoding="utf-8"
    )

    combined = "\n".join([skill, brief, guardrails])
    assert "do not display raw third-party names" in combined
    assert "raw meeting titles" in combined
    assert "prime suspect" not in meeting_mockup
    assert "higher association" in meeting_mockup


def _visual_specs() -> list[dict]:
    return json.loads(Path("visuals/cli/visual_specs.json").read_text(encoding="utf-8"))


def _matching_visual_ids(prompt: str, specs: list[dict]) -> set[str]:
    normalized = _normalize_text(prompt)
    matches = set()
    for spec in specs:
        for trigger in spec["triggers"]:
            if _normalize_text(trigger) in normalized:
                matches.add(spec["id"])
                break
    return matches


def _normalize_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

from __future__ import annotations

import json
from pathlib import Path


def test_cli_visual_specs_reference_existing_mockups():
    specs_path = Path("visuals/cli/visual_specs.json")
    specs = json.loads(specs_path.read_text(encoding="utf-8"))

    assert specs
    for spec in specs:
        assert spec["id"]
        assert "triggers" not in spec
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
    assert "synthesize a first-pass visual immediately" in repo_skill


def test_visual_routing_guidance_lives_in_skill_not_catalog_json():
    serialized_specs = Path("visuals/cli/visual_specs.json").read_text(encoding="utf-8")
    skill = Path("skills/health-visuals/SKILL.md").read_text(encoding="utf-8")
    reference = Path("skills/health-visuals/references/cli_visual_patterns.md").read_text(
        encoding="utf-8"
    )
    skill_lower = skill.lower()
    reference_lower = reference.lower()

    assert '"triggers"' not in serialized_specs
    assert "Route by semantic intent" in skill
    assert "Do not copy them into `visual_specs.json`" in skill
    assert "meeting_stress_leaderboard" in skill_lower
    assert "attendee_effect_board" in skill_lower
    assert "caffeine timing" in skill_lower
    assert "route by semantic" in reference_lower
    assert "coworker stress" in reference_lower


def test_health_visuals_first_pass_synthesis_is_primary_behavior():
    skill = Path("skills/health-visuals/SKILL.md").read_text(encoding="utf-8")
    reference = Path("skills/health-visuals/references/cli_visual_patterns.md").read_text(
        encoding="utf-8"
    )
    readme = Path("visuals/cli/README.md").read_text(encoding="utf-8")

    assert "first-pass visual" in skill
    assert "first pass" in readme
    old_backup_word = "fall" + "back"
    assert old_backup_word not in skill.lower()
    assert old_backup_word not in reference.lower()
    assert "health_event_query" in skill
    assert "Add or update a `visual_specs.json` entry" in skill
    assert "Add `mockups/<visual_id>.txt`" in skill


def test_health_visuals_skill_metadata_contains_invocation_terms():
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

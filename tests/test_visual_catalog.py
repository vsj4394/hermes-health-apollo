from __future__ import annotations

import re
from pathlib import Path


VISUAL_IDS = [
    "meeting_stress_leaderboard",
    "attendee_effect_board",
    "recovery_gate",
    "calendar_load_skyline",
    "day_shape_barcode",
    "workload_outcome_matrix",
    "sleep_debt_heatstrip",
    "baseline_drift_board",
    "stress_waterfall",
    "workout_recovery_lane",
    "workout_streak_ladder",
    "strain_readiness_ribbon",
    "training_mix_board",
    "chronotype_planner",
    "coverage_trust_ledger",
]


def test_cli_visual_mockups_exist_for_all_catalogued_visuals():
    mockup_root = Path("visuals/cli/mockups")

    for visual_id in VISUAL_IDS:
        assert (mockup_root / f"{visual_id}.txt").exists(), visual_id


def test_cli_visual_readme_catalog_matches_visual_ids():
    readme = Path("visuals/cli/README.md").read_text(encoding="utf-8")
    catalog_section = readme.split("## Catalog", 1)[1].split(
        "The source of truth is the `health-visuals` skill", 1
    )[0]
    readme_ids = re.findall(r"`([a-z0-9_]+)`", catalog_section)

    assert readme_ids == VISUAL_IDS


def test_packaged_visual_assets_mirror_repo_catalog():
    repo_root = Path("visuals/cli")
    asset_root = Path("health_data_assets/visuals/cli")
    repo_files = sorted(
        path.relative_to(repo_root) for path in repo_root.rglob("*") if path.is_file()
    )
    asset_files = sorted(
        path.relative_to(asset_root) for path in asset_root.rglob("*") if path.is_file()
    )

    assert asset_files == repo_files
    for relative_path in repo_files:
        assert (asset_root / relative_path).read_text(encoding="utf-8") == (
            repo_root / relative_path
        ).read_text(encoding="utf-8")


def test_cli_visual_mockups_do_not_use_real_identity_markers():
    mockup_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("visuals/cli/mockups").glob("*.txt")
    )

    assert "@" not in mockup_text
    assert "/Users/" not in mockup_text
    assert "client_secret" not in mockup_text


def test_health_visuals_skill_and_references_are_mirrored_for_package_assets():
    repo_skill = Path("skills/health-visuals/SKILL.md").read_text(encoding="utf-8")
    asset_skill = Path("health_data_assets/skills/health-visuals/SKILL.md").read_text(
        encoding="utf-8"
    )
    repo_cli_patterns = Path(
        "skills/health-visuals/references/cli_visual_patterns.md"
    ).read_text(encoding="utf-8")
    asset_cli_patterns = Path(
        "health_data_assets/skills/health-visuals/references/cli_visual_patterns.md"
    ).read_text(encoding="utf-8")
    repo_ascii_patterns = Path(
        "skills/health-visuals/references/terminal_ascii_patterns.md"
    ).read_text(encoding="utf-8")
    asset_ascii_patterns = Path(
        "health_data_assets/skills/health-visuals/references/terminal_ascii_patterns.md"
    ).read_text(encoding="utf-8")
    repo_ansi_patterns = Path(
        "skills/health-visuals/references/ansi_visual_patterns.md"
    ).read_text(encoding="utf-8")
    asset_ansi_patterns = Path(
        "health_data_assets/skills/health-visuals/references/ansi_visual_patterns.md"
    ).read_text(encoding="utf-8")
    repo_ansi_plan = Path(
        "skills/health-visuals/references/ansi_color_implementation_plan.md"
    ).read_text(encoding="utf-8")
    asset_ansi_plan = Path(
        "health_data_assets/skills/health-visuals/references/ansi_color_implementation_plan.md"
    ).read_text(encoding="utf-8")

    assert repo_skill == asset_skill
    assert repo_cli_patterns == asset_cli_patterns
    assert repo_ascii_patterns == asset_ascii_patterns
    assert repo_ansi_patterns == asset_ansi_patterns
    assert repo_ansi_plan == asset_ansi_plan


def test_health_visuals_skill_uses_skill_references_as_source_of_truth():
    skill = Path("skills/health-visuals/SKILL.md").read_text(encoding="utf-8")
    reference = Path("skills/health-visuals/references/cli_visual_patterns.md").read_text(
        encoding="utf-8"
    )
    ascii_patterns = Path(
        "skills/health-visuals/references/terminal_ascii_patterns.md"
    ).read_text(encoding="utf-8")
    ansi_patterns = Path(
        "skills/health-visuals/references/ansi_visual_patterns.md"
    ).read_text(encoding="utf-8")

    assert "The source of truth is the skill plus its references." in skill
    assert "visual_specs.json" not in skill
    assert "route by semantic" in reference.lower()
    assert "progress bars" in ascii_patterns.lower()
    assert "semantic color tokens" in ansi_patterns.lower()
    assert "workout_streak_ladder" in skill
    assert "training_mix_board" in skill

from __future__ import annotations

import json
from pathlib import Path


def test_cli_visual_specs_reference_existing_mockups():
    specs_path = Path("visuals/cli/visual_specs.json")
    specs = json.loads(specs_path.read_text(encoding="utf-8"))

    assert specs
    for spec in specs:
        assert spec["id"]
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

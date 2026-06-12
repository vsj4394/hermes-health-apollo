from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def load_release_safety():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "release_safety.py"
    spec = importlib.util.spec_from_file_location("release_safety", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["release_safety"] = module
    spec.loader.exec_module(module)
    return module


def test_release_safety_blocks_private_and_location_artifact_names():
    release_safety = load_release_safety()

    paths = [
        "health_data_assets/visuals/cli/visual_specs.json",
        "dist/hermes_health_data-0.1.0.data/.context/todos.md",
        "exports/Morning-Run.GPX",
        "exports/LOCATION-HISTORY.JSON",
        "exports/workout-ROUTES.json",
        "exports/Offline-Map.MBTILES",
        "exports/bundle.JS.MAP",
    ]

    assert release_safety.matches_any(paths[0]) is None
    assert release_safety.matches_any(paths[1]) == "*/.context/*"
    assert release_safety.matches_any(paths[2]) == "*.gpx"
    assert release_safety.matches_any(paths[3]) == "*location*.json"
    assert release_safety.matches_any(paths[4]) in {"*route*.json", "*routes*.json"}
    assert release_safety.matches_any(paths[5]) == "*.mbtiles"
    assert release_safety.matches_any(paths[6]) == "*.map"


def test_release_safety_requires_packaged_visual_assets():
    release_safety = load_release_safety()

    assert "health_data_assets/visuals/cli/visual_specs.json" in (
        release_safety.REQUIRED_PACKAGE_ASSETS
    )
    assert "health_data_assets/visuals/cli/prompts/health_visual_brief.md" in (
        release_safety.REQUIRED_PACKAGE_ASSETS
    )

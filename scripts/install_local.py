from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "hermes_plugins.health_data"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install this workspace into the active Hermes profile."
    )
    parser.add_argument(
        "--destination",
        help="Override the plugin destination. Defaults to Hermes home plugins/health-data.",
    )
    args = parser.parse_args()

    commands = _load_commands()
    result = commands.install_local(source=ROOT, destination=args.destination)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


def _load_commands():
    sys.modules.setdefault("hermes_plugins", types.ModuleType("hermes_plugins"))
    package = sys.modules.get(PACKAGE_NAME)
    if package is None:
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(ROOT)]
        sys.modules[PACKAGE_NAME] = package
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.commands", ROOT / "commands.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load health-data commands module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{PACKAGE_NAME}.commands"] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(main())

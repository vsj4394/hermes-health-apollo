from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "hermes_plugins.health_data"


def main() -> int:
    commands = _load_commands()
    destination = commands.store.hermes_home() / "plugins" / "health-data"
    installed_metadata = _read_json(destination / commands.INSTALL_METADATA_FILE)
    drift = _install_drift(commands, ROOT, destination)
    result = {
        "ok": installed_metadata is not None and not drift["has_drift"],
        "source": str(ROOT),
        "destination": str(destination),
        "installed_metadata": installed_metadata,
        "drift": drift,
        "sync_cron": commands.sync_cron_status(),
        "reminders": commands.reminder_guidance(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


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


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _install_drift(commands, source: Path, destination: Path) -> dict:
    source_files = sorted(commands._installable_source_files(source))
    source_file_set = set(source_files)
    destination_files = _installable_destination_files(commands, destination)
    missing: list[str] = []
    changed: list[str] = []
    extra = [str(relative) for relative in destination_files if relative not in source_file_set]
    for relative in source_files:
        source_path = source / relative
        destination_path = destination / relative
        if not destination_path.exists():
            missing.append(str(relative))
            continue
        if _sha256(source_path) != _sha256(destination_path):
            changed.append(str(relative))

    return {
        "has_drift": bool(missing or changed or extra),
        "missing": missing,
        "changed": changed,
        "extra": extra,
        "checked_files": len(source_files),
    }


def _installable_destination_files(commands, destination: Path) -> list[Path]:
    if not destination.exists():
        return []
    files: list[Path] = []
    for path in destination.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(destination)
        except ValueError:
            continue
        if commands._is_installable_relative_path(relative):
            files.append(relative)
    return sorted(files)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

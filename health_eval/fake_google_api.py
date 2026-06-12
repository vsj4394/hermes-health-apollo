"""Tiny fake Google Workspace CLI surface for future eval harness tests."""

from __future__ import annotations

import json


def calendar_payload() -> list[dict]:
    """Return deterministic calendar events."""

    return [
        {
            "summary": "Fixture planning",
            "start": "2026-06-08T09:00:00",
            "end": "2026-06-08T09:30:00",
        }
    ]


def main() -> int:
    print(json.dumps(calendar_payload(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

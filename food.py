from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from . import store


CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def log_food(day: str, description: str, analysis_text: str | dict | None = None) -> dict:
    parsed = _parse_analysis(analysis_text)
    items_json = json.dumps(parsed, sort_keys=True) if parsed is not None else None
    if items_json is None:
        return {
            "id": None,
            "day": day,
            "description": description,
            "items_json": None,
        }
    row_id = str(uuid4())
    logged_at = datetime.now(timezone.utc).isoformat()
    store.initialize()
    with sqlite3.connect(store.database_path()) as conn:
        conn.execute(
            """
            INSERT INTO food_logs(id, day, logged_at, description, items_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (row_id, day, logged_at, description, items_json),
        )
    return {
        "id": row_id,
        "day": day,
        "description": description,
        "items_json": items_json,
    }


def _parse_analysis(analysis_text: str | dict | None) -> dict | None:
    if analysis_text is None:
        return None
    if isinstance(analysis_text, dict):
        return _valid_items_json(analysis_text)
    text = analysis_text.strip()
    candidates = [text]
    match = CODE_BLOCK_RE.search(text)
    if match:
        candidates.insert(0, match.group(1).strip())
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        valid = _valid_items_json(parsed)
        if valid is not None:
            return valid
    return None


def _valid_items_json(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    if "items" not in value or "total_estimated_calories" not in value:
        return None
    if not isinstance(value["items"], list):
        return None
    try:
        calories = int(value["total_estimated_calories"])
    except (TypeError, ValueError):
        return None
    return {"items": value["items"], "total_estimated_calories": calories}

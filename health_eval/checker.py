"""Deterministic checker placeholders for Lane 1."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")

CHECKER_TYPE_MAP = {
    "date": {
        "columns": ["day"],
        "unit_factor": 1,
        "tolerance": 0,
    },
    "calories": {
        "columns": ["food_total_estimated_calories"],
        "unit_factor": 1,
        "tolerance": 0,
    },
    "stress_seconds": {
        "columns": ["stress_high_seconds"],
        "unit_factor": 1,
        "tolerance": 0,
    },
    "sleep_score": {
        "columns": ["sleep_score"],
        "unit_factor": 1,
        "tolerance": 1,
    },
    "readiness_score": {
        "columns": ["readiness_score"],
        "unit_factor": 1,
        "tolerance": 1,
    },
    "meetings": {
        "columns": ["meeting_count", "meeting_minutes"],
        "unit_factor": 1,
        "tolerance": 0,
    },
    "email": {
        "columns": ["received_count"],
        "unit_factor": 1,
        "tolerance": 0,
    },
}


def extract_numbers(text: str) -> list[str]:
    """Extract simple numeric claims from an answer."""

    return NUMBER_RE.findall(text)


def food_log_count(db_path: str | Path) -> int:
    """Return the number of food rows with calorie JSON present."""

    with sqlite3.connect(Path(db_path)) as conn:
        return conn.execute(
            """
            SELECT COUNT(*)
            FROM food_logs
            WHERE json_extract(items_json, '$.total_estimated_calories') IS NOT NULL
            """
        ).fetchone()[0]


def check_no_food_fabrication(db_path: str | Path, answer: str) -> dict:
    """Flag calorie claims when the fixture has no logged food data."""

    has_calorie_claim = "calorie" in answer.lower() and bool(extract_numbers(answer))
    has_food_data = food_log_count(db_path) > 0
    passed = has_food_data or not has_calorie_claim
    return {
        "passed": passed,
        "has_food_data": has_food_data,
        "has_calorie_claim": has_calorie_claim,
    }

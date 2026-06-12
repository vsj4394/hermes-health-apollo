from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import date, timedelta
from typing import Any

from . import feature_engineering, semantic_layer, store
from .analysis_registry import ANALYSIS_PACKS, catalog_entry
from .feature_registry import FEATURE_DEFINITIONS, FEATURE_VERSION

HEALTH_EVENT_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "event_types": {"type": "array", "items": {"type": "string"}},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "include_entities": {"type": "boolean"},
        "limit": {"type": "integer", "minimum": 1},
    },
    "additionalProperties": False,
}
HEALTH_COVERAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "domains": {"type": "array", "items": {"type": "string"}},
        "analysis_id": {"type": "string"},
        "start": {"type": "string"},
        "end": {"type": "string"},
    },
    "additionalProperties": False,
}
HEALTH_FEATURE_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "features": {"type": "array", "items": {"type": "string"}},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "grain": {"type": "string"},
    },
    "required": ["features", "start", "end"],
    "additionalProperties": False,
}
HEALTH_ANALYSIS_CATALOG_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
HEALTH_ANALYSIS_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "today": {"type": "string"},
    },
    "required": ["question"],
    "additionalProperties": False,
}
HEALTH_ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis_id": {"type": "string"},
        "question": {"type": "string"},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "target": {"type": "string"},
        "params": {"type": "object"},
    },
    "required": ["analysis_id", "start", "end"],
    "additionalProperties": False,
}
HEALTH_ANALYSIS_EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {"analysis_run_id": {"type": "string"}},
    "required": ["analysis_run_id"],
    "additionalProperties": False,
}


def health_coverage(args: dict) -> dict:
    store.initialize()
    domains = list(args.get("domains") or [])
    analysis_id = args.get("analysis_id")
    if analysis_id and not domains:
        domains = _domains_for_analysis(str(analysis_id))
    if not domains:
        domains = ["oura", "calendar", "email", "food", "exercise"]
    start = args.get("start")
    end = args.get("end")
    coverage = {}
    with sqlite3.connect(store.database_path()) as conn:
        for domain in domains:
            table, date_expr = {
                "oura": ("oura_daily", "day"),
                "calendar": ("calendar_daily", "day"),
                "email": ("email_daily", "day"),
                "food": ("food_logs", "day"),
                "exercise": ("oura_workouts", "day"),
            }[domain]
            coverage[domain] = _coverage_row(conn, table, date_expr, start, end)
    result = {"coverage": coverage}
    if analysis_id:
        result["analysis_id"] = analysis_id
    return result


def health_event_query(args: dict) -> dict:
    start = args.get("start")
    end = args.get("end")
    if start and end:
        semantic_layer.refresh_canonical_facts(start=start, end=end)
    else:
        store.initialize()
    event_types = list(args.get("event_types") or [])
    include_entities = bool(args.get("include_entities"))
    limit = int(args.get("limit", 100))
    filters = []
    params: list[Any] = []
    if event_types:
        filters.append(f"event_type IN ({','.join('?' for _ in event_types)})")
        params.extend(event_types)
    if start and end:
        filters.append("day BETWEEN ? AND ?")
        params.extend([start, end])
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with sqlite3.connect(store.database_path()) as conn:
        conn.row_factory = sqlite3.Row
        semantic_layer.ensure_canonical_schema(conn)
        rows = conn.execute(
            f"""
            SELECT event_id, event_type, provider, source_table, source_row_id,
                   start_ts, end_ts, day, title, status, attributes_json
            FROM events
            {where}
            ORDER BY day, start_ts
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        events = [_decode_row(row) for row in rows]
        if include_entities and events:
            _attach_event_entities(conn, events)
    return {"events": events, "count": len(events)}


def health_feature_query(args: dict) -> dict:
    return feature_engineering.materialize_features(
        feature_keys=list(args["features"]),
        start=str(args["start"]),
        end=str(args["end"]),
        grain=str(args.get("grain", "day")),
    )


def health_analysis_catalog(_args: dict | None = None) -> dict:
    return {
        "analysis_packs": [
            {
                **catalog_entry(analysis_id),
                "method": pack["method"],
                "required_features": pack["required_features"],
                "answer_policy": pack["answer_policy"],
                "eligible_now": True,
            }
            for analysis_id, pack in ANALYSIS_PACKS.items()
        ]
    }


def health_analysis_plan(args: dict) -> dict:
    question = str(args["question"]).strip()
    lowered = question.lower()
    direct = _direct_analysis_route(question, args.get("today"))
    if direct is not None:
        return {
            "question": question,
            "candidate_analyses": [catalog_entry(direct["analysis_id"])],
            "needs_sync": False,
            "routing_confidence": "high",
            "next_tools": ["health_analyze"],
            "direct_tool": {
                "name": "health_analyze",
                "args": {
                    "analysis_id": direct["analysis_id"],
                    "question": question,
                    "start": direct["start"],
                    "end": direct["end"],
                    "target": direct["target"],
                    "params": {"route": direct["route"]},
                },
            },
        }
    candidates = []
    if any(token in lowered for token in ("food", "meal", "eat", "sleep")):
        candidates.append(catalog_entry("food_sleep_association"))
    if any(token in lowered for token in ("meeting", "email", "stress", "inbox", "calendar")):
        candidates.append(catalog_entry("calendar_email_stress_association"))
    if any(token in lowered for token in ("miss exercise", "workout routine", "exercise days")):
        candidates.append(catalog_entry("exercise_adherence"))
    if any(token in lowered for token in ("recovery", "readiness", "workout")):
        candidates.append(catalog_entry("exercise_recovery_association"))
    return {
        "question": question,
        "candidate_analyses": candidates,
        "needs_sync": False,
        "next_tools": ["health_coverage", "health_analyze"],
    }


def health_analyze(args: dict) -> dict:
    analysis_id = str(args["analysis_id"])
    pack = ANALYSIS_PACKS[analysis_id]
    feature_result = feature_engineering.materialize_features(
        feature_keys=list(pack["required_features"]),
        start=str(args["start"]),
        end=str(args["end"]),
        grain="day",
    )
    coverage = health_coverage(
        {"analysis_id": analysis_id, "start": args["start"], "end": args["end"]}
    )["coverage"]
    rows = feature_result["rows"]
    if analysis_id == "calendar_email_stress_association":
        result = _calendar_email_stress(pack, rows)
    elif analysis_id == "food_sleep_association":
        result = _food_sleep(pack, rows)
    elif analysis_id == "exercise_adherence":
        result = _exercise_adherence(pack, rows)
    elif analysis_id == "exercise_recovery_association":
        result = _exercise_recovery(pack, rows)
    else:
        raise ValueError(f"Unsupported analysis_id: {analysis_id}")
    result.update(
        {
            "analysis_id": analysis_id,
            "coverage": coverage,
            "feature_keys": list(pack["required_features"]),
            "source_tables": _source_tables(pack["required_features"]),
        }
    )
    if not result["eligible"]:
        result.setdefault("reason", "minimum_sample_size_not_met")
    run_id = _store_analysis_run(args, result)
    result["analysis_run_id"] = run_id
    return result


def health_analysis_explain(args: dict) -> dict:
    run_id = str(args["analysis_run_id"])
    with sqlite3.connect(store.database_path()) as conn:
        conn.row_factory = sqlite3.Row
        semantic_layer.ensure_canonical_schema(conn)
        row = conn.execute(
            """
            SELECT analysis_id, question, args_json, code_version, coverage_json, result_json
            FROM analysis_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown analysis_run_id: {run_id}")
        result = json.loads(row["result_json"])
        run_args = json.loads(row["args_json"] or "{}")
        feature_keys = result["feature_keys"]
        source_tables = result["source_tables"]
        start = str(run_args.get("start") or "")
        end = str(run_args.get("end") or "")
        window_filter = ""
        params: list[Any] = [*feature_keys, row["code_version"]]
        if start and end:
            window_filter = "AND feature_ts BETWEEN ? AND ?"
            params.extend([start, end])
        feature_rows = conn.execute(
            f"""
            SELECT feature_id, feature_key, feature_ts, provenance_json
            FROM features
            WHERE feature_key IN ({','.join('?' for _ in feature_keys)})
              AND grain = 'day'
              AND feature_version = ?
              {window_filter}
            ORDER BY feature_ts, feature_key
            LIMIT 100
            """,
            params,
        ).fetchall()
        source_refs = [
            {
                "feature_id": feature_row["feature_id"],
                "feature_key": feature_row["feature_key"],
                "feature_ts": feature_row["feature_ts"],
                "provenance": json.loads(feature_row["provenance_json"] or "{}"),
            }
            for feature_row in feature_rows
        ]
        canonical_ids = [source_ref["feature_id"] for source_ref in source_refs]
    return {
        "analysis_run_id": run_id,
        "analysis_id": row["analysis_id"],
        "question": row["question"],
        "feature_keys": feature_keys,
        "source_tables": source_tables,
        "sample_size": result.get("sample_size", {}),
        "caveats": result.get("caveats", []),
        "coverage": json.loads(row["coverage_json"]),
        "row_counts": {
            "feature_rows": len(canonical_ids),
            "canonical_ids": len(canonical_ids),
        },
        "canonical_ids": canonical_ids,
        "source_refs": source_refs,
    }


def _calendar_email_stress(pack: dict, rows: list[dict]) -> dict:
    outcome = [row for row in rows if row.get("stress_high_seconds") is not None]
    high = [row for row in outcome if row["stress_high_seconds"] == max(r["stress_high_seconds"] for r in outcome)]
    low = [row for row in outcome if row not in high]
    sample_size = {
        "outcome_days": len(outcome),
        "high_signal_days": len(high),
        "low_signal_days": len(low),
    }
    caveats = [
        "Calendar and email are represented by daily rollups in this milestone.",
        "This is an association screen, not a causal or diagnostic claim.",
    ]
    if (
        sample_size["outcome_days"] < pack["minimums"]["outcome_days"]
        or sample_size["high_signal_days"] < pack["minimums"]["high_signal_days"]
        or sample_size["low_signal_days"] < pack["minimums"]["low_signal_days"]
    ):
        return _ineligible(sample_size, caveats)
    results = {
        key: {
            "higher_signal_mean": _mean(row[key] for row in high),
            "lower_signal_mean": _mean(row[key] for row in low),
        }
        for key in ("meeting_minutes", "email_received_count")
    }
    meeting_median = _median(row.get("meeting_minutes", 0) for row in outcome)
    email_median = _median(row.get("email_received_count", 0) for row in outcome)
    heavy_indexes = {
        index
        for index, row in enumerate(outcome)
        if row.get("meeting_minutes", 0) > meeting_median
        or row.get("email_received_count", 0) > email_median
    }
    heavy_work_days = [row for index, row in enumerate(outcome) if index in heavy_indexes]
    lighter_work_days = [
        row for index, row in enumerate(outcome) if index not in heavy_indexes
    ]
    if heavy_work_days and lighter_work_days:
        results["workload_outcomes"] = {
            key: {
                "heavier_workday_mean": _mean(row[key] for row in heavy_work_days),
                "lighter_workday_mean": _mean(row[key] for row in lighter_work_days),
            }
            for key in ("stress_high_seconds", "sleep_score", "readiness_score")
            if any(row.get(key) is not None for row in outcome)
        }
    strongest = max(
        ("meeting_minutes", "email_received_count"),
        key=lambda key: results[key]["higher_signal_mean"] - results[key]["lower_signal_mean"],
    )
    return {
        "eligible": True,
        "method": pack["method"],
        "sample_size": sample_size,
        "results": results,
        "caveats": caveats,
        "answer_hints": [
            "The strongest pattern in this window is associated with "
            f"{strongest.replace('_', ' ')} on the highest-stress days.",
            "For broad workload questions, compare heavier-workday stress, sleep, and readiness averages against lighter days.",
            "Compare high-stress and lower-stress day averages before interpreting the pattern.",
        ],
    }


def _food_sleep(pack: dict, rows: list[dict]) -> dict:
    outcome = [row for row in rows if row.get("sleep_score") is not None]
    meal_logged = [row for row in outcome if row.get("meal_count") is not None]
    exposed = [row for row in meal_logged if row.get("late_meal_flag") == 1]
    unexposed = [row for row in meal_logged if row.get("late_meal_flag") == 0]
    sample_size = {
        "outcome_days": len(outcome),
        "meal_logged_nights": len(meal_logged),
        "exposed_days": len(exposed),
        "unexposed_days": len(unexposed),
    }
    caveats = ["Food/sleep analysis uses day-grain meal features for this milestone."]
    if (
        sample_size["outcome_days"] < pack["minimums"]["outcome_days"]
        or sample_size["exposed_days"] < pack["minimums"]["exposed_days"]
        or sample_size["unexposed_days"] < pack["minimums"]["unexposed_days"]
    ):
        return _ineligible(
            sample_size,
            [
                "Only "
                f"{sample_size['meal_logged_nights']} meal-logged nights are available; "
                "4 exposed and 4 unexposed nights are required."
            ],
        )
    results = {
        "late_meal_flag": {
            "exposed_sleep_score_mean": _mean(row["sleep_score"] for row in exposed),
            "unexposed_sleep_score_mean": _mean(row["sleep_score"] for row in unexposed),
        },
        "food_total_estimated_calories": {
            "exposed_mean": _mean(row["food_total_estimated_calories"] for row in exposed),
            "unexposed_mean": _mean(row["food_total_estimated_calories"] for row in unexposed),
        },
    }
    return {
        "eligible": True,
        "method": pack["method"],
        "sample_size": sample_size,
        "results": results,
        "caveats": caveats,
        "answer_hints": [
            "Late logged meals are associated with lower sleep scores in this window."
        ],
    }


def _exercise_adherence(pack: dict, rows: list[dict]) -> dict:
    routine_rows = [row for row in rows if row.get("missed_planned_workout") is not None]
    missed = [row["day"] for row in routine_rows if row.get("missed_planned_workout") == 1]
    sample_size = {"routine_days": len(routine_rows), "missed_days": len(missed)}
    if sample_size["routine_days"] < pack["minimums"]["routine_days"]:
        return _ineligible(
            sample_size,
            ["Missed exercise days require an expected routine with enough routine days."],
        )
    return {
        "eligible": True,
        "method": pack["method"],
        "sample_size": sample_size,
        "results": {
            "missed_days": missed,
            "observed_workout_days": [row["day"] for row in rows if row.get("workout_count", 0) > 0],
        },
        "caveats": ["Missed days are based on the configured habit weekdays."],
        "answer_hints": ["Missed planned workout days are listed as routine gaps."],
    }


def _exercise_recovery(pack: dict, rows: list[dict]) -> dict:
    outcome = [row for row in rows if row.get("readiness_score") is not None]
    exercise = [row for row in outcome if row.get("workout_count", 0) > 0]
    non_exercise = [row for row in outcome if row.get("workout_count", 0) == 0]
    sample_size = {
        "outcome_days": len(outcome),
        "exercise_days": len(exercise),
        "non_exercise_days": len(non_exercise),
    }
    if (
        sample_size["outcome_days"] < pack["minimums"]["outcome_days"]
        or sample_size["exercise_days"] < pack["minimums"]["exercise_days"]
        or sample_size["non_exercise_days"] < pack["minimums"]["non_exercise_days"]
    ):
        return _ineligible(sample_size, ["Not enough exercise and non-exercise days."])
    return {
        "eligible": True,
        "method": pack["method"],
        "sample_size": sample_size,
        "results": {
            "readiness_score": {
                "exercise_day_mean": _mean(row["readiness_score"] for row in exercise),
                "non_exercise_day_mean": _mean(row["readiness_score"] for row in non_exercise),
            },
            "recovery_high_seconds": {
                "exercise_day_mean": _mean(row["recovery_high_seconds"] for row in exercise),
                "non_exercise_day_mean": _mean(row["recovery_high_seconds"] for row in non_exercise),
            },
        },
        "caveats": ["Exercise/recovery is observational and day-grain."],
        "answer_hints": ["Workout days are associated with the listed recovery averages."],
    }


def _store_analysis_run(args: dict, result: dict) -> str:
    run_id = f"analysis:{uuid.uuid4().hex}"
    question = _analysis_question(args)
    with sqlite3.connect(store.database_path()) as conn:
        semantic_layer.ensure_canonical_schema(conn)
        conn.execute(
            """
            INSERT INTO analysis_runs(
                run_id, analysis_id, question, args_json, code_version,
                data_fingerprint, coverage_json, result_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                result["analysis_id"],
                question,
                json.dumps(args, sort_keys=True),
                FEATURE_VERSION,
                f"{args.get('start')}:{args.get('end')}:{result['analysis_id']}",
                json.dumps(result["coverage"], sort_keys=True),
                json.dumps(result, sort_keys=True),
            ),
        )
        conn.commit()
    return run_id


def _direct_analysis_route(question: str, today: Any) -> dict[str, str] | None:
    lowered = question.lower()
    work_terms = ("meeting", "meetings", "email", "emails", "inbox", "calendar")
    outcome_terms = ("stress", "sleep", "readiness", "recovery")
    broad_terms = ("line up", "correlat", "associated", "heavier", "heavy", "busiest", "worse")
    if not (
        any(term in lowered for term in work_terms)
        and any(term in lowered for term in outcome_terms)
        and any(term in lowered for term in broad_terms)
    ):
        return None
    start, end = _analysis_window(question, today, default_days=30)
    return {
        "analysis_id": "calendar_email_stress_association",
        "start": start,
        "end": end,
        "target": "stress_sleep_readiness",
        "route": "broad_workload_wellbeing",
    }


def _analysis_window(question: str, today: Any, *, default_days: int) -> tuple[str, str]:
    end = date.fromisoformat(str(today)) if today else date.today()
    match = re.search(r"(?:last|past|over the last)\s+(\d{1,3})\s+days?", question.lower())
    days = int(match.group(1)) if match else default_days
    days = max(1, min(days, 366))
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _analysis_question(args: dict) -> str:
    question = args.get("question")
    if question is None and isinstance(args.get("params"), dict):
        question = args["params"].get("question")
    if question is None:
        question = ""
    return str(question)


def _ineligible(sample_size: dict, caveats: list[str]) -> dict:
    return {
        "eligible": False,
        "reason": "minimum_sample_size_not_met",
        "sample_size": sample_size,
        "caveats": caveats,
        "answer_hints": [
            "Data is too thin for a trustworthy association claim.",
            "List the observed rows and say more data is needed.",
        ],
    }


def _coverage_row(
    conn: sqlite3.Connection,
    table: str,
    date_expr: str,
    start: str | None,
    end: str | None,
) -> dict:
    params: list[Any] = []
    where = ""
    if start and end:
        where = f"WHERE {date_expr} BETWEEN ? AND ?"
        params = [start, end]
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS row_count, MIN({date_expr}) AS first_day, MAX({date_expr}) AS last_day
        FROM {table}
        {where}
        """,
        params,
    ).fetchone()
    return {"row_count": row[0], "first_day": row[1], "last_day": row[2]}


def _domains_for_analysis(analysis_id: str) -> list[str]:
    domains = []
    for feature in ANALYSIS_PACKS[analysis_id]["required_features"]:
        for domain in FEATURE_DEFINITIONS[feature].required_domains:
            if domain == "food":
                mapped = "food"
            elif domain == "calendar":
                mapped = "calendar"
            elif domain == "email":
                mapped = "email"
            elif feature in {"workout_count", "exercise_minutes", "missed_planned_workout"}:
                mapped = "exercise"
            else:
                mapped = "oura"
            if mapped not in domains:
                domains.append(mapped)
    return domains


def _source_tables(features: list[str]) -> list[str]:
    tables = []
    for feature in features:
        for table in FEATURE_DEFINITIONS[feature].source_tables:
            if table not in tables:
                tables.append(table)
    return tables


def _decode_row(row: sqlite3.Row) -> dict:
    decoded = dict(row)
    decoded["attributes"] = json.loads(decoded.pop("attributes_json") or "{}")
    return decoded


def _attach_event_entities(conn: sqlite3.Connection, events: list[dict]) -> None:
    for event in events:
        rows = conn.execute(
            """
            SELECT ee.entity_id, ee.role, ee.attributes_json, e.entity_type, e.display_name
            FROM event_entities ee
            JOIN entities e ON e.entity_id = ee.entity_id
            WHERE ee.event_id = ?
            ORDER BY ee.role, e.display_name
            """,
            (event["event_id"],),
        ).fetchall()
        event["entities"] = [
            {
                "entity_id": row["entity_id"],
                "entity_type": row["entity_type"],
                "display_name": row["display_name"],
                "role": row["role"],
                "attributes": json.loads(row["attributes_json"] or "{}"),
            }
            for row in rows
        ]


def _mean(values) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _median(values) -> float:
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return 0.0
    midpoint = len(clean) // 2
    if len(clean) % 2:
        return float(clean[midpoint])
    return (clean[midpoint - 1] + clean[midpoint]) / 2

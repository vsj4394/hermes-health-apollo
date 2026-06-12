from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import context, oura, store

FRESHNESS_POLICY_HOURS = 6
ADMIN_COMMANDS = ["setup", "status", "sync"]
CANONICAL_SOURCE_SLUGS = ("oura", "google_calendar", "gmail", "manual_food")

SOURCE_CAPABILITY_CARDS = [
    {
        "provider": "oura",
        "supports": ["sleep", "stress", "recovery", "activity"],
        "requires": ["oura_oauth"],
        "default_enabled": True,
        "privacy_mode": "device_metrics",
    },
    {
        "provider": "google_calendar",
        "supports": ["calendar correlations", "meeting load", "planning"],
        "requires": ["google_oauth"],
        "default_enabled": True,
        "privacy_mode": "metadata_only",
    },
    {
        "provider": "gmail",
        "supports": ["email/calendar correlations", "sender-volume patterns"],
        "requires": ["google_oauth"],
        "default_enabled": True,
        "privacy_mode": "metadata_only",
    },
    {
        "provider": "manual_food",
        "supports": ["food", "meals", "nutrition timing"],
        "requires": [],
        "default_enabled": True,
        "privacy_mode": "manual_logs",
    },
]

DEFAULT_PRIVACY = {
    "gmail_body_opt_in": False,
    "precise_location_opt_in": False,
}


def start_or_resume_setup_run(
    *,
    setup_run_id: str | None = None,
    goals: list[str] | None = None,
    already_uses: list[str] | None = None,
    privacy_email_body: bool = False,
    privacy_precise_location: bool = False,
    routine: dict[str, Any] | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Create or resume a deterministic setup run."""

    store.initialize()
    _ensure_onboarding_tables()
    if setup_run_id:
        existing = _load_setup_run(setup_run_id)
        if existing is not None:
            return existing

    normalized_goals = _normalize_list(goals)
    normalized_uses = _normalize_list(already_uses)
    privacy = {
        "email_body": bool(privacy_email_body),
        "precise_location": bool(privacy_precise_location),
    }
    recommendations = recommend_sources(
        goals=normalized_goals,
        already_uses=normalized_uses,
        privacy=privacy,
    )
    source_states = build_source_states(recommendations)
    next_action = _next_setup_action(source_states)
    run = {
        "id": f"setup-{uuid.uuid4().hex[:12]}",
        "status": "in_progress",
        "phase": "connect_sync_verify",
        "next_action": next_action,
        "goals": normalized_goals,
        "already_uses": normalized_uses,
        "privacy": privacy,
        "recommendations": recommendations,
        "sources": source_states,
    }
    _persist_profile(
        goals=normalized_goals,
        already_uses=normalized_uses,
        privacy=privacy,
        routine=routine or {},
        timezone=timezone,
    )
    _persist_setup_run(run)
    return run


def recommend_sources(
    *,
    goals: list[str],
    already_uses: list[str],
    privacy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return source cards ordered by the canonical source slug list."""

    goal_text = " ".join(goals).lower()
    uses = {item.lower() for item in already_uses}
    recommendations: list[dict[str, Any]] = []
    for card in SOURCE_CAPABILITY_CARDS:
        provider = str(card["provider"])
        supports = [str(value) for value in card["supports"]]
        matched = [
            support
            for support in supports
            if support in goal_text or any(token in goal_text for token in support.split())
        ]
        if provider == "google_calendar" and "google_workspace" in uses:
            matched.append("google_workspace")
        if provider == "gmail" and (
            "google_workspace" in uses or "email/calendar correlations" in goal_text
        ):
            matched.append("google_workspace")
        if provider == "manual_food" and "food" in goal_text:
            matched.append("food")
        if provider == "oura" and ("oura" in uses or {"sleep", "stress"} & set(goals)):
            matched.append("oura")
        if not matched:
            continue
        enriched = dict(card)
        enriched["reason"] = _recommendation_reason(provider, matched)
        enriched["privacy_mode"] = _privacy_mode(provider, privacy)
        recommendations.append(enriched)
    return sorted(recommendations, key=lambda item: CANONICAL_SOURCE_SLUGS.index(item["provider"]))


def build_source_states(recommendations: list[dict[str, Any]] | None = None) -> dict[str, dict]:
    cards = recommendations if recommendations is not None else SOURCE_CAPABILITY_CARDS
    wanted = {str(card["provider"]) for card in cards}
    legacy = _legacy_sync_state()
    states: dict[str, dict] = {}
    for provider in CANONICAL_SOURCE_SLUGS:
        if provider not in wanted:
            continue
        state = _provider_state(provider, legacy)
        card = next((item for item in SOURCE_CAPABILITY_CARDS if item["provider"] == provider), {})
        states[provider] = {
            "state": state,
            "privacy_mode": card.get("privacy_mode", "metadata_only"),
            "last_sync": _legacy_last_sync(provider, legacy),
            "freshness_policy_hours": FRESHNESS_POLICY_HOURS,
        }
    return states


def status_snapshot() -> dict[str, Any]:
    """Build the short admin status payload for commands.status()."""

    store.initialize()
    _ensure_onboarding_tables()
    recommendations = _latest_recommendations() or SOURCE_CAPABILITY_CARDS
    sources = build_source_states(recommendations)
    return {
        "primary_path": "normal_hermes_chat",
        "admin_commands": ADMIN_COMMANDS,
        "freshness_policy_hours": FRESHNESS_POLICY_HOURS,
        "sources": sources,
        "sync_schedules": _sync_schedules(),
        "recent_runs": _recent_runs(),
        "privacy_defaults": DEFAULT_PRIVACY,
        "guidance": (
            'Run `hermes`, then ask "How did I sleep last night?" After setup, '
            "Oura auth requires an Oura developer app plus "
            "`HERMES_OURA_CLIENT_ID`/`HERMES_OURA_CLIENT_SECRET`; Google auth "
            "requires the Google Workspace helper and a Google Cloud Desktop app "
            "OAuth JSON with redirect URI `http://localhost:1/`."
        ),
        "debug_command": 'hermes health ask "How did I sleep last night?"',
    }


def _ensure_onboarding_tables() -> None:
    with sqlite3.connect(store.database_path()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS health_profile (
                id TEXT PRIMARY KEY,
                timezone TEXT,
                goals_json TEXT NOT NULL,
                already_uses_json TEXT NOT NULL,
                privacy_json TEXT NOT NULL,
                routine_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS health_setup_runs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                phase TEXT NOT NULL,
                next_action TEXT,
                goals_json TEXT NOT NULL,
                already_uses_json TEXT NOT NULL,
                privacy_json TEXT NOT NULL,
                recommendations_json TEXT NOT NULL,
                source_states_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS exercise_routines (
                id TEXT PRIMARY KEY,
                weekday INTEGER NOT NULL,
                label TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


def _persist_profile(
    *,
    goals: list[str],
    already_uses: list[str],
    privacy: dict[str, Any],
    routine: dict[str, Any],
    timezone: str | None,
) -> None:
    with sqlite3.connect(store.database_path()) as conn:
        conn.execute(
            """
            INSERT INTO health_profile(
                id, timezone, goals_json, already_uses_json, privacy_json, routine_json, updated_at
            )
            VALUES ('default', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                timezone = excluded.timezone,
                goals_json = excluded.goals_json,
                already_uses_json = excluded.already_uses_json,
                privacy_json = excluded.privacy_json,
                routine_json = excluded.routine_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                timezone,
                _json(goals),
                _json(already_uses),
                _json(privacy),
                _json(routine),
            ),
        )


def _persist_setup_run(run: dict[str, Any]) -> None:
    with sqlite3.connect(store.database_path()) as conn:
        conn.execute(
            """
            INSERT INTO health_setup_runs(
                id, status, phase, next_action, goals_json, already_uses_json,
                privacy_json, recommendations_json, source_states_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["id"],
                run["status"],
                run["phase"],
                run["next_action"],
                _json(run["goals"]),
                _json(run["already_uses"]),
                _json(run["privacy"]),
                _json(run["recommendations"]),
                _json(run["sources"]),
            ),
        )


def _load_setup_run(setup_run_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(store.database_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM health_setup_runs WHERE id = ?",
            (setup_run_id,),
        ).fetchone()
    if row is None:
        return None
    recommendations = json.loads(row["recommendations_json"])
    sources = build_source_states(recommendations)
    next_action = _next_setup_action(sources)
    return {
        "id": row["id"],
        "status": row["status"],
        "phase": row["phase"],
        "next_action": next_action,
        "goals": json.loads(row["goals_json"]),
        "already_uses": json.loads(row["already_uses_json"]),
        "privacy": json.loads(row["privacy_json"]),
        "recommendations": recommendations,
        "sources": sources,
    }


def _latest_recommendations() -> list[dict[str, Any]] | None:
    try:
        with sqlite3.connect(store.database_path()) as conn:
            row = conn.execute(
                """
                SELECT recommendations_json
                FROM health_setup_runs
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.DatabaseError:
        return None
    if row is None:
        return None
    return json.loads(row[0])


def _sync_schedules() -> list[dict[str, Any]]:
    schedules = [
        {
            "source_slug": "oura",
            "cadence": "every 6h",
            "freshness_policy_hours": FRESHNESS_POLICY_HOURS,
        },
        {
            "source_slug": "google_calendar",
            "cadence": "every 6h",
            "freshness_policy_hours": FRESHNESS_POLICY_HOURS,
        },
        {
            "source_slug": "gmail",
            "cadence": "every 6h",
            "freshness_policy_hours": FRESHNESS_POLICY_HOURS,
        },
    ]
    return schedules


def _recent_runs() -> list[dict[str, Any]]:
    legacy = _legacy_sync_state()
    runs = []
    for provider, row in sorted(legacy.items()):
        runs.append(
            {
                "source_slug": _canonical_slug(provider),
                "provider": provider,
                "status": row.get("last_status", "never"),
                "updated_at": row.get("updated_at"),
            }
        )
    return runs


def _legacy_sync_state() -> dict[str, dict[str, Any]]:
    try:
        with store.connect() as conn:
            rows = conn.execute(
                "SELECT provider, last_status, last_sync_date, updated_at FROM sync_state"
            ).fetchall()
    except sqlite3.DatabaseError:
        return {}
    return {
        str(row["provider"]): {
            "last_status": row["last_status"],
            "last_sync_date": row["last_sync_date"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    }


def _provider_state(provider: str, legacy: dict[str, dict[str, Any]]) -> str:
    if provider == "manual_food":
        return "manual"
    if provider == "oura":
        if not oura.token_path().exists():
            return "needs_auth"
        return _state_from_sync_row(legacy.get("oura"))
    if provider in {"google_calendar", "gmail"}:
        if not context.google_workspace_available():
            return "needs_auth"
        return _state_from_sync_row(legacy.get("google_workspace"))
    return "needs_setup"


def _state_from_sync_row(row: dict[str, Any] | None) -> str:
    if row is None:
        return "needs_sync"
    status = str(row.get("last_status") or "never")
    if status == "ok":
        return "verified"
    if status == "partial":
        return "connected"
    if status == "running":
        return "syncing"
    if status == "error":
        return "needs_sync"
    return "needs_sync"


def _legacy_last_sync(provider: str, legacy: dict[str, dict[str, Any]]) -> str | None:
    if provider in {"google_calendar", "gmail"}:
        provider = "google_workspace"
    row = legacy.get(provider)
    if not row:
        return None
    return row.get("last_sync_date") or row.get("updated_at")


def _next_setup_action(sources: dict[str, dict]) -> str:
    for provider in CANONICAL_SOURCE_SLUGS:
        state = sources.get(provider, {}).get("state")
        if state in {"needs_auth", "needs_setup"}:
            return f"connect:{provider}"
        if state == "needs_sync":
            return f"sync:{provider}"
        if state in {"connected", "syncing"}:
            return f"verify:{provider}"
    return "verify:health_query"


def _privacy_mode(provider: str, privacy: dict[str, Any]) -> str:
    if provider == "gmail" and not privacy.get("email_body"):
        return "metadata_only"
    return str(
        next(
            card["privacy_mode"]
            for card in SOURCE_CAPABILITY_CARDS
            if card["provider"] == provider
        )
    )


def _recommendation_reason(provider: str, matched: list[str]) -> str:
    labels = {
        "oura": "Sleep, stress, recovery, and activity goals need wearable metrics.",
        "google_calendar": "Calendar metadata helps explain meeting load and planning context.",
        "gmail": "Gmail metadata helps compare sender and email-volume patterns.",
        "manual_food": "Manual food logs are needed for nutrition timing questions.",
    }
    return labels.get(provider, f"Matched requested goals: {', '.join(sorted(set(matched)))}.")


def _canonical_slug(provider: str) -> str:
    if provider == "google_workspace":
        return "google_calendar"
    return provider


def _normalize_list(value: list[str] | None) -> list[str]:
    return [str(item).strip().lower() for item in value or [] if str(item).strip()]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def database_path() -> Path:
    return store.database_path()

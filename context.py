from __future__ import annotations

import json
import logging
import hashlib
import re
import subprocess
import sys
import time
import webbrowser
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import store, sync_control


logger = logging.getLogger(__name__)
GMAIL_MAX_RESULTS = 500
_SENSITIVE_GOOGLE_SETUP_FLAGS = {"--auth-code", "--client-secret"}
_LOCAL_PATH_PATTERN = re.compile(
    r"(?i)("
    + re.escape("/" + "Users/")
    + r"[^/\\ \t\"']+|"
    + re.escape("/" + "home/")
    + r"[^/\\ \t\"']+|"
    + re.escape("C:" + "\\Users\\")
    + r"[^/\\ \t\"']+)"
)
_OAUTH_CODE_PATTERN = re.compile(r"(?i)([?&]code=)[^&\s]+")
_TOKEN_VALUE_PATTERN = re.compile(
    r"(?i)\b("
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|"
    r"api[_-]?key|secret[_-]?key|private[_-]?key|password"
    r")\b['\"]?(\s*[:=]\s*['\"]?)[^'\"\s,}]+"
)
_GOOGLE_TOKEN_PATTERN = re.compile(r"\b(?:ya29\.[A-Za-z0-9_-]{20,}|GOCSPX-[A-Za-z0-9_-]{10,})\b")


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.monotonic() - started) * 1000)))


def google_api_path() -> Path:
    return (
        store.hermes_home()
        / "skills"
        / "productivity"
        / "google-workspace"
        / "scripts"
        / "google_api.py"
    )


def google_setup_path() -> Path:
    return google_api_path().with_name("setup.py")


def google_token_path() -> Path:
    return store.hermes_home() / "google_token.json"


def google_client_secret_path() -> Path:
    return store.hermes_home() / "google_client_secret.json"


def google_workspace_available() -> bool:
    return google_api_path().exists() and google_token_path().exists()


def connect_google_workspace(
    *,
    client_secret: str | None = None,
    auth_code: str | None = None,
    auth_url: bool = False,
    check: bool = False,
    check_live: bool = False,
    install_deps: bool = False,
    open_browser: bool = False,
    revoke: bool = False,
) -> dict:
    setup_script = google_setup_path()
    if not setup_script.exists():
        return {
            "ok": False,
            "connected": False,
            "error": "Google Workspace skill is not installed.",
            "expected_setup_script": str(setup_script),
        }

    if install_deps:
        result = _run_google_setup(["--install-deps"])
        if not result["ok"]:
            return result

    if revoke:
        return _normalize_google_setup_result(_run_google_setup(["--revoke"]), connected=False)

    if auth_code:
        exchange = _run_google_setup(["--auth-code", auth_code])
        if not exchange["ok"]:
            return exchange
        live = _run_google_setup(["--check-live"])
        return {
            "ok": live["ok"],
            "connected": live["ok"],
            "token_path": str(google_token_path()),
            "auth": exchange,
            "live_check": live,
        }

    if client_secret:
        return _start_google_authorization(client_secret, open_browser=open_browser)

    if auth_url:
        url = _run_google_setup(["--auth-url"])
        if not url["ok"]:
            return url
        return _google_authorization_response(url, open_browser=open_browser)

    if check_live:
        return _normalize_google_setup_result(
            _run_google_setup(["--check-live"]),
            connected=google_workspace_available(),
        )

    if check:
        return _normalize_google_setup_result(
            _run_google_setup(["--check"]),
            connected=google_workspace_available(),
        )

    check_result = _run_google_setup(["--check"])
    if check_result["ok"]:
        return {
            "ok": True,
            "connected": True,
            "token_path": str(google_token_path()),
            "check": check_result,
        }

    if not google_client_secret_path().exists():
        discovered = _discover_google_client_secret()
        if discovered is not None:
            response = _start_google_authorization(
                str(discovered),
                open_browser=open_browser,
            )
            response["discovered_client_secret"] = str(discovered)
            return response
        return {
            "ok": False,
            "connected": False,
            "client_secret_required": True,
            "guidance": (
                "Run `hermes health connect-google --open-browser --client-secret "
                "/path/to/google_client_secret.json`."
            ),
            "check": check_result,
        }

    url = _run_google_setup(["--auth-url"])
    if not url["ok"]:
        return url
    return _google_authorization_response(url, open_browser=open_browser)


def sync_google_workspace(start: date, days: int = 1) -> dict:
    sync_started = time.monotonic()
    requested_days = max(days, 0)
    if not google_workspace_available():
        return {
            "ok": True,
            "calendar_days": 0,
            "email_days": 0,
            "requested_days": requested_days,
            "completed_days": 0,
            "day_results": [],
            "timings_ms": {
                "total": _elapsed_ms(sync_started),
                "calendar": 0,
                "gmail": 0,
            },
            "skipped": "Google Workspace is not connected.",
        }

    store.initialize()
    calendar_days = 0
    email_days = 0
    calendar_elapsed_ms = 0
    email_elapsed_ms = 0
    day_results = []
    with store.sync_guard("google_workspace"):
        with store.connect() as conn:
            for offset in range(requested_days):
                day = start + timedelta(days=offset)
                calendar_started = time.monotonic()
                calendar_ok = _sync_calendar_day(day, conn)
                calendar_ms = _elapsed_ms(calendar_started)
                calendar_elapsed_ms += calendar_ms
                if calendar_ok:
                    calendar_days += 1
                email_started = time.monotonic()
                email_ok = _sync_email_day(day, conn)
                email_ms = _elapsed_ms(email_started)
                email_elapsed_ms += email_ms
                if email_ok:
                    email_days += 1
                day_results.append(
                    {
                        "day": day.isoformat(),
                        "calendar_ok": calendar_ok,
                        "email_ok": email_ok,
                        "calendar_ms": calendar_ms,
                        "email_ms": email_ms,
                    }
                )
    if calendar_days < requested_days or email_days < requested_days:
        _mark_sync_partial("google_workspace")

    return {
        "ok": True,
        "calendar_days": calendar_days,
        "email_days": email_days,
        "requested_days": requested_days,
        "completed_days": len(day_results),
        "day_results": day_results,
        "timings_ms": {
            "total": _elapsed_ms(sync_started),
            "calendar": calendar_elapsed_ms,
            "gmail": email_elapsed_ms,
        },
        "skipped": None,
    }


def calendar_peek(days: int = 3) -> dict:
    if not google_workspace_available():
        return {"ok": False, "events": [], "error": "Google Workspace is not connected."}

    start = _today()
    end = start + timedelta(days=max(days, 0))
    query_start, query_end = _calendar_query_window(start, end)
    events = _run_google_json(
        [
            "calendar",
            "list",
            "--start",
            query_start,
            "--end",
            query_end,
        ]
    )
    if events is None:
        return {"ok": False, "events": [], "error": "Calendar peek skipped."}
    return {
        "ok": True,
        "events": [
            _sanitize_calendar_event(event)
            for event in _event_list(events)
            if _event_in_day_range(event, start, end)
        ],
    }


def _sync_calendar_day(day: date, conn) -> bool:
    source_id = sync_control.ensure_source(
        conn,
        source_slug="google_calendar",
        provider="google_workspace",
        connection_name="Google Workspace shared auth",
        status="connected",
        sync_mode="pull",
        metadata={"google_workspace_shared_auth": True},
    )
    sync_control.ensure_scope_rows(
        conn,
        source_id=source_id,
        scopes=[
            {
                "scope_key": "calendar.events.readonly",
                "scope_label": "Google Calendar events read-only",
            }
        ],
    )
    run_id = sync_control.start_sync_run(
        conn,
        source_id=source_id,
        trigger_kind="manual",
        request_start=day.isoformat(),
        request_end=day.isoformat(),
    )
    next_day = day + timedelta(days=1)
    query_start, query_end = _calendar_query_window(day, next_day)
    batch_id = sync_control.start_sync_batch(
        conn,
        sync_run_id=run_id,
        object_type="calendar_event",
        window_start=query_start,
        window_end=query_end,
    )
    payload = _run_google_json(
        [
            "calendar",
            "list",
            "--start",
            query_start,
            "--end",
            query_end,
        ]
    )
    if payload is None:
        sync_control.record_sync_error(
            conn,
            source_slug="google_calendar",
            sync_run_id=run_id,
            sync_batch_id=batch_id,
            object_type="calendar_event",
            error_code="google_calendar_sync_failed",
            error_message="Google Calendar adapter returned no usable JSON.",
            retryable=True,
        )
        sync_control.finish_sync_batch(
            conn,
            sync_batch_id=batch_id,
            status="error",
            cursor_after=None,
            records_seen=0,
            records_written=0,
        )
        sync_control.finish_sync_run(
            conn,
            sync_run_id=run_id,
            status="error",
            records_seen=0,
            records_written=0,
            batch_count=1,
            error_count=1,
        )
        sync_control.mark_source_synced(
            conn,
            source_slug="google_calendar",
            status="partial",
        )
        return False

    events = _event_list(payload)
    raw_ids_by_identity: dict[str, str] = {}
    for event in events:
        external_id = _calendar_event_external_id(event)
        raw_ids_by_identity[external_id] = sync_control.persist_raw_record(
            conn,
            source_id=source_id,
            sync_batch_id=batch_id,
            provider="google_workspace",
            object_type="calendar_event",
            external_id=external_id,
            payload=_sanitize_calendar_event(event),
            source_updated_at=_calendar_event_updated_at(event),
            privacy_tier="standard",
            is_redacted=True,
        )

    meeting_count = 0
    meeting_minutes = 0
    first_start: datetime | None = None
    last_end: datetime | None = None
    used_raw_ids: list[str] = []
    for event in events:
        if not _event_in_day_range(event, day, next_day):
            continue
        start, end = _event_bounds(event)
        if start is None or end is None:
            continue
        meeting_count += 1
        meeting_minutes += max(0, int((end - start).total_seconds() // 60))
        first_start = start if first_start is None else min(first_start, start)
        last_end = end if last_end is None else max(last_end, end)
        raw_record_id = raw_ids_by_identity.get(_calendar_event_external_id(event))
        if raw_record_id:
            used_raw_ids.append(raw_record_id)

    conn.execute(
        """
        INSERT INTO calendar_daily(
            day,
            meeting_count,
            meeting_minutes,
            first_meeting_start,
            last_meeting_end,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(day) DO UPDATE SET
            meeting_count = excluded.meeting_count,
            meeting_minutes = excluded.meeting_minutes,
            first_meeting_start = excluded.first_meeting_start,
            last_meeting_end = excluded.last_meeting_end,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            day.isoformat(),
            meeting_count,
            meeting_minutes,
            first_start.isoformat() if first_start else None,
            last_end.isoformat() if last_end else None,
        ),
    )
    for raw_record_id in used_raw_ids:
        sync_control.attach_lineage(
            conn,
            canonical_table="calendar_daily",
            canonical_id=day.isoformat(),
            raw_record_id=raw_record_id,
        )
    sync_control.finish_sync_batch(
        conn,
        sync_batch_id=batch_id,
        status="ok",
        cursor_after=day.isoformat(),
        records_seen=len(events),
        records_written=len(raw_ids_by_identity),
    )
    sync_control.finish_sync_run(
        conn,
        sync_run_id=run_id,
        status="ok",
        records_seen=len(events),
        records_written=len(raw_ids_by_identity),
        batch_count=1,
        error_count=0,
    )
    sync_control.update_cursor(
        conn,
        source_slug="google_calendar",
        object_type="calendar_event",
        cursor_kind="date_window_end",
        cursor_value=day.isoformat(),
        window_start=day.isoformat(),
        window_end=day.isoformat(),
    )
    sync_control.mark_source_synced(
        conn,
        source_slug="google_calendar",
        status="connected",
    )
    return True


def _sync_email_day(day: date, conn) -> bool:
    source_id = sync_control.ensure_source(
        conn,
        source_slug="gmail",
        provider="google_workspace",
        connection_name="Google Workspace shared auth",
        status="connected",
        sync_mode="pull",
        metadata={"google_workspace_shared_auth": True},
    )
    sync_control.ensure_scope_rows(
        conn,
        source_id=source_id,
        scopes=[{"scope_key": "gmail.metadata", "scope_label": "Gmail metadata"}],
    )
    run_id = sync_control.start_sync_run(
        conn,
        source_id=source_id,
        trigger_kind="manual",
        request_start=day.isoformat(),
        request_end=day.isoformat(),
    )
    batch_id = sync_control.start_sync_batch(
        conn,
        sync_run_id=run_id,
        object_type="gmail_message_metadata",
        window_start=day.isoformat(),
        window_end=day.isoformat(),
    )
    next_day = day + timedelta(days=1)
    query = f"after:{day:%Y/%m/%d} before:{next_day:%Y/%m/%d}"
    payload = _run_google_json(["gmail", "search", query, "--max", str(GMAIL_MAX_RESULTS)])
    if payload is None:
        sync_control.record_sync_error(
            conn,
            source_slug="gmail",
            sync_run_id=run_id,
            sync_batch_id=batch_id,
            object_type="gmail_message_metadata",
            error_code="gmail_sync_failed",
            error_message="Gmail adapter returned no usable JSON.",
            retryable=True,
        )
        sync_control.finish_sync_batch(
            conn,
            sync_batch_id=batch_id,
            status="error",
            cursor_after=None,
            records_seen=0,
            records_written=0,
        )
        sync_control.finish_sync_run(
            conn,
            sync_run_id=run_id,
            status="error",
            records_seen=0,
            records_written=0,
            batch_count=1,
            error_count=1,
        )
        sync_control.mark_source_synced(conn, source_slug="gmail", status="partial")
        return False

    messages = [message for message in _message_list(payload) if isinstance(message, dict)]
    raw_ids: list[str] = []
    for message in messages:
        sanitized = _sanitize_gmail_metadata(message)
        external_id = str(sanitized.get("id") or _stable_payload_id("gmail", sanitized))
        raw_ids.append(
            sync_control.persist_raw_record(
                conn,
                source_id=source_id,
                sync_batch_id=batch_id,
                provider="google_workspace",
                object_type="gmail_message_metadata",
                external_id=external_id,
                payload=sanitized,
                source_updated_at=str(sanitized.get("internalDate"))
                if sanitized.get("internalDate") is not None
                else None,
                privacy_tier="standard",
                is_redacted=len(sanitized) != len(message),
            )
        )
    conn.execute(
        """
        INSERT INTO email_daily(day, received_count, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(day) DO UPDATE SET
            received_count = excluded.received_count,
            updated_at = CURRENT_TIMESTAMP
        """,
        (day.isoformat(), len(_message_list(payload))),
    )
    for raw_record_id in raw_ids:
        sync_control.attach_lineage(
            conn,
            canonical_table="email_daily",
            canonical_id=day.isoformat(),
            raw_record_id=raw_record_id,
        )
    sync_control.finish_sync_batch(
        conn,
        sync_batch_id=batch_id,
        status="ok",
        cursor_after=day.isoformat(),
        records_seen=len(messages),
        records_written=len(raw_ids),
    )
    sync_control.finish_sync_run(
        conn,
        sync_run_id=run_id,
        status="ok",
        records_seen=len(messages),
        records_written=len(raw_ids),
        batch_count=1,
        error_count=0,
    )
    sync_control.update_cursor(
        conn,
        source_slug="gmail",
        object_type="gmail_message_metadata",
        cursor_kind="date_window_end",
        cursor_value=day.isoformat(),
        window_start=day.isoformat(),
        window_end=day.isoformat(),
    )
    sync_control.mark_source_synced(conn, source_slug="gmail", status="connected")
    return True


def _run_google_json(args: list[str]) -> Any | None:
    command = [sys.executable, str(google_api_path()), *args]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("Google Workspace adapter skipped", exc_info=True)
        return None
    if result.returncode != 0:
        logger.warning("Google Workspace adapter returned non-zero status")
        return None
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        logger.warning("Google Workspace adapter returned non-JSON output")
        return None


def _run_google_setup(args: list[str], *, raw_stdout: bool = False) -> dict:
    command = [sys.executable, str(google_setup_path()), *args]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "command": _redact_google_setup_command(command),
            "error": f"Google Workspace setup command failed: {exc}",
        }
    response = {
        "ok": result.returncode == 0,
        "command": _redact_google_setup_command(command),
        "returncode": result.returncode,
        "stdout": _redact_google_setup_text(result.stdout.strip()),
        "stderr": _redact_google_setup_text(result.stderr.strip()),
    }
    if raw_stdout:
        response["_raw_stdout"] = result.stdout.strip()
    return response


def _start_google_authorization(client_secret: str, *, open_browser: bool) -> dict:
    stored = _run_google_setup(["--client-secret", client_secret])
    if not stored["ok"]:
        return stored
    url = _run_google_setup(["--auth-url"], raw_stdout=True)
    if not url["ok"]:
        return url
    response = _google_authorization_response(url, open_browser=open_browser)
    response["client_secret_path"] = str(google_client_secret_path())
    return response


def _google_authorization_response(result: dict, *, open_browser: bool) -> dict:
    authorize_url = result.get("_raw_stdout", result["stdout"]).strip()
    response = {
        "ok": True,
        "connected": False,
        "authorize_url": authorize_url,
        "browser_opened": False,
        "guidance": (
            "Open authorize_url, approve access, copy the full localhost "
            "redirect URL, then run `hermes health connect-google --auth-code '<URL>'`."
        ),
    }
    if open_browser and authorize_url:
        try:
            response["browser_opened"] = bool(webbrowser.open(authorize_url))
        except webbrowser.Error as exc:
            response["browser_error"] = str(exc)
    if response["browser_opened"]:
        response["guidance"] = (
            "Approve access in the browser, copy the full localhost redirect URL, "
            "then run `hermes health connect-google --auth-code '<URL>'`."
        )
    return response


def _redact_google_setup_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for part in command:
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        if part in _SENSITIVE_GOOGLE_SETUP_FLAGS:
            redacted.append(part)
            redact_next = True
            continue
        flag, separator, _value = part.partition("=")
        if separator and flag in _SENSITIVE_GOOGLE_SETUP_FLAGS:
            redacted.append(f"{flag}=[REDACTED]")
            continue
        redacted.append(_redact_google_setup_text(part))
    return redacted


def _redact_google_setup_text(text: str) -> str:
    if not text:
        return text
    text = _LOCAL_PATH_PATTERN.sub("[LOCAL_PATH]", text)
    text = _OAUTH_CODE_PATTERN.sub(r"\1[REDACTED]", text)
    text = _TOKEN_VALUE_PATTERN.sub(r"\1\2[REDACTED]", text)
    return _GOOGLE_TOKEN_PATTERN.sub("[REDACTED]", text)


def _discover_google_client_secret() -> Path | None:
    candidates: list[Path] = []
    home = Path.home()
    for root in [home / "Downloads", home / "Desktop"]:
        if not root.exists():
            continue
        for pattern in [
            "client_secret*.json",
            "*google*client*.json",
            "*oauth*.json",
            "*credentials*.json",
        ]:
            candidates.extend(root.rglob(pattern))

    valid = [
        path
        for path in set(candidates)
        if path.is_file() and _is_google_client_secret_file(path)
    ]
    if not valid:
        return None
    return max(valid, key=lambda path: path.stat().st_mtime)


def _is_google_client_secret_file(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    return isinstance(payload, dict) and ("installed" in payload or "web" in payload)


def _normalize_google_setup_result(result: dict, *, connected: bool) -> dict:
    normalized = {
        "ok": result["ok"],
        "connected": connected if result["ok"] else False,
        "token_path": str(google_token_path()),
        "client_secret_path": str(google_client_secret_path()),
        "setup": result,
    }
    if not result["ok"]:
        normalized["guidance"] = (
            "Run `hermes health connect-google --open-browser --client-secret "
            "/path/to/google_client_secret.json` to start Google Workspace OAuth."
        )
    return normalized


def _event_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [event for event in payload if isinstance(event, dict)]
    if isinstance(payload, dict):
        for key in ("events", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [event for event in value if isinstance(event, dict)]
    return []


def _message_list(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("messages", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _sanitize_gmail_metadata(message: dict[str, Any]) -> dict[str, Any]:
    allowed = {"id", "threadId", "labelIds", "internalDate", "historyId", "sizeEstimate"}
    return {key: value for key, value in message.items() if key in allowed}


def _sanitize_calendar_event(event: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id",
        "iCalUID",
        "status",
        "summary",
        "start",
        "end",
        "location",
        "description",
        "attendees",
        "organizer",
        "creator",
        "transparency",
        "visibility",
        "recurrence",
        "recurringEventId",
        "eventType",
        "updated",
        "created",
    }
    sanitized: dict[str, Any] = {}
    for key, value in event.items():
        if key not in allowed:
            continue
        if key == "attendees" and isinstance(value, list):
            sanitized[key] = [_sanitize_calendar_attendee(attendee) for attendee in value]
        elif key in {"organizer", "creator"} and isinstance(value, dict):
            sanitized[key] = _sanitize_calendar_person(value)
        else:
            sanitized[key] = _sanitize_calendar_value(value)

    conference = _sanitize_calendar_conference(event.get("conferenceData"))
    if conference:
        sanitized["conferenceData"] = conference
    return sanitized


def _sanitize_calendar_attendee(attendee: Any) -> Any:
    if not isinstance(attendee, dict):
        return _sanitize_calendar_value(attendee)
    allowed = {
        "email",
        "displayName",
        "organizer",
        "self",
        "resource",
        "optional",
        "responseStatus",
        "additionalGuests",
    }
    return {
        key: _sanitize_calendar_value(value)
        for key, value in attendee.items()
        if key in allowed
    }


def _sanitize_calendar_person(person: dict[str, Any]) -> dict[str, Any]:
    allowed = {"email", "displayName", "self"}
    return {
        key: _sanitize_calendar_value(value)
        for key, value in person.items()
        if key in allowed
    }


def _sanitize_calendar_conference(conference_data: Any) -> dict[str, Any]:
    if not isinstance(conference_data, dict):
        return {}
    sanitized: dict[str, Any] = {}
    solution = conference_data.get("conferenceSolution")
    if isinstance(solution, dict):
        solution_name = solution.get("name")
        if solution_name not in (None, ""):
            sanitized["conferenceSolution"] = {
                "name": _sanitize_calendar_value(solution_name)
            }
    entry_points = conference_data.get("entryPoints")
    if isinstance(entry_points, list):
        sanitized_points = []
        for entry_point in entry_points:
            if not isinstance(entry_point, dict):
                continue
            entry_type = entry_point.get("entryPointType")
            label = entry_point.get("label")
            sanitized_point: dict[str, Any] = {}
            if entry_type not in (None, ""):
                sanitized_point["entryPointType"] = _sanitize_calendar_value(entry_type)
            if label not in (None, ""):
                sanitized_point["label"] = _sanitize_calendar_value(label)
            if sanitized_point:
                sanitized_points.append(sanitized_point)
        if sanitized_points:
            sanitized["entryPoints"] = sanitized_points
    return sanitized


def _sanitize_calendar_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_google_setup_text(value)
    if isinstance(value, list):
        return [_sanitize_calendar_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _sanitize_calendar_value(child)
            for key, child in value.items()
        }
    return value


def _calendar_event_external_id(event: dict[str, Any]) -> str:
    for key in ("id", "iCalUID", "htmlLink"):
        value = event.get(key)
        if value not in (None, ""):
            return str(value)
    return _stable_payload_id("calendar", _sanitize_calendar_event(event))


def _calendar_event_updated_at(event: dict[str, Any]) -> str | None:
    for key in ("updated", "created"):
        value = event.get(key)
        if value not in (None, ""):
            return str(value)
    _start, end = _event_bounds(event)
    return end.isoformat() if end else None


def _stable_payload_id(prefix: str, payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _mark_sync_partial(provider: str) -> None:
    with store.connect() as conn:
        conn.execute(
            """
            UPDATE sync_state
            SET last_status = 'partial',
                updated_at = ?
            WHERE provider = ?
            """,
            (datetime.now(UTC).isoformat(), provider),
        )


def _event_bounds(event: dict) -> tuple[datetime | None, datetime | None]:
    start_raw = event.get("start")
    end_raw = event.get("end")
    if _is_all_day_value(start_raw) or _is_all_day_value(end_raw):
        return None, None
    return _parse_event_datetime(start_raw), _parse_event_datetime(end_raw)


def _is_all_day_value(value: Any) -> bool:
    if isinstance(value, dict):
        return "date" in value and "dateTime" not in value
    if isinstance(value, str):
        return "T" not in value
    return False


def _parse_event_datetime(value: Any) -> datetime | None:
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("datetime")
    if not isinstance(value, str) or "T" not in value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _event_in_day_range(event: dict, start: date, end: date) -> bool:
    event_date = _event_start_date(event)
    return event_date is not None and start <= event_date < end


def _event_start_date(event: dict) -> date | None:
    value = event.get("start")
    if isinstance(value, dict) and isinstance(value.get("date"), str):
        try:
            return date.fromisoformat(value["date"])
        except ValueError:
            return None
    parsed = _parse_event_datetime(value)
    if parsed is None:
        return None
    return parsed.date()


def _calendar_query_window(start: date, end: date) -> tuple[str, str]:
    return _day_start(start - timedelta(days=1)), _day_start(end + timedelta(days=1))


def _day_start(day: date) -> str:
    return f"{day.isoformat()}T00:00:00Z"


def _today() -> date:
    return date.today()

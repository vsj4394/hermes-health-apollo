from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import types
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fake_google_client_secret() -> str:
    return "GOCSPX-" + "secret-value"


def load_module(name: str):
    package_name = "hermes_plugins.health_data"
    sys.modules.setdefault("hermes_plugins", types.ModuleType("hermes_plugins"))
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        package.__path__ = [str(ROOT)]
        sys.modules[package_name] = package
    sys.modules.pop(f"{package_name}.{name}", None)
    spec = importlib.util.spec_from_file_location(
        f"{package_name}.{name}", ROOT / f"{name}.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{package_name}.{name}"] = module
    spec.loader.exec_module(module)
    return module


def install_google_workspace(tmp_path: Path) -> Path:
    script = (
        tmp_path
        / "skills"
        / "productivity"
        / "google-workspace"
        / "scripts"
        / "google_api.py"
    )
    script.parent.mkdir(parents=True)
    script.write_text("# fake google api\n", encoding="utf-8")
    (tmp_path / "google_token.json").write_text("{}", encoding="utf-8")
    return script


def install_google_setup(tmp_path: Path) -> Path:
    script = (
        tmp_path
        / "skills"
        / "productivity"
        / "google-workspace"
        / "scripts"
        / "setup.py"
    )
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("# fake setup\n", encoding="utf-8")
    return script


def test_google_workspace_available_requires_script_and_token(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    context = load_module("context")

    assert context.google_workspace_available() is False

    install_google_workspace(tmp_path)

    assert context.google_workspace_available() is True


def test_connect_google_workspace_reports_missing_client_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    script = install_google_setup(tmp_path)
    context = load_module("context")

    def fake_run(args, **kwargs):
        assert args == [sys.executable, str(script), "--check"]
        return subprocess.CompletedProcess(
            args,
            1,
            stdout=f"NOT_AUTHENTICATED: No token at {tmp_path / 'google_token.json'}",
            stderr="",
        )

    monkeypatch.setattr(context.subprocess, "run", fake_run)

    result = context.connect_google_workspace()

    assert result["ok"] is False
    assert result["connected"] is False
    assert result["client_secret_required"] is True
    assert "hermes health connect-google --open-browser --client-secret" in result["guidance"]
    assert "Google Cloud Desktop app OAuth client" in result["guidance"]
    assert "http://localhost:1/" in result["guidance"]


def test_connect_google_workspace_client_secret_returns_auth_url(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    script = install_google_setup(tmp_path)
    context = load_module("context")
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        if args == [sys.executable, str(script), "--client-secret", "/tmp/client.json"]:
            return subprocess.CompletedProcess(args, 0, stdout="OK", stderr="")
        if args == [sys.executable, str(script), "--auth-url"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="https://accounts.google.com/o/oauth2/auth?client_id=abc\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(context.subprocess, "run", fake_run)

    opened_urls = []
    monkeypatch.setattr(context.webbrowser, "open", lambda url: opened_urls.append(url) or True)

    result = context.connect_google_workspace(client_secret="/tmp/client.json", open_browser=True)

    assert result["ok"] is True
    assert result["connected"] is False
    assert result["authorize_url"] == "https://accounts.google.com/o/oauth2/auth?client_id=abc"
    assert result["browser_opened"] is True
    assert opened_urls == ["https://accounts.google.com/o/oauth2/auth?client_id=abc"]
    assert "connect-google --auth-code" in result["guidance"]
    assert "http://localhost:1/" in result["guidance"]
    assert commands == [
        [sys.executable, str(script), "--client-secret", "/tmp/client.json"],
        [sys.executable, str(script), "--auth-url"],
    ]


def test_connect_google_workspace_discovers_downloaded_client_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    script = install_google_setup(tmp_path)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    client_secret = downloads / "client_secret_abc.apps.googleusercontent.com.json"
    client_secret.write_text(json.dumps({"installed": {"client_id": "abc"}}), encoding="utf-8")
    context = load_module("context")
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        if args == [sys.executable, str(script), "--check"]:
            return subprocess.CompletedProcess(args, 1, stdout="NOT_AUTHENTICATED", stderr="")
        if args == [sys.executable, str(script), "--client-secret", str(client_secret)]:
            return subprocess.CompletedProcess(args, 0, stdout="OK", stderr="")
        if args == [sys.executable, str(script), "--auth-url"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="https://accounts.google.com/o/oauth2/auth?client_id=abc\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(context.subprocess, "run", fake_run)

    result = context.connect_google_workspace()

    assert result["ok"] is True
    assert result["discovered_client_secret"] == str(client_secret)
    assert result["authorize_url"] == "https://accounts.google.com/o/oauth2/auth?client_id=abc"
    assert commands == [
        [sys.executable, str(script), "--check"],
        [sys.executable, str(script), "--client-secret", str(client_secret)],
        [sys.executable, str(script), "--auth-url"],
    ]


def test_connect_google_workspace_auth_code_runs_live_check(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    script = install_google_setup(tmp_path)
    context = load_module("context")
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        if args == [sys.executable, str(script), "--auth-code", "http://localhost:1/?code=abc"]:
            return subprocess.CompletedProcess(args, 0, stdout="OK", stderr="")
        if args == [sys.executable, str(script), "--check-live"]:
            return subprocess.CompletedProcess(args, 0, stdout="LIVE_CHECK_OK", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(context.subprocess, "run", fake_run)

    result = context.connect_google_workspace(auth_code="http://localhost:1/?code=abc")

    assert result["ok"] is True
    assert result["connected"] is True
    assert result["token_path"] == str(tmp_path / "google_token.json")
    serialized = json.dumps(result, sort_keys=True)
    assert "code=abc" not in serialized
    assert result["auth"]["command"][-2:] == ["--auth-code", "[REDACTED]"]
    assert commands == [
        [sys.executable, str(script), "--auth-code", "http://localhost:1/?code=abc"],
        [sys.executable, str(script), "--check-live"],
    ]


def test_google_setup_result_redacts_sensitive_output(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    script = install_google_setup(tmp_path)
    context = load_module("context")
    google_secret = fake_google_client_secret()

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            1,
            stdout='{"access_token":"ya29.secret-token-value"}',
            stderr=(
                "failed for " + "/" + "Users/alice/Downloads/client_secret.json "
                f"with client_secret={google_secret} and "
                "http://localhost:1/?code=abc123"
            ),
        )

    monkeypatch.setattr(context.subprocess, "run", fake_run)

    result = context.connect_google_workspace(auth_code="http://localhost:1/?code=abc123")

    serialized = json.dumps(result, sort_keys=True)
    assert "abc123" not in serialized
    assert google_secret not in serialized
    assert "ya29.secret-token-value" not in serialized
    assert "/" + "Users/alice" not in serialized
    assert result["command"][-2:] == ["--auth-code", "[REDACTED]"]
    assert "[LOCAL_PATH]" in result["stderr"]


def test_sync_google_workspace_skips_without_token(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    context = load_module("context")

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("google_api.py should not be called without auth")

    monkeypatch.setattr(context.subprocess, "run", fake_run)

    result = context.sync_google_workspace(date(2026, 6, 8), days=1)

    assert result["ok"] is True
    assert result["calendar_days"] == 0
    assert result["email_days"] == 0
    assert result["requested_days"] == 1
    assert result["completed_days"] == 0
    assert result["day_results"] == []
    assert result["timings_ms"]["calendar"] == 0
    assert result["timings_ms"]["gmail"] == 0
    assert result["skipped"] == "Google Workspace is not connected."
    assert calls == []


def test_sync_google_workspace_aggregates_calendar_and_gmail(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    script = install_google_workspace(tmp_path)
    context = load_module("context")

    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        assert args[0] == sys.executable
        assert args[1] == str(script)
        if args[2:4] == ["calendar", "list"]:
            assert args[4:] == [
                "--start",
                "2026-06-07T00:00:00Z",
                "--end",
                "2026-06-10T00:00:00Z",
            ]
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    [
                        {
                            "id": "event-standup",
                            "summary": "Standup",
                            "start": "2026-06-08T09:00:00+00:00",
                            "end": "2026-06-08T09:30:00+00:00",
                        },
                        {
                            "id": "event-planning",
                            "summary": "Planning",
                            "start": {"dateTime": "2026-06-08T11:00:00+00:00"},
                            "end": {"dateTime": "2026-06-08T12:15:00+00:00"},
                        },
                        {
                            "summary": "All day hold",
                            "start": {"date": "2026-06-08"},
                            "end": {"date": "2026-06-09"},
                        },
                        {
                            "id": "event-previous",
                            "summary": "Previous local day",
                            "start": "2026-06-07T23:30:00-07:00",
                            "end": "2026-06-08T00:30:00-07:00",
                        },
                        {
                            "id": "event-late",
                            "summary": "Late target local day",
                            "start": "2026-06-08T23:30:00-07:00",
                            "end": "2026-06-09T00:00:00-07:00",
                        },
                    ]
                ),
                stderr="",
            )
        if args[2:4] == ["gmail", "search"]:
            assert args[4] == "after:2026/06/08 before:2026/06/09"
            assert args[5:] == ["--max", "500"]
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps([{"id": "a"}, {"id": "b"}]),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(context.subprocess, "run", fake_run)

    result = context.sync_google_workspace(date(2026, 6, 8), days=1)

    assert result["ok"] is True
    assert result["calendar_days"] == 1
    assert result["email_days"] == 1
    assert result["requested_days"] == 1
    assert result["completed_days"] == 1
    assert result["day_results"][0]["day"] == "2026-06-08"
    assert result["day_results"][0]["calendar_ok"] is True
    assert result["day_results"][0]["email_ok"] is True
    assert result["timings_ms"]["calendar"] >= 0
    assert result["timings_ms"]["gmail"] >= 0
    assert result["timings_ms"]["total"] >= 0
    assert result["skipped"] is None
    assert len(commands) == 2

    with sqlite3.connect(tmp_path / "health.db") as conn:
        calendar = conn.execute(
            "SELECT meeting_count, meeting_minutes, first_meeting_start, last_meeting_end "
            "FROM calendar_daily WHERE day = ?",
            ("2026-06-08",),
        ).fetchone()
        email = conn.execute(
            "SELECT received_count FROM email_daily WHERE day = ?",
            ("2026-06-08",),
        ).fetchone()
        sync_state = conn.execute(
            "SELECT last_status FROM sync_state WHERE provider = ?",
            ("google_workspace",),
        ).fetchone()
        source_rows = conn.execute(
            "SELECT source_slug, status FROM health_sources ORDER BY source_slug"
        ).fetchall()
        raw_rows = conn.execute(
            """
            SELECT provider, object_type, external_id, is_redacted
            FROM raw_records
            ORDER BY provider, object_type, external_id
            """
        ).fetchall()
        lineage_rows = conn.execute(
            """
            SELECT canonical_table, canonical_id
            FROM record_lineage
            ORDER BY canonical_table, canonical_id
            """
        ).fetchall()

    assert calendar == (
        3,
        135,
        "2026-06-08T09:00:00+00:00",
        "2026-06-09T00:00:00-07:00",
    )
    assert email == (2,)
    assert sync_state == ("ok",)
    assert ("google_calendar", "connected") in source_rows
    assert ("gmail", "connected") in source_rows
    assert ("google_workspace", "calendar_event", "event-planning", 1) in raw_rows
    assert ("google_workspace", "calendar_event", "event-late", 1) in raw_rows
    assert ("google_workspace", "gmail_message_metadata", "a", 0) in raw_rows
    assert ("calendar_daily", "2026-06-08") in lineage_rows
    assert ("email_daily", "2026-06-08") in lineage_rows


def test_gmail_raw_persistence_strips_body_like_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    script = install_google_workspace(tmp_path)
    context = load_module("context")

    def fake_run(args, **kwargs):
        if args[2:4] == ["calendar", "list"]:
            return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")
        if args[2:4] == ["gmail", "search"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    [
                        {
                            "id": "msg-1",
                            "threadId": "thr-1",
                            "labelIds": ["INBOX"],
                            "snippet": "private body text",
                            "payload": {"body": {"data": "secret"}},
                        }
                    ]
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(context.subprocess, "run", fake_run)

    result = context.sync_google_workspace(date(2026, 6, 8), days=1)

    assert result["ok"] is True
    assert result["calendar_days"] == 1
    assert result["email_days"] == 1
    assert result["day_results"][0]["calendar_ok"] is True
    assert result["day_results"][0]["email_ok"] is True
    assert result["timings_ms"]["total"] >= 0
    assert result["skipped"] is None
    with sqlite3.connect(tmp_path / "health.db") as conn:
        payload_json = conn.execute(
            "SELECT payload_json FROM raw_records WHERE object_type = 'gmail_message_metadata'"
        ).fetchone()[0]
        redacted = conn.execute(
            "SELECT is_redacted FROM raw_records WHERE object_type = 'gmail_message_metadata'"
        ).fetchone()[0]

    payload = json.loads(payload_json)
    assert "snippet" not in payload
    assert "payload" not in payload
    assert payload == {"id": "msg-1", "labelIds": ["INBOX"], "threadId": "thr-1"}
    assert redacted == 1


def test_calendar_peek_reads_future_events_without_persisting(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    script = install_google_workspace(tmp_path)
    context = load_module("context")
    google_secret = fake_google_client_secret()

    def fake_today():
        return date(2026, 6, 8)

    def fake_run(args, **kwargs):
        assert args == [
            sys.executable,
            str(script),
            "calendar",
            "list",
            "--start",
            "2026-06-07T00:00:00Z",
            "--end",
            "2026-06-11T00:00:00Z",
        ]
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps(
                [
                    {
                        "summary": "Tomorrow planning",
                        "start": "2026-06-09T14:00:00+00:00",
                        "end": "2026-06-09T14:45:00+00:00",
                        "attendees": [
                            {
                                "email": "person@example.test",
                                "displayName": "Stressful Stakeholder",
                                "comment": "not returned",
                            }
                        ],
                        "conferenceData": {
                            "conferenceSolution": {"name": "Google Meet"},
                            "entryPoints": [
                                {
                                    "entryPointType": "video",
                                    "label": "Meet",
                                    "uri": "https://meet.example.test/abc?code=secret",
                                    "pin": "123456",
                                }
                            ],
                        },
                        "description": f"planning details with client_secret={google_secret}",
                        "location": "private office",
                    },
                    {
                        "summary": "Yesterday planning",
                        "start": "2026-06-07T14:00:00+00:00",
                        "end": "2026-06-07T14:45:00+00:00",
                    },
                    {
                        "summary": "Outside range",
                        "start": "2026-06-10T01:00:00+00:00",
                        "end": "2026-06-10T01:30:00+00:00",
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(context, "_today", fake_today)
    monkeypatch.setattr(context.subprocess, "run", fake_run)

    result = context.calendar_peek(days=2)

    assert result == {
        "ok": True,
        "events": [
            {
                "summary": "Tomorrow planning",
                "start": "2026-06-09T14:00:00+00:00",
                "end": "2026-06-09T14:45:00+00:00",
                "attendees": [
                    {
                        "email": "person@example.test",
                        "displayName": "Stressful Stakeholder",
                    }
                ],
                "conferenceData": {
                    "conferenceSolution": {"name": "Google Meet"},
                    "entryPoints": [{"entryPointType": "video", "label": "Meet"}],
                },
                "description": "planning details with client_secret=[REDACTED]",
                "location": "private office",
            }
        ],
    }
    serialized = json.dumps(result, sort_keys=True)
    assert "https://meet.example.test" not in serialized
    assert google_secret not in serialized
    assert "123456" not in serialized

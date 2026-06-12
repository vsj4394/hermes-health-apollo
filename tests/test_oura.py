from __future__ import annotations

import importlib.util
import io
import json
import os
import socket
import sqlite3
import sys
import threading
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse
from urllib import request as urllib_request

import pytest


ROOT = Path(__file__).resolve().parents[1]


class _FakeUrlopenResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.status = status
        self._body = body
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


def load_module(name: str):
    package_name = "hermes_plugins.health_data"
    sys.modules.setdefault("hermes_plugins", types.ModuleType("hermes_plugins"))
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        package.__path__ = [str(ROOT)]
        sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(
        f"{package_name}.{name}", ROOT / f"{name}.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def modules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return {
        "store": load_module("store"),
        "oura": load_module("oura"),
        "normalize": load_module("normalize"),
    }


def test_token_path_and_atomic_save_are_private(modules, tmp_path: Path):
    oura = modules["oura"]
    token = {
        "access_token": "access-one",
        "refresh_token": "refresh-one",
        "expires_at": "2026-06-09T12:00:00+00:00",
    }

    assert oura.token_path() == tmp_path / "oura_token.json"

    oura.save_token(token)

    assert oura.load_token() == token
    assert not (tmp_path / "auth.json").exists()
    if os.name != "nt":
        assert oct((tmp_path / "oura_token.json").stat().st_mode & 0o777) == "0o600"


def test_database_and_sqlite_sidecars_are_private(modules, tmp_path: Path):
    store = modules["store"]
    db_path = store.initialize()

    for path in [
        db_path,
        tmp_path / "health.db-wal",
        tmp_path / "health.db-shm",
        tmp_path / "health.db-journal",
    ]:
        path.touch(exist_ok=True)
        if os.name != "nt":
            os.chmod(path, 0o644)

    store._chmod_private_database_files(db_path)

    if os.name != "nt":
        for path in [
            db_path,
            tmp_path / "health.db-wal",
            tmp_path / "health.db-shm",
            tmp_path / "health.db-journal",
        ]:
            assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_refresh_token_uses_pending_shadow_and_rotates(modules, tmp_path: Path):
    oura = modules["oura"]
    clock = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
    expired = {
        "access_token": "old-access",
        "refresh_token": "old-refresh",
        "expires_at": (clock - timedelta(minutes=10)).isoformat(),
        "scope": "daily",
    }
    oura.save_token(expired)
    calls = []

    def http_post(url: str, data: dict, headers: dict | None = None) -> dict:
        calls.append((url, data, headers))
        pending = json.loads((tmp_path / "oura_token.json.pending").read_text("utf-8"))
        assert pending["refresh_token"] == "old-refresh"
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 1800,
        }

    refreshed = oura.refresh_access_token(
        client_id="client-id",
        client_secret="client-secret",
        http_post=http_post,
        now=lambda: clock,
    )

    assert refreshed["access_token"] == "new-access"
    assert refreshed["refresh_token"] == "new-refresh"
    assert refreshed["scope"] == "daily"
    assert oura.load_token()["refresh_token"] == "new-refresh"
    assert not (tmp_path / "oura_token.json.pending").exists()
    assert calls == [
        (
            "https://api.ouraring.com/oauth/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": "old-refresh",
                "client_id": "client-id",
                "client_secret": "client-secret",
            },
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
    ]


def test_refresh_invalid_grant_asks_to_reconnect(modules):
    oura = modules["oura"]
    oura.save_token(
        {
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        }
    )

    def invalid_grant(_url: str, _data: dict, _headers: dict | None = None) -> dict:
        return {"error": "invalid_grant"}

    with pytest.raises(oura.OuraNotConnected, match="re-run `/health connect`"):
        oura.refresh_access_token(
            client_id="client-id",
            client_secret="client-secret",
            http_post=invalid_grant,
        )


def test_connect_oura_saves_credentials_and_exchanges_code(modules, tmp_path):
    oura = modules["oura"]
    calls = []

    def http_post(url: str, data: dict, headers: dict | None = None) -> dict:
        calls.append((url, data, headers))
        return {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        }

    pending = oura.connect_oura(
        client_id="client-id",
        client_secret="client-secret",
        loopback_timeout=0,
    )

    result = oura.connect_oura(
        client_id="client-id",
        client_secret="client-secret",
        code="returned-code",
        state=pending["state"],
        http_post=http_post,
    )

    assert result["ok"] is True
    assert result["connected"] is True
    assert oura.load_token()["refresh_token"] == "refresh"
    assert not oura.pending_state_path().exists()
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert 'HERMES_OURA_CLIENT_ID="client-id"' in env_text
    assert 'HERMES_OURA_CLIENT_SECRET="client-secret"' in env_text
    assert calls == [
        (
            "https://api.ouraring.com/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": "returned-code",
                "redirect_uri": "http://localhost:43828/callback",
                "client_id": "client-id",
                "client_secret": "client-secret",
            },
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
    ]


def test_connect_oura_rejects_manual_code_without_matching_state(modules):
    oura = modules["oura"]
    pending = oura.connect_oura(
        client_id="client-id",
        client_secret="client-secret",
        loopback_timeout=0,
    )

    with pytest.raises(oura.OuraNotConnected, match="state is required"):
        oura.connect_oura(
            client_id="client-id",
            client_secret="client-secret",
            code="returned-code",
            http_post=lambda *_args, **_kwargs: {},
        )

    with pytest.raises(oura.OuraNotConnected, match="state mismatch"):
        oura.connect_oura(
            client_id="client-id",
            client_secret="client-secret",
            code="returned-code",
            state=f"{pending['state']}-wrong",
            http_post=lambda *_args, **_kwargs: {},
        )


def test_connect_oura_returns_authorize_url_without_code(modules):
    oura = modules["oura"]

    result = oura.connect_oura(
        client_id="client-id",
        client_secret="client-secret",
        loopback_timeout=0,
    )

    assert result["ok"] is False
    assert result["connected"] is False
    parsed = parse.urlparse(result["authorize_url"])
    params = parse.parse_qs(parsed.query)
    assert parsed.netloc == "cloud.ouraring.com"
    assert params["client_id"] == ["client-id"]
    assert params["redirect_uri"] == ["http://localhost:43828/callback"]
    assert params["state"] == [result["state"]]
    assert "scope" not in params
    assert result["requested_oauth_scopes"] == ""
    assert result["required_portal_scopes"] == [
        "Daily",
        "Session",
        "SpO2",
        "Stress",
        "Heartrate",
        "Tag",
        "Workout",
        "Personal",
        "Heart Health",
        "Ring Configuration",
    ]
    assert json.loads(oura.pending_state_path().read_text(encoding="utf-8")) == {
        "state": result["state"]
    }


def test_connect_oura_can_request_explicit_scopes(modules):
    oura = modules["oura"]

    result = oura.connect_oura(
        client_id="client-id",
        client_secret="client-secret",
        scopes=" daily   session   spo2 ",
        loopback_timeout=0,
    )

    parsed = parse.urlparse(result["authorize_url"])
    params = parse.parse_qs(parsed.query)
    assert params["scope"] == ["daily session spo2"]
    assert result["requested_oauth_scopes"] == "daily session spo2"


def test_connect_oura_loopback_validates_state_and_saves_token(modules):
    oura = modules["oura"]
    port = _free_port()
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    calls = []

    def http_post(url: str, data: dict, headers: dict | None = None) -> dict:
        calls.append((url, data, headers))
        return {
            "access_token": "loopback-access",
            "refresh_token": "loopback-refresh",
            "expires_in": 3600,
        }

    def browser_open(auth_url: str) -> bool:
        parsed = parse.urlparse(auth_url)
        params = parse.parse_qs(parsed.query)
        callback = (
            f"{params['redirect_uri'][0]}?"
            f"code=loopback-code&state={params['state'][0]}"
        )
        thread = threading.Thread(
            target=lambda: urllib_request.urlopen(callback, timeout=5).read(),
            daemon=True,
        )
        thread.start()
        return True

    result = oura.connect_oura(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri=redirect_uri,
        browser_open=browser_open,
        http_post=http_post,
        loopback_timeout=5,
    )

    assert result["ok"] is True
    assert oura.load_token()["access_token"] == "loopback-access"
    assert calls[0][1]["code"] == "loopback-code"
    assert calls[0][1]["redirect_uri"] == redirect_uri


def test_connect_oura_loopback_timeout_returns_manual_guidance(modules):
    oura = modules["oura"]

    result = oura.connect_oura(
        client_id="client-id",
        client_secret="client-secret",
        browser_open=lambda _url: True,
        loopback_timeout=0.01,
    )

    assert result["ok"] is False
    assert result["connected"] is False
    assert "timed out" in result["error"]
    assert result["authorize_url"].startswith("https://cloud.ouraring.com/oauth/authorize?")
    assert result["state"]
    assert oura.pending_state_path().exists()
    assert "hermes health connect --code <code> --state <state>" in result["guidance"]


def test_paginated_request_retries_429_and_uses_next_token(modules):
    oura = modules["oura"]
    calls = []
    sleeps = []
    responses = [
        oura.OuraResponse(429, {}, headers={"Retry-After": "3"}),
        oura.OuraResponse(
            200,
            {"data": [{"id": "first"}], "next_token": "cursor-1"},
        ),
        oura.OuraResponse(200, {"data": [{"id": "second"}]}),
    ]

    def request(method: str, url: str, *, params: dict, headers: dict) -> object:
        calls.append((method, url, dict(params), dict(headers)))
        return responses.pop(0)

    rows = oura.fetch_paginated(
        "/v2/usercollection/daily_sleep",
        access_token="secret-access",
        params={"start_date": "2026-06-01"},
        request=request,
        sleep=sleeps.append,
    )

    assert rows == [{"id": "first"}, {"id": "second"}]
    assert sleeps == [3.0]
    assert calls[0][2] == {"start_date": "2026-06-01"}
    assert calls[1][2] == {"start_date": "2026-06-01"}
    assert calls[2][2] == {"start_date": "2026-06-01", "next_token": "cursor-1"}
    assert calls[0][3]["Authorization"] == "Bearer secret-access"


def test_http_request_converts_429_http_error_to_retryable_response(monkeypatch, modules):
    oura = modules["oura"]
    calls = []

    def urlopen(_request, timeout: int):
        calls.append(timeout)
        if len(calls) == 1:
            raise urllib_error.HTTPError(
                url="https://api.ouraring.com/v2/usercollection/daily_sleep",
                code=429,
                msg="Too Many Requests",
                hdrs={"Retry-After": "4"},
                fp=io.BytesIO(b'{"error":"rate_limited"}'),
            )
        return _FakeUrlopenResponse(
            200,
            b'{"data":[{"id":"after-retry"}]}',
            {"Content-Type": "application/json"},
        )

    monkeypatch.setattr(oura.urllib_request, "urlopen", urlopen)

    rows = oura.fetch_paginated(
        "/v2/usercollection/daily_sleep",
        access_token="secret-access",
        request=oura.http_request,
        sleep=lambda _seconds: None,
    )

    assert rows == [{"id": "after-retry"}]
    assert calls == [30, 30]


def test_http_post_form_returns_json_error_from_http_error(monkeypatch, modules):
    oura = modules["oura"]

    def urlopen(_request, timeout: int):
        raise urllib_error.HTTPError(
            url="https://api.ouraring.com/oauth/token",
            code=400,
            msg="Bad Request",
            hdrs={"Content-Type": "application/json"},
            fp=io.BytesIO(b'{"error":"invalid_grant"}'),
        )

    monkeypatch.setattr(oura.urllib_request, "urlopen", urlopen)

    assert oura.http_post_form(
        "https://api.ouraring.com/oauth/token",
        {"grant_type": "refresh_token"},
    ) == {"error": "invalid_grant"}


def test_sync_oura_fetches_required_endpoints_and_upserts(modules):
    store = modules["store"]
    oura = modules["oura"]
    store.initialize()
    oura.save_token(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": "2099-06-09T12:00:00+00:00",
        }
    )
    responses = {
        "/v2/usercollection/daily_sleep": [
            {"day": "2026-06-08", "score": 81, "total_sleep_duration": 25200}
        ],
        "/v2/usercollection/daily_readiness": [
            {"day": "2026-06-08", "score": 76, "contributors": {"hrv_balance": 68}}
        ],
        "/v2/usercollection/daily_stress": [
            {
                "day": "2026-06-08",
                "stress_high": 3600,
                "recovery_high": 1800,
                "day_summary": "stressful",
            }
        ],
        "/v2/usercollection/daily_activity": [
            {"day": "2026-06-08", "score": 84}
        ],
        "/v2/usercollection/daily_spo2": [
            {"day": "2026-06-08", "spo2_percentage": {"average": 97.2}}
        ],
        "/v2/usercollection/sleep": [
            {
                "id": "sleep-1",
                "day": "2026-06-08",
                "type": "long_sleep",
                "bedtime_start": "2026-06-08T22:40:00-04:00",
                "bedtime_end": "2026-06-09T06:50:00-04:00",
                "total_sleep_duration": 29400,
                "deep_sleep_duration": 5400,
                "heart_rate": {
                    "timestamp": "2026-06-08T22:45:00-04:00",
                    "interval": 300,
                    "items": [55, 56, None],
                },
            }
        ],
        "/v2/usercollection/heartrate": [
            {
                "timestamp": "2026-06-08T12:00:00.000+00:00",
                "timestamp_unix": 1780920000000,
                "bpm": 61,
                "source": "awake",
            }
        ],
        "/v2/usercollection/ring_battery_level": [
            {
                "timestamp": "2026-06-08T12:00:00.000+00:00",
                "timestamp_unix": 1780920000000,
                "level": 88,
                "charging": False,
                "in_charger": False,
            }
        ],
        "/v2/usercollection/personal_info": {
            "id": "user-1",
            "age": 38,
            "height": 1.8,
            "weight": 78.5,
            "email": "user@example.test",
            "biological_sex": "male",
        },
        "/v2/usercollection/workout": [
            {
                "id": "workout-1",
                "day": "2026-06-08",
                "activity": "running",
                "calories": 320,
                "distance": 5000,
                "intensity": "moderate",
                "source": "confirmed",
                "start_datetime": "2026-06-08T17:00:00-04:00",
                "end_datetime": "2026-06-08T17:40:00-04:00",
            }
        ],
        "/v2/usercollection/session": [
            {
                "id": "session-1",
                "day": "2026-06-08",
                "type": "meditation",
                "start_datetime": "2026-06-08T08:00:00-04:00",
                "end_datetime": "2026-06-08T08:10:00-04:00",
                "heart_rate": {
                    "timestamp": "2026-06-08T08:00:00-04:00",
                    "interval": 300,
                    "items": [60, 58],
                },
            }
        ],
        "/v2/usercollection/tag": [
            {
                "id": "tag-1",
                "day": "2026-06-08",
                "text": "late caffeine",
                "timestamp": "2026-06-08T15:00:00-04:00",
                "tags": ["caffeine"],
            }
        ],
        "/v2/usercollection/enhanced_tag": [
            {
                "id": "enhanced-tag-1",
                "start_day": "2026-06-08",
                "start_time": "2026-06-08T15:00:00",
                "tag_type_code": "custom",
                "custom_name": "late caffeine",
            }
        ],
        "/v2/usercollection/daily_resilience": [
            {
                "id": "resilience-1",
                "day": "2026-06-08",
                "level": "solid",
                "contributors": {"sleep": "high"},
            }
        ],
        "/v2/usercollection/daily_cardiovascular_age": [
            {
                "id": "heart-health-1",
                "day": "2026-06-08",
                "vascular_age": 34,
                "pulse_wave_velocity": 6.2,
            }
        ],
        "/v2/usercollection/vO2_max": [
            {
                "id": "vo2-1",
                "day": "2026-06-08",
                "timestamp": "2026-06-08T17:40:00-04:00",
                "vo2_max": 44,
            }
        ],
        "/v2/usercollection/sleep_time": [
            {
                "id": "sleep-time-1",
                "day": "2026-06-08",
                "recommendation": "maintain",
                "status": "available",
                "optimal_bedtime": {"start_offset": 82800, "end_offset": 84600},
            }
        ],
        "/v2/usercollection/rest_mode_period": [
            {
                "id": "rest-mode-1",
                "start_day": "2026-06-08",
                "start_time": "2026-06-08T09:00:00-04:00",
                "episodes": [{"tag": "sick"}],
            }
        ],
        "/v2/usercollection/ring_configuration": [
            {
                "id": "ring-1",
                "color": "silver",
                "design": "heritage",
                "firmware_version": "3.0.1",
                "hardware_type": "gen3",
                "set_up_at": "2026-01-01T00:00:00.000Z",
                "size": 10,
            }
        ],
    }
    calls = []

    def request(method: str, url: str, *, params: dict, headers: dict) -> object:
        endpoint = parse.urlparse(url).path
        calls.append((method, endpoint, dict(params), dict(headers)))
        payload = responses[endpoint]
        if endpoint == "/v2/usercollection/personal_info":
            return oura.OuraResponse(200, payload)
        return oura.OuraResponse(200, {"data": payload})

    result = oura.sync_oura(
        request=request,
        today=datetime(2026, 6, 9, tzinfo=UTC),
    )

    assert result["ok"] is True
    assert result["daily_rows"] == 1
    assert result["sleep_sessions"] == 1
    assert result["heart_rate_samples"] == 5
    assert result["workouts"] == 1
    assert result["sessions"] == 1
    assert result["tags"] == 1
    assert result["daily_resilience_rows"] == 1
    assert result["endpoint_errors"] == {}
    assert {call[1] for call in calls} == set(responses)
    assert all(
        call[2] == {"start_date": "2026-06-07", "end_date": "2026-06-09"}
        for call in calls
        if call[1]
        not in {
            "/v2/usercollection/heartrate",
            "/v2/usercollection/ring_battery_level",
            "/v2/usercollection/ring_configuration",
            "/v2/usercollection/personal_info",
        }
    )
    assert [
        call[2]
        for call in calls
        if call[1] == "/v2/usercollection/heartrate"
    ] == [
        {
            "start_datetime": "2026-06-07T00:00:00+00:00",
            "end_datetime": "2026-06-10T00:00:00+00:00",
        }
    ]
    assert [
        call[2]
        for call in calls
        if call[1] == "/v2/usercollection/ring_configuration"
    ] == [{}]
    with sqlite3.connect(store.database_path()) as conn:
        daily = conn.execute(
            """
            SELECT readiness_score, sleep_score, activity_score, primary_bedtime_start
            FROM oura_daily WHERE day = '2026-06-08'
            """
        ).fetchone()
        heart_rate_sources = conn.execute(
            """
            SELECT source, COUNT(*)
            FROM oura_heart_rate
            GROUP BY source
            ORDER BY source
            """
        ).fetchall()
        workout = conn.execute(
            "SELECT activity, calories FROM oura_workouts"
        ).fetchone()
        personal = conn.execute(
            "SELECT age, email FROM oura_personal_info"
        ).fetchone()
        sync_state = conn.execute(
            "SELECT last_sync_date, last_status FROM sync_state WHERE provider = 'oura'"
        ).fetchone()
        source = conn.execute(
            """
            SELECT source_id, status, last_synced_at
            FROM health_sources
            WHERE source_slug = 'oura'
            """
        ).fetchone()
        run = conn.execute(
            """
            SELECT status, records_seen, records_written, batch_count, error_count
            FROM sync_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
        raw_count = conn.execute(
            "SELECT COUNT(*) FROM raw_records WHERE provider = 'oura'"
        ).fetchone()[0]
        sensitive_personal = conn.execute(
            """
            SELECT privacy_tier
            FROM raw_records
            WHERE provider = 'oura' AND object_type = 'personal_info'
            """
        ).fetchone()
        daily_lineage = conn.execute(
            """
            SELECT COUNT(*)
            FROM record_lineage
            WHERE canonical_table = 'oura_daily' AND canonical_id = '2026-06-08'
            """
        ).fetchone()[0]
        cursor = conn.execute(
            """
            SELECT cursor_value
            FROM sync_cursors
            WHERE source_id = ? AND object_type = 'daily' AND cursor_kind = 'date_window_end'
            """,
            (source[0],),
        ).fetchone()

    assert daily == (76, 81, 84, "2026-06-08T22:40:00-04:00")
    assert heart_rate_sources == [("awake", 1), ("session", 2), ("sleep", 2)]
    assert workout == ("running", 320.0)
    assert personal == (38, "user@example.test")
    assert sync_state == ("2026-06-09", "ok")
    assert source[1] == "connected"
    assert source[2] is not None
    assert run == ("ok", raw_count, raw_count, len(responses), 0)
    assert raw_count >= len(responses)
    assert sensitive_personal == ("sensitive",)
    assert daily_lineage >= 5
    assert cursor == ("2026-06-09",)


def test_sync_oura_accepts_explicit_date_range_for_backfill(modules):
    store = modules["store"]
    oura = modules["oura"]
    store.initialize()
    oura.save_token(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": "2099-06-09T12:00:00+00:00",
        }
    )
    calls = []

    def request(method: str, url: str, *, params: dict, headers: dict) -> object:
        calls.append((parse.urlparse(url).path, dict(params)))
        return oura.OuraResponse(200, {"data": []})

    result = oura.sync_oura(
        request=request,
        start_date="2026-05-12",
        end_date="2026-06-10",
    )

    assert result["ok"] is True
    assert result["start_date"] == "2026-05-12"
    assert result["end_date"] == "2026-06-10"
    assert all(
        params == {"start_date": "2026-05-12", "end_date": "2026-06-10"}
        for endpoint, params in calls
        if endpoint
        not in {
            "/v2/usercollection/heartrate",
            "/v2/usercollection/ring_battery_level",
            "/v2/usercollection/ring_configuration",
            "/v2/usercollection/personal_info",
        }
    )
    assert all(
        params
        == {
            "start_datetime": "2026-05-12T00:00:00+00:00",
            "end_datetime": "2026-06-11T00:00:00+00:00",
        }
        for endpoint, params in calls
        if endpoint
        in {
            "/v2/usercollection/heartrate",
            "/v2/usercollection/ring_battery_level",
        }
    )
    with sqlite3.connect(store.database_path()) as conn:
        sync_state = conn.execute(
            "SELECT last_sync_date, last_status FROM sync_state WHERE provider = 'oura'"
        ).fetchone()

    assert sync_state == ("2026-06-10", "ok")


def test_sync_oura_reports_partial_status_for_endpoint_errors(modules):
    store = modules["store"]
    oura = modules["oura"]
    store.initialize()
    oura.save_token(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": "2099-06-09T12:00:00+00:00",
        }
    )

    def request(_method: str, url: str, *, params: dict, headers: dict) -> object:
        endpoint = parse.urlparse(url).path
        if endpoint == "/v2/usercollection/heartrate":
            return oura.OuraResponse(403, {"error": "missing_scope"})
        if endpoint == "/v2/usercollection/personal_info":
            return oura.OuraResponse(200, {"id": "user-1"})
        return oura.OuraResponse(200, {"data": []})

    result = oura.sync_oura(
        request=request,
        start_date="2026-06-08",
        end_date="2026-06-10",
    )

    assert result["ok"] is True
    assert result["endpoint_errors"] == {
        "heart_rate": "Oura API request failed with status 403."
    }
    with sqlite3.connect(store.database_path()) as conn:
        sync_state = conn.execute(
            "SELECT last_sync_date, last_status FROM sync_state WHERE provider = 'oura'"
        ).fetchone()
        error_row = conn.execute(
            """
            SELECT object_type, retryable
            FROM sync_errors
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
        run_row = conn.execute(
            """
            SELECT status, error_count
            FROM sync_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()

    assert sync_state == ("2026-06-10", "partial")
    assert error_row == ("heart_rate", 1)
    assert run_row == ("partial", 1)


def test_sync_oura_surfaces_stale_sleep_coverage_after_empty_sleep_endpoint(modules):
    store = modules["store"]
    oura = modules["oura"]
    store.initialize()
    oura.save_token(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": "2099-06-09T12:00:00+00:00",
        }
    )
    with sqlite3.connect(store.database_path()) as conn:
        conn.execute(
            """
            INSERT INTO oura_sleep_sessions(id, day, type, raw_json)
            VALUES ('old-sleep', '2025-08-03', 'long_sleep', '{}')
            """
        )

    def request(_method: str, url: str, *, params: dict, headers: dict) -> object:
        endpoint = parse.urlparse(url).path
        if endpoint == "/v2/usercollection/daily_sleep":
            return oura.OuraResponse(
                200,
                {
                    "data": [
                        {
                            "day": "2026-06-08",
                            "score": 81,
                            "total_sleep_duration": 25200,
                        }
                    ]
                },
            )
        if endpoint == "/v2/usercollection/personal_info":
            return oura.OuraResponse(200, {"data": []})
        return oura.OuraResponse(200, {"data": []})

    result = oura.sync_oura(
        request=request,
        start_date="2026-06-08",
        end_date="2026-06-10",
    )

    sleep_diagnostic = result["coverage_diagnostics"]["sleep_sessions"]
    sleep_time_diagnostic = result["coverage_diagnostics"]["sleep_time"]

    assert result["ok"] is True
    assert result["daily_rows"] == 1
    assert result["sleep_sessions"] == 0
    assert result["endpoint_errors"] == {}
    assert result["endpoint_counts"]["daily_sleep"]["records"] == 1
    assert result["endpoint_counts"]["sleep"]["status"] == "ok"
    assert result["endpoint_counts"]["sleep"]["records"] == 0
    assert result["duration_ms"] >= 0
    assert sleep_diagnostic["status"] == "stale_local_coverage"
    assert sleep_diagnostic["local_latest_day"] == "2025-08-03"
    assert sleep_diagnostic["fetched_rows"] == 0
    assert sleep_diagnostic["normalized_rows"] == 0
    assert sleep_diagnostic["supporting_daily_sleep_rows"] == 1
    assert "OpenAPI 1.34" in sleep_diagnostic["message"]
    assert sleep_time_diagnostic["status"] == "empty_endpoint_response"
    assert sleep_time_diagnostic["supporting_daily_sleep_rows"] == 1


def test_sync_oura_does_not_move_cursor_backwards_for_historical_backfill(modules):
    store = modules["store"]
    oura = modules["oura"]
    store.initialize()
    oura.save_token(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": "2099-06-09T12:00:00+00:00",
        }
    )
    with sqlite3.connect(store.database_path()) as conn:
        conn.execute(
            """
            INSERT INTO sync_state(provider, last_sync_date, last_status, updated_at)
            VALUES ('oura', '2026-06-10', 'ok', '2026-06-10T00:00:00+00:00')
            """
        )

    def request(_method: str, _url: str, *, params: dict, headers: dict) -> object:
        return oura.OuraResponse(200, {"data": []})

    result = oura.sync_oura(
        request=request,
        start_date="2026-05-01",
        end_date="2026-05-31",
    )

    assert result["ok"] is True
    with sqlite3.connect(store.database_path()) as conn:
        sync_state = conn.execute(
            "SELECT last_sync_date, last_status FROM sync_state WHERE provider = 'oura'"
        ).fetchone()

    assert sync_state == ("2026-06-10", "ok")


def test_sync_window_end_date_only_uses_three_day_window(modules):
    store = modules["store"]
    oura = modules["oura"]
    store.initialize()
    with sqlite3.connect(store.database_path()) as conn:
        conn.execute(
            """
            INSERT INTO sync_state(provider, last_sync_date, last_status, updated_at)
            VALUES ('oura', '2026-06-10', 'ok', '2026-06-10T00:00:00+00:00')
            """
        )

    assert oura.sync_window("2026-06-11", end_date="2026-05-31") == (
        "2026-05-29",
        "2026-05-31",
    )


def test_sync_window_reports_invalid_date_strings(modules):
    oura = modules["oura"]

    with pytest.raises(oura.OuraAPIError, match="start_date must be YYYY-MM-DD"):
        oura.sync_window(
            "2026-06-11",
            start_date="not-a-date",
            end_date="2026-06-10",
        )
    with pytest.raises(oura.OuraAPIError, match="end_date must be YYYY-MM-DD"):
        oura.sync_window(
            "2026-06-11",
            start_date="2026-06-08",
            end_date="not-a-date",
        )


def test_datetime_window_chunks_respect_oura_thirty_day_limit(modules):
    oura = modules["oura"]

    chunks = oura.datetime_window_chunks("2026-01-01", "2026-03-05")

    assert chunks == [
        {
            "start_datetime": "2026-01-01T00:00:00+00:00",
            "end_datetime": "2026-01-31T00:00:00+00:00",
        },
        {
            "start_datetime": "2026-01-31T00:00:00+00:00",
            "end_datetime": "2026-03-02T00:00:00+00:00",
        },
        {
            "start_datetime": "2026-03-02T00:00:00+00:00",
            "end_datetime": "2026-03-06T00:00:00+00:00",
        },
    ]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_normalize_and_upsert_oura_rows_with_primary_sleep(modules):
    store = modules["store"]
    normalize = modules["normalize"]
    db_path = store.initialize()

    daily_rows = normalize.normalize_daily_rows(
        daily_sleep=[
            {
                "day": "2026-06-08",
                "score": 81,
                "contributors": {"deep_sleep": 91},
                "total_sleep_duration": 25_200,
            }
        ],
        readiness=[
            {
                "day": "2026-06-08",
                "score": 76,
                "contributors": {"hrv_balance": 68},
            }
        ],
        stress=[
            {
                "day": "2026-06-08",
                "stress_high": 3600,
                "recovery_high": 1800,
                "day_summary": "stressful",
            }
        ],
        activity=[{"day": "2026-06-08", "score": 84}],
        spo2=[{"day": "2026-06-08", "spo2_percentage": {"average": 97.2}}],
    )
    sessions = normalize.normalize_sleep_sessions(
        [
            {
                "id": "nap",
                "day": "2026-06-08",
                "type": "rest",
                "bedtime_start": "2026-06-08T14:00:00-04:00",
                "bedtime_end": "2026-06-08T14:40:00-04:00",
                "total_sleep_duration": 2400,
                "deep_sleep_duration": 0,
            },
            {
                "id": "short",
                "day": "2026-06-08",
                "type": "sleep",
                "bedtime_start": "2026-06-08T23:30:00-04:00",
                "bedtime_end": "2026-06-09T05:30:00-04:00",
                "total_sleep_duration": 21_600,
                "deep_sleep_duration": 3600,
            },
            {
                "id": "long",
                "day": "2026-06-08",
                "type": "long_sleep",
                "bedtime_start": "2026-06-08T22:40:00-04:00",
                "bedtime_end": "2026-06-09T06:50:00-04:00",
                "total_sleep_duration": 29_400,
                "deep_sleep_duration": 5400,
            },
        ]
    )

    with sqlite3.connect(db_path) as conn:
        normalize.upsert_oura_rows(conn, daily_rows, sessions)
        normalize.upsert_oura_rows(
            conn,
            normalize.normalize_daily_rows(
                daily_sleep=[{"day": "2026-06-08", "score": 83}]
            ),
            [],
        )
        daily = conn.execute(
            """
            SELECT readiness_score, sleep_score, activity_score, stress_high_seconds,
                   recovery_high_seconds, stress_day_summary, hrv_balance, spo2_average,
                   total_sleep_duration_seconds, deep_sleep_duration_seconds,
                   primary_bedtime_start, primary_bedtime_end
            FROM oura_daily WHERE day = '2026-06-08'
            """
        ).fetchone()
        sleep_count = conn.execute(
            "SELECT COUNT(*) FROM oura_sleep_sessions"
        ).fetchone()[0]

    assert daily == (
        76,
        83,
        84,
        3600,
        1800,
        "stressful",
        68,
        97.2,
        29400,
        5400,
        "2026-06-08T22:40:00-04:00",
        "2026-06-09T06:50:00-04:00",
    )
    assert sleep_count == 3

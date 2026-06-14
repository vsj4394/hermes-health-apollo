"""Google Health normalization + persistence onto the canonical health tables.

This is the offline normalization layer: it maps an already-fetched Google Health
API response into the source-linked canonical tables (sample / interval / session /
daily) with raw lineage, reusing the existing source + raw-record + lineage helpers.

Out of scope here (separate follow-up PRs): live OAuth and HTTP fetch, Fitbit as a
second source, GPS/sleep-stage child tables, and semantic-layer projection. The live
connector should also populate the canonical ``*_unix`` columns when it normalizes
provider timestamps; this layer leaves them NULL because its fixtures are already
canonical UTC ('Z') strings, which the text ordering CHECK handles.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import sync_control


SOURCE_SLUG = "google_health"
PROVIDER = "google_health"

logger = logging.getLogger(__name__)

# Google Health ``dataType`` -> canonical mapping, one entry per temporal shape for
# the MVP. Extend by adding rows; each shape routes to one canonical table.
METRIC_REGISTRY: dict[str, dict[str, Any]] = {
    "com.google.heart_rate.bpm": {"shape": "sample", "metric": "heart_rate", "unit": "bpm"},
    "com.google.step_count.delta": {"shape": "interval", "metric": "steps", "unit": "count"},
    "com.google.sleep.segment": {"shape": "session", "session_type": "sleep"},
    "com.google.step_count.daily": {
        "shape": "daily",
        "metric": "steps",
        "unit": "count",
        "aggregation_kind": "provider_daily_summary",
    },
}


def persist_google_health(
    conn: sqlite3.Connection,
    *,
    responses: list[dict[str, Any]],
    sync_batch_id: str | None = None,
) -> dict[str, int]:
    """Persist Google Health ``dataPoints``-style responses into canonical tables.

    Each response is ``{"dataType", "userId", "point": [...]}``. Unregistered data
    types and points missing required timing are skipped. Returns per-shape counts.
    """
    source_id = sync_control.ensure_default_source(conn, SOURCE_SLUG)
    tz = _resolve_profile_timezone(conn)
    counts = {"sample": 0, "interval": 0, "session": 0, "daily": 0}
    for response in responses:
        spec = METRIC_REGISTRY.get(str(response.get("dataType")))
        if spec is None:
            continue
        ctx = {
            "conn": conn,
            "source_id": source_id,
            "sync_batch_id": sync_batch_id,
            "data_type": str(response.get("dataType")),
            "user_id": response.get("userId"),
            "spec": spec,
            "tz": tz,
        }
        handler = _HANDLERS[spec["shape"]]
        for point in response.get("point") or []:
            if handler(ctx, point):
                counts[spec["shape"]] += 1
    return counts


def _persist_sample(ctx: dict[str, Any], point: dict[str, Any]) -> bool:
    sample_time = point.get("startTime") or point.get("time")
    if not sample_time:
        return False
    name = point.get("name")
    key = _derive_key(ctx["data_type"], name, str(sample_time))
    value_number = _extract_number(point)
    _upsert(
        ctx["conn"],
        table="health_sample_observations",
        conflict_columns=("source_id", "observation_key"),
        row={
            "source_id": ctx["source_id"],
            "observation_key": key,
            "provider_user_id": ctx["user_id"],
            "provider_data_type": ctx["data_type"],
            "provider_point_name": name,
            "metric": ctx["spec"]["metric"],
            "sample_time": str(sample_time),
            "value_number": value_number,
            "metric_unit": ctx["spec"].get("unit"),
            "provenance_json": _provenance_json(point),
        },
    )
    _link(ctx, "sample_observation", key, point, "health_sample_observations", key)
    return True


def _persist_interval(ctx: dict[str, Any], point: dict[str, Any]) -> bool:
    start = point.get("startTime")
    end = point.get("endTime")
    if not start or not end:
        return False
    # Skip out-of-order intervals (provider clock skew) rather than letting the
    # CHECK(end_time >= start_time) raise and abort the rest of the batch. This
    # mirrors the table's text comparison exactly for the normalized timestamps
    # this layer ingests.
    if str(end) < str(start):
        return False
    name = point.get("name")
    key = _derive_key(ctx["data_type"], name, str(start), str(end))
    value_number = _extract_number(point)
    _upsert(
        ctx["conn"],
        table="health_interval_observations",
        conflict_columns=("source_id", "observation_key"),
        row={
            "source_id": ctx["source_id"],
            "observation_key": key,
            "provider_user_id": ctx["user_id"],
            "provider_data_type": ctx["data_type"],
            "provider_point_name": name,
            "metric": ctx["spec"]["metric"],
            "start_time": str(start),
            "end_time": str(end),
            "value_number": value_number,
            "metric_unit": ctx["spec"].get("unit"),
            "provenance_json": _provenance_json(point),
        },
    )
    _link(ctx, "interval_observation", key, point, "health_interval_observations", key)
    return True


def _persist_session(ctx: dict[str, Any], point: dict[str, Any]) -> bool:
    start = point.get("startTime")
    if not start:
        return False
    end = point.get("endTime")
    session_type = ctx["spec"]["session_type"]
    session_id = point.get("id")
    key = str(session_id) if session_id else _derive_key(session_type, str(start))
    _upsert(
        ctx["conn"],
        table="health_sessions",
        conflict_columns=("source_id", "session_key"),
        row={
            "source_id": ctx["source_id"],
            "session_key": key,
            "provider_user_id": ctx["user_id"],
            "provider_session_id": session_id,
            "session_type": session_type,
            "day": _local_day(start, ctx["tz"]),
            "start_time": str(start),
            "end_time": end,
            "duration_seconds": _duration_seconds(start, end),
            "provenance_json": _provenance_json(point),
        },
    )
    _link(ctx, "session", key, point, "health_sessions", key, sensitive=True)
    return True


def _persist_daily(ctx: dict[str, Any], point: dict[str, Any]) -> bool:
    start = point.get("startTime")
    # Prefer the provider's own day bucketing; otherwise derive the user-local day.
    # NOTE: `day` is part of the daily PK, so for a (rare) provider-day-less point the
    # derived day is idempotent only while the profile timezone is stable -- changing
    # the timezone between syncs would re-bucket it to a new PK row. Provider-day points
    # (the live norm) are unaffected.
    day = point.get("day") or _local_day(start, ctx["tz"])
    if not day:
        return False
    metric = ctx["spec"]["metric"]
    # aggregation_kind is a property of the source endpoint (registry), not the point.
    # Ignore any per-point aggregationKind: trusting it would let an unrecognized
    # provider value violate the CHECK (aborting the batch) and would split idempotency
    # across the PK if the field toggled between syncs.
    aggregation_kind = ctx["spec"]["aggregation_kind"]
    value_number = _extract_number(point)
    _upsert(
        ctx["conn"],
        table="daily_health_metrics",
        conflict_columns=("day", "source_id", "metric", "metric_component", "aggregation_kind"),
        row={
            "day": day,
            "source_id": ctx["source_id"],
            "metric": metric,
            "provider_data_type": ctx["data_type"],
            "aggregation_kind": aggregation_kind,
            "value_number": value_number,
            "metric_unit": ctx["spec"].get("unit"),
            "provenance_json": _provenance_json(point),
        },
    )
    # daily_health_metrics has no single key column, so the lineage canonical_id is a
    # surrogate hashed from the full composite PK (day, source_id, metric,
    # metric_component='', aggregation_kind). To join record_lineage back to a daily
    # row, recompute this key from those five columns.
    canonical_id = _derive_key(day, ctx["source_id"], metric, "", aggregation_kind)
    _link(ctx, "daily_metric", canonical_id, point, "daily_health_metrics", canonical_id)
    return True


_HANDLERS = {
    "sample": _persist_sample,
    "interval": _persist_interval,
    "session": _persist_session,
    "daily": _persist_daily,
}


def _link(
    ctx: dict[str, Any],
    object_type: str,
    external_id: str,
    point: dict[str, Any],
    canonical_table: str,
    canonical_id: str,
    *,
    sensitive: bool = False,
) -> None:
    """Persist the raw point and link it to its canonical row."""
    raw_record_id = sync_control.persist_raw_record(
        ctx["conn"],
        source_id=ctx["source_id"],
        sync_batch_id=ctx["sync_batch_id"],
        provider=PROVIDER,
        object_type=object_type,
        external_id=external_id,
        payload=point,
        source_updated_at=None,
        privacy_tier="sensitive" if sensitive else "standard",
    )
    sync_control.attach_lineage(
        ctx["conn"],
        canonical_table=canonical_table,
        canonical_id=canonical_id,
        raw_record_id=raw_record_id,
    )


def _upsert(
    conn: sqlite3.Connection,
    *,
    table: str,
    conflict_columns: tuple[str, ...],
    row: dict[str, Any],
) -> None:
    columns = list(row)
    update_columns = [c for c in columns if c not in conflict_columns]
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in update_columns)
    set_clause = f"{set_clause}, updated_at = CURRENT_TIMESTAMP" if set_clause else "updated_at = CURRENT_TIMESTAMP"
    conn.execute(
        f"""
        INSERT INTO {table}({", ".join(columns)})
        VALUES ({", ".join("?" for _ in columns)})
        ON CONFLICT({", ".join(conflict_columns)}) DO UPDATE SET
            {set_clause}
        """,
        [row[c] for c in columns],
    )


def _extract_number(point: dict[str, Any]) -> float | None:
    """Numeric value of a point (fpVal/intVal).

    Returns 0.0 for a true zero, and None for a missing or non-numeric value so a
    malformed point persists with a NULL value rather than aborting the batch.
    """
    values = point.get("value") or []
    if not values or not isinstance(values[0], dict):
        return None
    first = values[0]
    raw = first.get("fpVal")
    if raw is None:
        raw = first.get("intVal")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _provenance_json(point: dict[str, Any]) -> str:
    source = point.get("dataSource") or {}
    provenance = {
        key: source[key]
        for key in ("recordingMethod", "platform", "application", "device")
        if key in source
    }
    return json.dumps(provenance, sort_keys=True)


def _derive_key(*parts: str | None) -> str:
    """Deterministic, collision-safe, source-scoped key for the given parts.

    Google Health ``DataPoint.name`` is absent for most data types, so identity is a
    composite of data type / point name (when present) / temporal bounds. The parts
    are hashed rather than delimiter-joined so that a value containing the delimiter --
    a timezone offset like '+05:30', or a provider-supplied name -- can never make two
    distinct points collide onto the same key.
    """
    encoded = json.dumps(list(parts), separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _resolve_profile_timezone(conn: sqlite3.Connection) -> tzinfo:
    """Resolve the user's configured timezone to a tzinfo, defaulting to UTC.

    Reads the single-user ``health_profile`` ('default') row. Warns once -- rather
    than silently bucketing as UTC, which is the very off-by-one this guards against
    -- if a timezone is set but is not a known IANA zone. Single-user assumption: when
    multi-user support lands, resolve the zone per userId instead of the 'default' row.
    """
    row = conn.execute(
        "SELECT timezone FROM health_profile WHERE id = 'default'"
    ).fetchone()
    tz_name = row[0] if row else None
    if not tz_name:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown profile timezone %r; bucketing days as UTC", tz_name)
        return timezone.utc


def _parse_instant(value: str | None) -> datetime | None:
    """Parse an RFC3339 instant to an aware datetime (UTC if it carries no offset)."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _local_day(instant: str | None, tz: tzinfo) -> str | None:
    """Calendar day of an RFC3339 instant in the resolved timezone.

    Google Health returns UTC instants; bucketing on the raw UTC date would assign
    near-midnight data to the wrong local day for users far from UTC. Returns None for
    an empty/unparseable instant (the point is then skipped).
    """
    moment = _parse_instant(instant)
    if moment is None:
        return None
    return moment.astimezone(tz).date().isoformat()


def _duration_seconds(start: str | None, end: str | None) -> int | None:
    started = _parse_instant(start)
    ended = _parse_instant(end)
    if started is None or ended is None:
        return None
    return int((ended - started).total_seconds())

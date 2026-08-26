"""Durable, independently observable alert-dispatcher transport health."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


STARTING = "STARTING"
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
FAILED = "FAILED"


class AlertDispatcherUnhealthy(RuntimeError):
    """The dispatcher is stale or has lost its delivery path."""


@dataclass(frozen=True)
class DispatcherHealth:
    dispatcher_id: str
    started_at: datetime
    heartbeat_at: datetime
    state: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    consecutive_failures: int
    last_error: str | None
    updated_at: datetime


_COLUMNS = (
    "dispatcher_id,started_at,heartbeat_at,state,last_attempt_at,"
    "last_success_at,consecutive_failures,last_error,updated_at"
)


def _identity(value: str) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 128:
        raise ValueError("dispatcher identity must contain 1..128 characters")
    return result


def _record(row) -> DispatcherHealth:
    return DispatcherHealth(*row)


def register(conn, *, dispatcher_id: str) -> DispatcherHealth:
    """Create or revive one stable dispatcher identity."""
    identity = _identity(dispatcher_id)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_alert_dispatcher_health"
                " (dispatcher_id,state) VALUES (%s,'STARTING')"
                " ON CONFLICT (dispatcher_id) DO UPDATE SET"
                " heartbeat_at=clock_timestamp(),updated_at=clock_timestamp()",
                (identity,))
        conn.commit()
        return load(conn, dispatcher_id=identity)
    except BaseException:
        conn.rollback()
        raise


def heartbeat(conn, *, dispatcher_id: str) -> DispatcherHealth:
    identity = _identity(dispatcher_id)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_alert_dispatcher_health SET"
                " heartbeat_at=clock_timestamp(),updated_at=clock_timestamp()"
                " WHERE dispatcher_id=%s", (identity,))
            if cur.rowcount != 1:
                raise AlertDispatcherUnhealthy(
                    f"dispatcher {identity!r} has no durable registration")
        conn.commit()
        return load(conn, dispatcher_id=identity)
    except BaseException:
        conn.rollback()
        raise


def record_success(conn, *, dispatcher_id: str) -> DispatcherHealth:
    identity = _identity(dispatcher_id)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_alert_dispatcher_health SET"
                " heartbeat_at=clock_timestamp(),last_attempt_at=clock_timestamp(),"
                " last_success_at=clock_timestamp(),consecutive_failures=0,"
                " state='HEALTHY',last_error=NULL,updated_at=clock_timestamp()"
                " WHERE dispatcher_id=%s", (identity,))
            if cur.rowcount != 1:
                raise AlertDispatcherUnhealthy(
                    f"dispatcher {identity!r} has no durable registration")
        conn.commit()
        return load(conn, dispatcher_id=identity)
    except BaseException:
        conn.rollback()
        raise


def record_failure(
        conn, *, dispatcher_id: str, error: str,
        terminal: bool = False, maximum_failures: int = 3
        ) -> DispatcherHealth:
    identity = _identity(dispatcher_id)
    if maximum_failures < 1:
        raise ValueError("maximum alert transport failures must be positive")
    detail = str(error or "alert transport failed without detail")[:4000]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_alert_dispatcher_health SET"
                " heartbeat_at=clock_timestamp(),last_attempt_at=clock_timestamp(),"
                " consecutive_failures=consecutive_failures+1,"
                " state=CASE WHEN %s OR consecutive_failures+1 >= %s"
                "            THEN 'FAILED' ELSE 'DEGRADED' END,"
                " last_error=%s,updated_at=clock_timestamp()"
                " WHERE dispatcher_id=%s",
                (bool(terminal), maximum_failures, detail, identity))
            if cur.rowcount != 1:
                raise AlertDispatcherUnhealthy(
                    f"dispatcher {identity!r} has no durable registration")
        conn.commit()
        return load(conn, dispatcher_id=identity)
    except BaseException:
        conn.rollback()
        raise


def load(conn, *, dispatcher_id: str) -> DispatcherHealth:
    identity = _identity(dispatcher_id)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM sentinel_alert_dispatcher_health"
            " WHERE dispatcher_id=%s", (identity,))
        row = cur.fetchone()
    if row is None:
        raise AlertDispatcherUnhealthy(
            f"dispatcher {identity!r} has no durable registration")
    return _record(row)


def load_all(conn) -> list[DispatcherHealth]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM sentinel_alert_dispatcher_health"
            " ORDER BY dispatcher_id")
        rows = cur.fetchall()
    return [_record(row) for row in rows]


def require_healthy(
        conn, *, dispatcher_id: str, maximum_age_seconds: float,
        startup_grace_seconds: float) -> DispatcherHealth:
    """Database-clock liveness used by Docker, independent of the webhook."""
    if maximum_age_seconds <= 0 or startup_grace_seconds <= 0:
        raise ValueError("dispatcher health intervals must be positive")
    identity = _identity(dispatcher_id)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS},"
            " EXTRACT(EPOCH FROM (clock_timestamp()-heartbeat_at)),"
            " EXTRACT(EPOCH FROM (clock_timestamp()-started_at)),"
            " (SELECT COUNT(*) FROM sentinel_alert_outbox"
            "   WHERE state='DEAD_LETTER')"
            " FROM sentinel_alert_dispatcher_health WHERE dispatcher_id=%s",
            (identity,))
        row = cur.fetchone()
    conn.rollback()
    if row is None:
        raise AlertDispatcherUnhealthy(
            f"dispatcher {identity!r} has no durable health row")
    health = _record(row[:9])
    heartbeat_age = float(row[9])
    startup_age = float(row[10])
    dead_letters = int(row[11])
    if heartbeat_age < 0 or heartbeat_age > maximum_age_seconds:
        raise AlertDispatcherUnhealthy(
            f"dispatcher heartbeat is stale ({heartbeat_age:.3f}s)")
    if dead_letters:
        raise AlertDispatcherUnhealthy(
            f"alert outbox contains {dead_letters} dead-letter row(s)")
    if health.state == FAILED:
        raise AlertDispatcherUnhealthy(
            f"dispatcher transport is failed: {health.last_error}")
    if (health.last_success_at is None
            and startup_age > startup_grace_seconds):
        raise AlertDispatcherUnhealthy(
            "dispatcher has not proved webhook delivery within startup grace")
    return health


__all__ = [
    "AlertDispatcherUnhealthy", "DEGRADED", "DispatcherHealth", "FAILED",
    "HEALTHY", "STARTING", "heartbeat", "load", "load_all", "record_failure",
    "record_success", "register", "require_healthy",
]

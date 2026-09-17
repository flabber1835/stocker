"""Fenced, deadline-bound preparation work. No source or publication authority."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import Field

from sentinel.feed.rolling_contract import Contract, Digest, PriceWindow, canonical_json, digest
from sentinel.feed import rolling_store

State = Literal["ACQUIRING", "WAIT_SOURCE", "STAGING", "VALIDATING", "READY",
                "RETRY_WAIT", "INTERRUPTED", "REFUSED", "ABORTED", "PUBLISHED"]
ACTIVE = {"ACQUIRING", "STAGING", "VALIDATING", "READY"}
TERMINAL = {"REFUSED", "ABORTED", "PUBLISHED"}
WAITING = {"WAIT_SOURCE", "RETRY_WAIT", "INTERRUPTED"}
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,95}\Z")
_COMPONENT = re.compile(
    r"(?:SEP|SFP|ACTIONS|TICKERS)(?:\.[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"\.[0-9]{4}-[0-9]{2}-[0-9]{2})?\Z")


class JobRefused(RuntimeError):
    pass


class PreparationRequest(Contract):
    window: PriceWindow
    expected_publication_version: int | None = Field(default=None, ge=1, strict=True)
    cursor: date | None = None
    strategy_sha256: Digest
    dependencies_sha256: Digest

    @property
    def request_sha256(self):
        return digest(self.model_dump(mode="json"))


@dataclass(frozen=True)
class Lease:
    job_id: str
    owner: str
    fence: int


def _code(value):
    if not isinstance(value, str) or not _CODE.fullmatch(value):
        raise JobRefused("reason must be a bounded machine code")
    return value


def _seconds(value, *, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise JobRefused(f"duration must be an integer in 1..{maximum} seconds")
    return value


def enqueue(conn, request: PreparationRequest, *, budget_seconds: int) -> str:
    """Coalesce the exact active request without renewing its original budget."""
    budget = _seconds(budget_seconds, maximum=86400)
    request = PreparationRequest.model_validate(request.model_dump(mode="json"))
    if request.cursor is not None and request.cursor not in request.window.sessions[1:]:
        raise JobRefused("request cursor/predecessor is outside the available window")
    identity = request.request_sha256
    # A transaction lock closes the insert/select race and allows terminal jobs
    # to be retained without making their request identity permanently unique.
    key = int(identity[:15], 16)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        cur.execute("SELECT job_id FROM sentinel_snapshot_jobs WHERE request_sha256=%s "
                    "AND state NOT IN ('REFUSED','ABORTED','PUBLISHED')", (identity,))
        row = cur.fetchone()
        if row:
            return str(row[0])
        job_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO sentinel_snapshot_jobs "
            "(job_id,request_sha256,request,deadline,state,resume_state,reason) "
            "VALUES (%s,%s,%s::jsonb,clock_timestamp()+%s*interval '1 second',"
            "'ACQUIRING','ACQUIRING','QUEUED')",
            (job_id, identity, canonical_json(request.model_dump(mode="json")), budget))
    return job_id


def status(conn, job_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT to_jsonb(j),clock_timestamp() FROM sentinel_snapshot_jobs j "
                    "WHERE job_id=%s", (job_id,))
        row = cur.fetchone()
    if row is None:
        raise JobRefused("preparation job does not exist")
    value, now = row
    request = PreparationRequest.model_validate(value["request"])
    if request.request_sha256 != value["request_sha256"]:
        raise JobRefused("preparation request changed after enqueue")
    value["remaining_seconds"] = max(0.0, (
        datetime.fromisoformat(value["deadline"]) - now).total_seconds())
    value["elapsed_seconds"] = max(0.0, (
        now - datetime.fromisoformat(value["created_at"])).total_seconds())
    value["phase_elapsed_seconds"] = max(0.0, (
        now - datetime.fromisoformat(value["phase_started_at"])).total_seconds())
    value["last_progress_age_seconds"] = max(0.0, (
        now - datetime.fromisoformat(value["last_progress_at"])).total_seconds())
    return value


def claim(conn, job_id: str, *, lease_seconds: int = 60) -> Lease:
    duration = _seconds(lease_seconds, maximum=600)
    owner = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_snapshot_jobs SET owner=%s,fence=fence+1,"
            "lease_until=LEAST(deadline,clock_timestamp()+%s*interval '1 second'),"
            "state=CASE WHEN state IN ('WAIT_SOURCE','RETRY_WAIT','INTERRUPTED') "
            "THEN resume_state ELSE state END,reason='RUNNING',updated_at=clock_timestamp() "
            "WHERE job_id=%s AND state NOT IN ('REFUSED','ABORTED','PUBLISHED') "
            "AND deadline>clock_timestamp() "
            "AND (owner IS NULL OR lease_until<=clock_timestamp()) "
            "AND NOT EXISTS (SELECT 1 FROM sentinel_snapshot_comparisons p "
            "WHERE p.job_id=sentinel_snapshot_jobs.job_id) "
            "AND (next_retry IS NULL OR next_retry<=clock_timestamp()) RETURNING fence",
            (owner, duration, job_id))
        row = cur.fetchone()
    if row is None:
        raise JobRefused("job is owned, waiting, expired or terminal")
    conn.execute("INSERT INTO sentinel_snapshot_workers(owner,job_id) VALUES(%s,%s)", (owner, job_id))
    return Lease(job_id, owner, int(row[0]))


def _owned(conn, lease: Lease):
    with conn.cursor() as cur:
        cur.execute("SELECT state,resume_state,deadline,lease_until,owner,fence,"
                    "candidate_id,request,rows_done,bytes_done "
                    "FROM sentinel_snapshot_jobs WHERE job_id=%s FOR UPDATE", (lease.job_id,))
        row = cur.fetchone()
        cur.execute("SELECT clock_timestamp()")
        now = cur.fetchone()[0]
        if row is not None:
            row = (*row, now)
    if (row is None or str(row[4]) != lease.owner or row[5] != lease.fence
            or row[0] not in ACTIVE or row[3] is None or row[3] <= row[10]
            or row[2] <= row[10]):
        raise JobRefused("worker lease, fence or deadline no longer permits work")
    return row


def heartbeat(conn, lease: Lease, *, lease_seconds: int = 60) -> None:
    duration = _seconds(lease_seconds, maximum=600)
    row = _owned(conn, lease)
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_snapshot_jobs SET lease_until=%s,updated_at=%s "
                    "WHERE job_id=%s", (min(row[2], row[10] + timedelta(seconds=duration)),
                                          row[10], lease.job_id))


def progress(conn, lease: Lease, *, rows: int, bytes_: int) -> None:
    if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in (rows, bytes_)):
        raise JobRefused("progress counters must be nonnegative integers")
    current = _owned(conn, lease)
    if rows < current[8] or bytes_ < current[9]:
        raise JobRefused("progress counters cannot regress inside a stage")
    meaningful = rows > current[8] or bytes_ > current[9]
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_snapshot_jobs SET rows_done=%s,bytes_done=%s,"
                    "updated_at=%s,last_progress_at=CASE WHEN %s THEN %s "
                    "ELSE last_progress_at END WHERE job_id=%s",
                    (rows, bytes_, current[10], meaningful, current[10], lease.job_id))


def advance(conn, lease: Lease, state: State, *, candidate_id: str | None = None) -> None:
    current = _owned(conn, lease)
    if (current[0], state) not in {
            ("ACQUIRING", "STAGING"), ("STAGING", "VALIDATING"), ("VALIDATING", "READY")}:
        raise JobRefused("unsupported preparation state transition")
    candidate = candidate_id or (str(current[6]) if current[6] else None)
    if current[6] and candidate != str(current[6]):
        raise JobRefused("job cannot change its candidate generation")
    if candidate is None:
        raise JobRefused("staging requires an explicit private candidate")
    request = PreparationRequest.model_validate(current[7])
    with conn.cursor() as cur:
        cur.execute("SELECT session_axis,expected_publication_version,dependencies_sha256 "
                    "FROM sentinel_price_candidates WHERE candidate_id=%s", (candidate,))
        parent = cur.fetchone()
    if (parent is None or parent[0] != request.window.model_dump(mode="json")["sessions"]
            or parent[1] != request.expected_publication_version
            or parent[2] != request.dependencies_sha256):
        raise JobRefused("candidate does not match the frozen preparation request")
    if state == "READY":
        rolling_store.manifest(conn, candidate)
        # Loading reference payloads can be slow. Recheck server time after
        # validation rather than granting READY with a now-expired lease.
        current = _owned(conn, lease)
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_snapshot_jobs SET state=%s,resume_state=%s,candidate_id=%s,"
                    "rows_done=0,bytes_done=0,phase_started_at=%s,last_progress_at=%s,"
                    "updated_at=%s,reason='RUNNING' WHERE job_id=%s",
                    (state, state, candidate, current[10], current[10], current[10], lease.job_id))


def wait(conn, lease: Lease, *, state: State, reason: str, retry_seconds: int) -> None:
    current = _owned(conn, lease)
    if state not in WAITING or (state == "WAIT_SOURCE" and current[0] != "ACQUIRING"):
        raise JobRefused("unsupported wait state")
    delay = _seconds(retry_seconds, maximum=86400)
    retry = current[10] + timedelta(seconds=delay)
    if retry >= current[2]:
        raise JobRefused("retry would exhaust the persisted request deadline")
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_snapshot_jobs SET state=%s,resume_state=%s,reason=%s,"
                    "next_retry=%s,owner=NULL,lease_until=NULL,updated_at=%s WHERE job_id=%s",
                    (state, current[0], _code(reason), retry, current[10], lease.job_id))


def finish(conn, lease: Lease, *, state: State, reason: str) -> None:
    current = _owned(conn, lease)
    if state not in {"REFUSED", "ABORTED"}:
        raise JobRefused("only the publisher can mark a preparation PUBLISHED")
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_snapshot_jobs SET state=%s,reason=%s,owner=NULL,"
                    "lease_until=NULL,next_retry=NULL,updated_at=%s WHERE job_id=%s",
                    (state, _code(reason), current[10], lease.job_id))


def checkpoint(conn, lease: Lease, *, component: str, generation_sha256: str,
               artifact_sha256: str, rows: int, bytes_: int) -> None:
    current = _owned(conn, lease)
    if current[0] != "ACQUIRING" or not _COMPONENT.fullmatch(component):
        raise JobRefused("source checkpoint requires an acquiring job and a safe component name")
    if any(not re.fullmatch(r"[0-9a-f]{64}", value)
           for value in (generation_sha256, artifact_sha256)):
        raise JobRefused("source checkpoint requires exact SHA-256 identities")
    if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in (rows, bytes_)):
        raise JobRefused("checkpoint counters must be nonnegative integers")
    values = (generation_sha256, artifact_sha256, rows, bytes_)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_snapshot_job_components "
                    "(job_id,component,generation_sha256,artifact_sha256,rows_done,bytes_done) "
                    "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (lease.job_id, component, *values))
        cur.execute("SELECT generation_sha256,artifact_sha256,rows_done,bytes_done "
                    "FROM sentinel_snapshot_job_components WHERE job_id=%s AND component=%s",
                    (lease.job_id, component))
        if cur.fetchone() != values:
            raise JobRefused("completed component changed generation or content; refuse this attempt")


def components(conn, job_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT component,generation_sha256,artifact_sha256,rows_done,bytes_done "
                    "FROM sentinel_snapshot_job_components WHERE job_id=%s ORDER BY component", (job_id,))
        return [dict(zip(("component", "generation_sha256", "artifact_sha256", "rows", "bytes"), row))
                for row in cur.fetchall()]


def expire(conn, job_id: str) -> bool:
    """A dead worker cannot leave expired work looking pending indefinitely."""
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_snapshot_jobs SET state='REFUSED',reason='DEADLINE_EXHAUSTED',"
                    "owner=NULL,lease_until=NULL,next_retry=NULL,fence=fence+1,"
                    "updated_at=clock_timestamp() WHERE job_id=%s "
                    "AND deadline<=clock_timestamp() "
                    "AND NOT EXISTS (SELECT 1 FROM sentinel_snapshot_comparisons p "
                    "WHERE p.job_id=sentinel_snapshot_jobs.job_id) "
                    "AND state NOT IN ('REFUSED','ABORTED','PUBLISHED') RETURNING job_id", (job_id,))
        return cur.fetchone() is not None

"""Shared tracing utilities: execution step logging, trace file artifacts, row serialization."""
from __future__ import annotations
import asyncio
import json
import os
import traceback
import uuid
from datetime import datetime, timezone
from typing import Optional


def fmt_row(row) -> dict:
    """Serialize a SQLAlchemy Row or RowMapping: UUIDs → str, datetimes → isoformat, rest unchanged."""
    import uuid as _uuid
    out = {}
    # Row has ._mapping; RowMapping (from .mappings().first()) is itself the mapping
    mapping = row._mapping if hasattr(row, "_mapping") else row
    for k, v in dict(mapping).items():
        if isinstance(v, _uuid.UUID):
            out[k] = str(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


async def log_step(
    conn,
    trace_id: str,
    service: str,
    step_name: str,
    status: str,
    *,
    started_at: Optional[datetime] = None,
    input_summary: Optional[dict] = None,
    output_summary: Optional[dict] = None,
    warnings: Optional[list] = None,
    error_message: Optional[str] = None,
) -> None:
    """Insert an execution_steps row for the given trace."""
    from sqlalchemy import text
    now = datetime.now(timezone.utc)
    await conn.execute(
        text(
            "INSERT INTO execution_steps "
            "(step_id, trace_id, service, step_name, status, started_at, completed_at, "
            " input_summary, output_summary, warnings, error_message) "
            "VALUES (:sid, :tid, :service, :step, :status, :started, :now, "
            "        CAST(:inp AS jsonb), CAST(:out AS jsonb), CAST(:warn AS jsonb), :err)"
        ),
        {
            "sid": str(uuid.uuid4()),
            "tid": trace_id,
            "service": service,
            "step": step_name,
            "status": status,
            "started": started_at or now,
            "now": now,
            "inp": json.dumps(input_summary) if input_summary else None,
            "out": json.dumps(output_summary) if output_summary else None,
            "warn": json.dumps(warnings) if warnings else None,
            "err": error_message,
        },
    )


async def write_trace_file(
    engine,
    artifacts_path: str,
    trace_id: str,
    run_id: str,
    job_type: str,
    status: str,
    started_at: datetime,
    service_label: str,
    **extra,
) -> None:
    """Write a trace artifact JSON file using asyncio.to_thread for the file write.

    Fetches execution_steps from DB, writes JSON to artifacts_path/traces/.
    Silently skips if artifacts_path is empty.
    """
    if not artifacts_path:
        return
    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT service, step_name, status, started_at, completed_at, "
                    "       input_summary, output_summary, warnings, error_message "
                    "FROM execution_steps WHERE trace_id = :tid ORDER BY started_at ASC"
                ),
                {"tid": trace_id},
            )
            steps = [dict(r) for r in rows.mappings()]

        traces_dir = os.path.join(artifacts_path, "traces")
        fname = f"{started_at.strftime('%Y-%m-%d')}_{job_type}_{trace_id[:8]}.json"
        payload = {
            "trace_id": trace_id,
            "run_id": run_id,
            "job_type": job_type,
            "status": status,
            "started_at": started_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **extra,
            "steps": steps,
        }
        path = os.path.join(traces_dir, fname)

        def _write() -> None:
            os.makedirs(traces_dir, exist_ok=True)
            with open(path, "w") as f:
                json.dump(payload, f, indent=2, default=str)

        await asyncio.to_thread(_write)
        print(f"[{service_label}] trace → {path} ({len(steps)} steps, status={status})")
    except Exception as exc:
        print(f"[{service_label}] WARNING: failed to write trace file for {trace_id}: {exc}")
        traceback.print_exc()


async def mark_orphaned_runs_failed(
    conn,
    run_table: str,
    trace_job_type: Optional[str] = None,
) -> None:
    """Mark any 'running' rows as 'failed' in run_table on service startup (crash recovery).

    run_table must be a trusted internal constant — never accept from user input.
    If trace_job_type is given, also marks matching execution_traces rows as failed.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    try:
        await conn.execute(
            text(
                f"UPDATE {run_table} SET status='failed', completed_at=NOW(), "  # noqa: S608
                "error_message='Service restarted while run was active' "
                "WHERE status='running'"
            )
        )
    except ProgrammingError as exc:
        if "UndefinedTableError" in type(exc.orig).__name__ or "does not exist" in str(exc):
            print(f"[tracing] WARNING: table '{run_table}' does not exist yet — skipping orphan cleanup")
            return
        raise
    if trace_job_type:
        await conn.execute(
            text(
                "UPDATE execution_traces SET status='failed', completed_at=NOW(), "
                "notes='Service restarted while trace was active' "
                "WHERE status='running' AND job_type=:jt"
            ),
            {"jt": trace_job_type},
        )

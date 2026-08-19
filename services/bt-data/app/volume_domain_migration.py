"""One-time, resumable migration of a pre-#185 ``bt_prices`` corpus.

The schema guard deliberately leaves every pre-existing row without a
``volume_domain_version`` marker. That makes the legacy corpus ineligible for
certification, but the repair must itself remain reachable: the old corpus can be
tens of millions of rows and a network/process failure halfway through a full
re-fetch is ordinary operational reality.

Run inside the post-fix bt-data image:

    python -m app.volume_domain_migration

The command owns the same PostgreSQL corpus advisory lock as normal bt-data
writers. It may resume only its own interrupted PUBLISHING generation; no other
unknown PUBLISHING state is guessed or repaired. The command then:

1. force-replays the complete stored date range from SEP, ignoring old chunk
   completion markers;
2. refreshes the configured SFP benchmark tickers, which share ``bt_prices``;
3. proves **every** remaining row carries the post-fix semantic marker; and
4. only then publishes a new READY corpus UUID.

A row absent from current source is not deleted or grandfathered. It remains
unmarked and the migration refuses with a ticker/date sample. That is current-
source disagreement requiring inspection, not permission to bless the old
mixed-domain value.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import text

from app import main as bt

DOMAIN_VERSION = "sharadar-raw-volume-v1"
NOTE_PREFIX = "VOLUME_DOMAIN_MIGRATION:v1"


class VolumeDomainMigrationRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class MigrationResult:
    date_from: str | None
    date_to: str | None
    rows: int
    benchmarks_refreshed: int


async def _reserve_migration():
    mode = bt.data_mode()
    if mode == "frozen":
        raise VolumeDomainMigrationRefused(
            "BT_DATA_MODE=frozen cannot rewrite a frozen corpus")

    conn = await bt.engine.connect()
    locked = False
    try:
        locked = bool((await conn.execute(text(
            "SELECT pg_try_advisory_lock(:key)"),
            {"key": bt.CORPUS_LOCK_KEY})).scalar_one())
        await conn.commit()
        if not locked:
            await conn.close()
            return None

        row = (await conn.execute(text(
            "SELECT status, source_mode, COALESCE(note,'') AS note "
            "FROM bt_data_version WHERE id=1 FOR UPDATE"))).one()
        if row.status == "PUBLISHING":
            if not str(row.note).startswith(NOTE_PREFIX):
                raise VolumeDomainMigrationRefused(
                    f"corpus is PUBLISHING for a different operation: {row.note!r}")
            if row.source_mode is not None and row.source_mode != mode:
                raise VolumeDomainMigrationRefused(
                    f"interrupted migration belongs to source mode "
                    f"{row.source_mode!r}, configured mode is {mode!r}")
            await conn.rollback()
            return conn

        if row.status != "READY":
            raise VolumeDomainMigrationRefused(
                f"corpus is {row.status}; volume migration only starts from "
                "READY or resumes its own interrupted PUBLISHING state")
        if row.source_mode is not None and row.source_mode != mode:
            raise VolumeDomainMigrationRefused(
                f"corpus source mode is {row.source_mode!r}, configured writer "
                f"mode is {mode!r}; implicit mode mixing is refused")

        # Enter PUBLISHING before any rewrite. Readers acquire the matching
        # shared advisory corpus lock and require READY, so a partial migration
        # cannot become citable. If a legacy deployment never bound source_mode,
        # roll this state change back rather than inventing provenance merely to
        # make the economic-domain repair reachable.
        await conn.execute(text(
            "UPDATE bt_data_version SET status='PUBLISHING', updated_at=NOW(), "
            "note=:note WHERE id=1"),
            {"note": f"{NOTE_PREFIX}: starting"})
        populated = bool((await conn.execute(text(
            f"SELECT {bt._CORPUS_POPULATED_SQL}"))).scalar_one())
        if populated and row.source_mode is None:
            await conn.rollback()
            raise VolumeDomainMigrationRefused(
                "populated legacy corpus has no source_mode; refusing to invent "
                "Sharadar provenance during an economic-domain migration")
        if row.source_mode is None:
            await conn.execute(text(
                "UPDATE bt_data_version SET source_mode=:mode WHERE id=1"),
                {"mode": mode})
        await conn.commit()
        return conn
    except Exception:
        if conn.in_transaction():
            await conn.rollback()
        if locked:
            await bt._release_corpus_writer(conn)
        else:
            await conn.close()
        raise


async def _bounds_and_count() -> tuple[str | None, str | None, int]:
    async with bt.engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT MIN(date),MAX(date),COUNT(*) FROM bt_prices"))).one()
    if row[0] is None or row[1] is None:
        return None, None, int(row[2] or 0)
    return str(row[0]), str(row[1]), int(row[2] or 0)


async def _remaining_unmarked() -> tuple[int, list[tuple[str, str]]]:
    async with bt.engine.connect() as conn:
        count = int((await conn.execute(text(
            "SELECT COUNT(*) FROM bt_prices "
            "WHERE volume_domain_version IS DISTINCT FROM :version"),
            {"version": DOMAIN_VERSION})).scalar_one())
        rows = (await conn.execute(text(
            "SELECT ticker,date FROM bt_prices "
            "WHERE volume_domain_version IS DISTINCT FROM :version "
            "ORDER BY date,ticker LIMIT 20"),
            {"version": DOMAIN_VERSION})).fetchall()
    return count, [(str(row[0]), str(row[1])) for row in rows]


async def _mark_incomplete(conn, exc: Exception) -> None:
    if conn.in_transaction():
        await conn.rollback()
    await conn.execute(text(
        "UPDATE bt_data_version SET updated_at=NOW(), note=:note "
        "WHERE id=1 AND status='PUBLISHING'"),
        {"note": f"{NOTE_PREFIX}: INCOMPLETE: {type(exc).__name__}: {exc}"[:500]})
    await conn.commit()


async def migrate() -> MigrationResult:
    failures = await bt._ensure_schema()
    if failures:
        raise VolumeDomainMigrationRefused(
            "bt-data schema bootstrap failed before volume migration: "
            + " | ".join(failures[:5]))
    await bt._assert_required_schema()

    reservation = await _reserve_migration()
    if reservation is None:
        raise VolumeDomainMigrationRefused(
            "another process owns the bt-data corpus writer lock")
    try:
        date_from, date_to, rows = await _bounds_and_count()
        if rows == 0:
            await bt._publish_ready(
                reservation, f"{NOTE_PREFIX}: empty corpus; no rows to migrate")
            return MigrationResult(None, None, 0, 0)
        assert date_from is not None and date_to is not None

        # FORCE is load-bearing: old backfill_chunk markers describe completion
        # under the *old* economic contract and cannot skip a single year here.
        await bt._run_price_stage(date_from, date_to, None, force=True)
        benchmark_rows = await bt._load_benchmarks(date_from, date_to)

        remaining, sample = await _remaining_unmarked()
        if remaining:
            raise VolumeDomainMigrationRefused(
                f"{remaining:,} bt_prices row(s) remain outside "
                f"{DOMAIN_VERSION} after full SEP + configured SFP benchmark "
                f"refresh; sample={sample}. Do not delete/grandfather them. "
                "If they belong to historical custom benchmark tickers, include "
                "those symbols in BT_BENCHMARK_TICKERS and rerun this same "
                "migration command; otherwise investigate source key drift.")

        await bt._publish_ready(
            reservation,
            f"{NOTE_PREFIX}: complete {date_from}..{date_to}; rows={rows}")
        return MigrationResult(date_from, date_to, rows, benchmark_rows)
    except Exception as exc:
        await _mark_incomplete(reservation, exc)
        raise
    finally:
        await bt._release_corpus_writer(reservation)


def main() -> None:
    result = asyncio.run(migrate())
    print(
        f"volume-domain migration complete: range={result.date_from}.."
        f"{result.date_to}, rows={result.rows:,}, "
        f"benchmarks_refreshed={result.benchmarks_refreshed:,}",
        flush=True)


if __name__ == "__main__":
    main()

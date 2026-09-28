"""Real HTTP acquisition and SQL staging, without publication or strategy work."""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import time

import httpx

from sentinel import backup_runtime_authority
from sentinel.feed import acquisition_work, rolling_source, runtime_schema, staging, store
from tools.acquisition_resources.fixtures import PROFILES
from tools.acquisition_resources.measurement import Measurement, disk


def source_identity():
    root = Path(__file__).resolve().parents[2]
    result = hashlib.sha256()
    for path in sorted((root / "sentinel").rglob("*.py")):
        result.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return result.hexdigest()


def database_sizes(conn):
    conn.commit()
    conn.execute("SELECT pg_stat_force_next_flush()")
    conn.commit()
    conn.execute("SELECT pg_stat_clear_snapshot()")
    row = conn.execute("SELECT pg_database_size(current_database()), "
        "pg_total_relation_size('sentinel_sep_staging'), "
        "(SELECT coalesce(sum(size),0) FROM pg_ls_waldir()), "
        "temp_bytes,temp_files FROM pg_stat_database WHERE datname=current_database()").fetchone()
    conn.rollback()
    return dict(zip(("database_bytes", "staging_bytes", "wal_bytes", "temp_bytes", "temp_files"), map(int, row)))


def run(profile, cycles):
    cache = acquisition_work.cache_root()
    # A disposable measurement database has no production backup media. Source
    # data, session, decimal, generation and metadata checks are unmodified.
    backup_runtime_authority.POLICY_MARKER = cache / "no-production-backup-policy"
    results = []
    started = time.monotonic()
    with Measurement(cache) as measure, store.connect(os.environ["RESOURCE_DSN"]) as conn:
        with measure.phase("schema"):
            runtime_schema.migrate_feed_schema(conn)
        for cycle in range(cycles):
            name = "cold" if cycle == 0 else "cached"
            source = rolling_source.SharadarSource(profile.window())
            checkpoints = []
            def checkpoint(*args):
                checkpoints.append(args[0])
            run_id = "00000000-0000-4000-8000-000000000001"
            acquisition_started = time.monotonic()
            with acquisition_work.budget(seconds=500):
                with measure.phase(name + ":preflight"):
                    source.preflight()
                with measure.phase(name + ":references"):
                    source.references(checkpoint)
                    assert len(source.actions) == profile.actions
                    assert len(source.tickers) == profile.tickers
                    assert len(source.sfp) == 2 * len(profile.window().sessions)
                with measure.phase(name + ":download_parse_stage"):
                    count = staging.stage(conn, source.prices(checkpoint, lambda: None),
                                          run_id=run_id, chunk="prices")
                    assert count == profile.securities * len(profile.window().sessions)
            acquisition_seconds = time.monotonic() - acquisition_started
            assert acquisition_seconds <= 500, "acquisition exceeds the production callback budget"
            with measure.phase(name + ":database_sort_read"):
                seen = 0
                previous = None
                digest = hashlib.sha256()
                for row in staging.staged(conn, run_id=run_id, chunk="prices"):
                    key = (row["date"], row["ticker"])
                    assert previous is None or previous < key
                    previous = key
                    digest.update(("|".join(str(row[k]) for k in
                        ("date", "ticker", "open", "close", "closeunadj", "volume")) + "\n").encode())
                    seen += 1
                assert seen == count
                conn.commit()
            with measure.phase(name + ":corroborate"), acquisition_work.budget(seconds=500):
                source.corroborate()
            for table in ("sentinel_corpus_publications", "sentinel_price_candidates"):
                assert conn.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
            result = dict(cycle=name, rows=count, staged_sha256=digest.hexdigest(),
                          acquisition_seconds=acquisition_seconds,
                          checkpoints=len(checkpoints), disk=disk(cache), database=database_sizes(conn),
                          provider=httpx.get("http://provider:8080/metrics", timeout=15).json())
            assert result["checkpoints"] == len(source.snapshots) + 1
            if results:
                assert result["staged_sha256"] == results[0]["staged_sha256"]
                assert result["provider"]["downloads"] == results[0]["provider"]["downloads"]
                assert result["disk"] == results[0]["disk"]
            results.append(result)
            del source
            gc.collect()
    return dict(event="result", profile=profile.model_dump(), sessions=len(profile.window().sessions),
                source_sha256=source_identity(), seconds=time.monotonic()-started,
                cycles=results, measurement=measure.result())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--cycles", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    print(json.dumps(run(PROFILES[args.profile], args.cycles), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

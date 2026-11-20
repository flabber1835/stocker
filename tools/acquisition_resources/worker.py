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
from sentinel.feed import acquisition_parts, acquisition_work, rolling_jobs as jobs, runtime_schema, store
from tools.acquisition_resources.fixture_transport import market_source
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
        "pg_total_relation_size('sentinel_acquisition_prices'), "
        "(SELECT coalesce(sum(size),0) FROM pg_ls_waldir()), "
        "temp_bytes,temp_files FROM pg_stat_database WHERE datname=current_database()").fetchone()
    conn.rollback()
    return dict(zip(("database_bytes", "staging_bytes", "wal_bytes", "temp_bytes", "temp_files"), map(int, row)))


def run(profile, cycles, *, address="http://provider:8080"):
    cache = acquisition_work.cache_root()
    # A disposable measurement database has no production backup media. Source
    # data, session, decimal, generation and metadata checks are unmodified.
    backup_runtime_authority.POLICY_MARKER = cache / "no-production-backup-policy"
    results = []
    started = time.monotonic()
    with Measurement(cache) as measure, store.connect(os.environ["RESOURCE_DSN"]) as conn:
        with measure.phase("schema"):
            runtime_schema.migrate_feed_schema(conn)
        window = profile.window()
        request = jobs.PreparationRequest(window=window, strategy_sha256='f'*64, dependencies_sha256='a'*64)
        job_id = jobs.enqueue(conn, request, budget_seconds=3600)
        lease = jobs.claim(conn, job_id, lease_seconds=600)
        conn.commit()
        for cycle in range(cycles):
            name = "cold" if cycle == 0 else "cached"
            source = market_source(address, window, conn, lease)
            checkpoints = []
            def checkpoint(*args):
                checkpoints.append(args[0])
            acquisition_started = time.monotonic()
            with acquisition_work.budget(seconds=500):
                with measure.phase(name + ":preflight"):
                    source.preflight()
                with measure.phase(name + ":references"):
                    source.references(checkpoint)
                    assert source.action_evidence["actions"] == profile.actions
                    assert len(source.assets) == profile.tickers + 2
                    assert len(source.selected) == profile.securities
                    assert len(source.sfp) == 2 * len(profile.window().sessions)
                with measure.phase(name + ":download_parse_stage"):
                    source.acquire_prices(checkpoint, lambda: jobs.heartbeat(conn, lease, lease_seconds=600))
                    count = sum(item["rows"] for item in source.evidence if item["component"].startswith("SEP."))
                    assert count == profile.securities * len(profile.window().sessions)
            acquisition_seconds = time.monotonic() - acquisition_started
            assert acquisition_seconds <= 500, "acquisition exceeds the production callback budget"
            with measure.phase(name + ":database_sort_read"):
                seen = 0
                previous = None
                digest = hashlib.sha256()
                for row in acquisition_parts.price_rows(conn, job_id):
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
                          provider=httpx.get(address + "/metrics", timeout=15, trust_env=False).json())
            assert result["checkpoints"] == len(source.evidence)
            if results:
                assert result["staged_sha256"] == results[0]["staged_sha256"]
                assert result["provider"]["/v2/stocks/bars"] == results[0]["provider"]["/v2/stocks/bars"]
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

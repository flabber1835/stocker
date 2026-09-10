"""Drive canonical production ingestion and retain independently checked evidence."""
from __future__ import annotations

import json
import platform
import subprocess
from contextlib import ExitStack, contextmanager
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from .model import Corpus, Scenario
from .oracle import StateMismatch, canonical, compare, compare_readiness, corpus_digest, digest
from .provider import Provider
from .runtime import simulated_runtime


def checked_server_dsn(dsn: str) -> dict:
    info = conninfo_to_dict(dsn)
    if info.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("replay requires an explicitly disposable loopback PostgreSQL server")
    if info.get("hostaddr") not in {None, "127.0.0.1", "::1"} or "service" in info:
        raise ValueError("alternate PostgreSQL routing is forbidden")
    return info


@contextmanager
def disposable_database(server_dsn: str):
    info = checked_server_dsn(server_dsn)
    name = "sharadar_replay_" + uuid4().hex
    with psycopg.connect(server_dsn, autocommit=True, connect_timeout=10) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield make_conninfo(**(info | {"dbname": name}))
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def observed_corpus(conn) -> Corpus:
    from sentinel.feed import publication

    def rows(query):
        with conn.cursor() as cur:
            cur.execute(query)
            return tuple(tuple(row) for row in cur.fetchall())

    return Corpus(
        bars=rows("SELECT b.security_id,b.session,b.ticker,b.close_signal,"
                  "b.close_unadjusted,b.open_unadjusted,b.volume,"
                  f"{publication.effective_split_ratio('b')},b.dividend_per_share "
                  f"FROM sentinel_bars b WHERE {publication.visible_predicate('b')} "
                  "ORDER BY b.security_id,b.session"),
        actions=rows("SELECT ticker,session,action,name,value,contraticker,contraname "
                     "FROM sentinel_active_actions ORDER BY ticker,session,action,source_row_id"),
        identities=rows("SELECT permaticker,ticker,category,sector,related_tickers,"
                        "first_price_date,last_price_date,is_delisted "
                        "FROM feed_universe_current ORDER BY permaticker,ticker"),
        spy=rows("SELECT session,closeadj FROM sentinel_spy_total_return r WHERE "
                 f"{publication.visible_predicate('r', sep_retirements=False)} ORDER BY session"),
        defensive=rows("SELECT session,security_id,ticker,open_signal,close_signal,"
                       "close_adjusted,close_unadjusted FROM sentinel_defensive_bars r WHERE "
                       f"{publication.visible_predicate('r', sep_retirements=False)} ORDER BY session"),
    )


def _write_new(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, sort_keys=True, indent=2, default=str, allow_nan=False)
        f.write("\n")


def run_scenario(scenario: Scenario, *, server_dsn: str, output: Path) -> dict:
    from sentinel.feed import ingest, publication, readiness, sharadar, store

    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(
        ["git", "-c", f"safe.directory={root}", "rev-parse", "HEAD"],
        cwd=root, text=True).strip()
    report = {"scenario": scenario.name, "commit": commit,
              "python": platform.python_version(), "postgres": None,
              "dependencies": {name: version(name) for name in
                  ("psycopg", "httpx", "exchange_calendars", "pandas", "numpy", "pydantic")},
              "producer_identity": "synthetic-test-only", "seed_authority": "injected-non-certifying",
              "daily_source": "production-default-tables-and-exporter", "steps": [], "verdict": "FAIL"}
    _write_new(output / "scenario.json", json.loads(scenario.model_dump_json()))
    provider = Provider(page_size=scenario.page_size, variation_seed=scenario.variation_seed)
    frozen_evidence: list[tuple[Path, str]] = []
    recovery_attempts = None
    recovered = False
    try:
        with disposable_database(server_dsn) as dsn, simulated_runtime(provider, commit=commit):
            with store.connect(dsn) as conn:
                store.migrate_schema(conn)
                report["postgres"] = conn.info.server_version
            for index, step in enumerate((scenario.seed, *scenario.steps)):
                provider.advance(step)
                if step.name == scenario.recovery_from:
                    recovery_attempts = 0
                if recovery_attempts is not None and not recovered:
                    recovery_attempts += 1
                print(f"[sharadar-replay] {scenario.name} {index + 1}/{len(scenario.steps) + 1} "
                      f"{step.name} at {step.at.isoformat()}", flush=True)
                with store.connect(dsn, statement_timeout_ms=30000) as conn:
                    previous_version = publication.require_current(conn).version if index else None
                    error = None
                    with ExitStack() as faults:
                        if step.publication_failure:
                            faults.enter_context(patch.object(publication, "publish",
                                side_effect=RuntimeError("scheduled publication interruption")))
                        try:
                            if index == 0:
                                # This seed is explicitly non-certifying. Strict HTTP still executes.
                                ingest.seed(conn, date_from=str(scenario.seed_start),
                                    date_to=str(step.through),
                                    fetch=lambda *a, **kw: sharadar.fetch_table(*a, **kw))
                            else:
                                ingest.daily(conn, today=str(step.through))
                        except Exception as exc:
                            conn.rollback()
                            error = {"type": type(exc).__name__, "detail": str(exc)}
                    with publication.pinned(conn) as current:
                        corpus = observed_corpus(conn)
                        state = readiness.check_readiness(conn, today=step.at.isoformat())
                    failures = [check.name for check in state.failures]
                    snapshot_path = output / f"{index:03d}_{step.name}.json"
                    evidence = {"step": step.name, "at": step.at.isoformat(),
                        "publication_version": current.version, "error": error,
                        "ready": state.ready, "readiness": [vars(c) for c in state.checks],
                        "corpus": canonical(corpus.model_dump()),
                        "corpus_digest": corpus_digest(corpus),
                        "expected_digest": corpus_digest(step.expected)}
                    _write_new(snapshot_path, evidence)
                    frozen_evidence.append((snapshot_path, digest(snapshot_path.read_text())))
                    record = {k: evidence[k] for k in ("step", "at", "publication_version", "error",
                                                      "ready", "corpus_digest", "expected_digest")}
                    report["steps"].append(record)
                    if (step.error is None) != (error is None):
                        raise StateMismatch(f"{step.name}: expected error {step.error}, actual {error}")
                    if step.error and step.error not in (error["type"] + ": " + error["detail"]):
                        raise StateMismatch(f"{step.name}: unexpected error {error}")
                    if step.error and not step.error_after_daily_publication and current.version != previous_version:
                        raise StateMismatch(f"{step.name}: interrupted candidate changed publication")
                    if step.error_after_daily_publication and current.version == previous_version:
                        raise StateMismatch(f"{step.name}: expected completed daily publication before maintenance error")
                    compare(step.expected, corpus)
                    provider.assert_revisions_applied()
                    try:
                        compare_readiness(expected=step.ready, actual=state.ready,
                                          required_blockers=step.required_blockers, failures=failures)
                    except StateMismatch as exc:
                        raise StateMismatch(str(exc) + '; details=' + json.dumps(
                            [vars(c) for c in state.failures], default=str)) from exc
                    if recovery_attempts is not None and not recovered:
                        recovered = error is None and state.ready
                        if recovery_attempts >= scenario.recovery_attempt_budget and not recovered:
                            raise StateMismatch("recovery attempt deadline exceeded")
                for path, expected_digest in frozen_evidence:
                    if digest(path.read_text()) != expected_digest:
                        raise StateMismatch(f"earlier input snapshot changed: {path.name}")
            if scenario.recovery_from and not recovered:
                raise StateMismatch("scenario ended before required convergence")
            report.update(verdict="PASS", recovery_attempts=recovery_attempts)
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "detail": str(exc)}
        raise
    finally:
        _write_new(output / "transcript.json", provider.transcript)
        _write_new(output / "report.json", report)
    return report

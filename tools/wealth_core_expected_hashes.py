"""Produce the seven canonical Wealth Core hashes from the BT corpus once.

This is a certification tool, not a runtime service.  It imports the canonical
backtester corpus loader and the shared Wealth Core engine, holds one locked
read-only snapshot, prints one self-describing JSON artifact, and exits.  It
has no persistence and no broker dependency.

The database authority is explicit through ``BT_DATABASE_URL``.  The URL is
never included in the result or in an error message.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from tools.corpus_parity import BT_CORPUS_LOCK_KEY, _add_backtester_to_path


SCHEMA = "wealth_core_expected_hashes.v1"
WARMUP_CALENDAR_DAYS = 400
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ExpectedHashesRefused(RuntimeError):
    """The command could not produce a citable certification artifact."""


@dataclass(frozen=True)
class DataGeneration:
    version: str
    status: str
    source_mode: str
    updated_at: Any
    note: str | None

    def to_dict(self) -> dict[str, Any]:
        updated = self.updated_at
        if hasattr(updated, "isoformat"):
            updated = updated.isoformat()
        return {
            "version": self.version,
            "status": self.status,
            "source_mode": self.source_mode,
            "updated_at": str(updated),
            "note": self.note,
        }


def _iso_day(value: str, *, name: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ExpectedHashesRefused(
            f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc
    if str(parsed) != value:
        raise ExpectedHashesRefused(
            f"{name} must use canonical YYYY-MM-DD form, got {value!r}")
    return parsed


def validate_window(start: str, end: str) -> tuple[date, date]:
    start_day = _iso_day(start, name="start")
    end_day = _iso_day(end, name="end")
    if end_day < start_day:
        raise ExpectedHashesRefused(
            f"end {end!r} precedes start {start!r}; reversed windows are refused")
    return start_day, end_day


def _first(result):
    return result.first()


def load_actions_ingestion_evidence(conn, *, start: date,
                                    end: date) -> dict[str, Any]:
    """Name the successful Sharadar fetch that claims the queried coverage.

    A non-empty ``bt_actions`` table proves only that *something* was fetched.
    Certification needs the durable fetch-run marker whose requested bounds
    cover every action date this producer asks the loader to consume.  The
    exact rows are hashed separately below; together the marker and digest say
    what completion was claimed and what data was actually read without
    pretending the producer can independently audit the vendor response.
    """
    import sqlalchemy as sa

    try:
        row = _first(conn.execute(sa.text(
            "SELECT run_id::text, job_type, rows_written, date_min, date_max, "
            "started_at, completed_at, error_message "
            "FROM bt_data_runs "
            "WHERE table_name = 'bt_actions' AND status = 'success' "
            "AND source_mode = 'sharadar' AND rows_written > 0 "
            "AND date_min <= :start AND date_max >= :end "
            "AND completed_at IS NOT NULL "
            "ORDER BY completed_at DESC, run_id DESC LIMIT 1"),
            {"start": start, "end": end}))
    except Exception as exc:  # noqa: BLE001 - missing evidence is a refusal
        raise ExpectedHashesRefused(
            "bt_data_runs cannot prove a completed Sharadar ACTIONS ingest "
            "covering the causal window") from exc
    if row is None:
        raise ExpectedHashesRefused(
            "no successful Sharadar bt_actions ingestion run covers the full "
            f"queried action window {start}..{end}; a non-empty action table "
            "alone is not completeness evidence")
    (run_id, job_type, rows_written, date_min, date_max, started_at,
     completed_at, error_message) = row
    return {
        "coverage_complete": True,
        "run_id": str(run_id),
        "job_type": str(job_type),
        "source_mode": "sharadar",
        "rows_written": int(rows_written),
        "date_min": str(date_min),
        "date_max": str(date_max),
        "started_at": (started_at.isoformat() if hasattr(started_at, "isoformat")
                       else str(started_at)),
        "completed_at": (completed_at.isoformat()
                         if hasattr(completed_at, "isoformat")
                         else str(completed_at)),
        # Successful rows occasionally carry the unusable-row count here.  It
        # is evidence, not an error, and omitting it would hide that filtering.
        "completion_note": (None if error_message is None
                            else str(error_message)),
        "required_start": str(start),
        "required_end": str(end),
    }


def actions_sha256(rows: list[Mapping[str, Any]]) -> str:
    """Digest every canonical-loader ACTIONS row, independent of row order."""
    rendered: list[str] = []
    for row in rows:
        payload = {
            "action": (None if row.get("action") is None
                       else str(row.get("action"))),
            "contraticker": (None if row.get("contraticker") is None
                             else str(row.get("contraticker"))),
            "date": (None if row.get("date") is None
                     else str(row.get("date"))),
            "ticker": (None if row.get("ticker") is None
                       else str(row.get("ticker"))),
            # Decimal text is exact.  Coercing through float here would make
            # the evidence digest lose precision before Wealth Core saw it.
            "value": (None if row.get("value") is None
                      else str(row.get("value"))),
        }
        rendered.append(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False))
    h = hashlib.sha256()
    for item in sorted(rendered):
        h.update(item.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def prepare_snapshot(conn) -> tuple[DataGeneration, dict[str, Any]]:
    """Make this transaction immutable, then name and lock its generation.

    ``SET TRANSACTION`` is deliberately the first SQL statement issued by this
    function.  The caller must enter a fresh transaction before calling it.
    """
    import sqlalchemy as sa

    conn.execute(sa.text(
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    read_only = conn.execute(sa.text("SHOW transaction_read_only")).scalar_one()
    isolation = conn.execute(sa.text("SHOW transaction_isolation")).scalar_one()
    if str(read_only).lower() not in ("on", "true", "1"):
        raise ExpectedHashesRefused(
            "PostgreSQL did not enter a read-only transaction; no corpus query "
            "was run")
    if str(isolation).lower().replace("_", " ") != "repeatable read":
        raise ExpectedHashesRefused(
            f"transaction isolation is {isolation!r}, not REPEATABLE READ")

    locked = conn.execute(sa.text(
        "SELECT pg_try_advisory_xact_lock_shared(:key)"),
        {"key": BT_CORPUS_LOCK_KEY}).scalar_one()
    if not locked:
        raise ExpectedHashesRefused(
            "the canonical BT corpus is being published; refusing to queue or "
            "read across generations")

    try:
        row = _first(conn.execute(sa.text(
            "SELECT version::text, status, source_mode, updated_at, note "
            "FROM bt_data_version WHERE id = 1")))
    except Exception as exc:  # noqa: BLE001 - old schema is not citable
        raise ExpectedHashesRefused(
            "bt_data_version cannot supply the certification generation") from exc
    if row is None:
        raise ExpectedHashesRefused(
            "bt_data_version has no singleton row; the corpus has no identity")
    version, status, source_mode, updated_at, note = row
    if str(status).upper() != "READY":
        raise ExpectedHashesRefused(
            f"the BT corpus is {status!r}, not READY")
    if str(source_mode).lower() != "sharadar":
        raise ExpectedHashesRefused(
            f"the BT corpus source is {source_mode!r}, not 'sharadar'; mock or "
            "frozen inputs cannot produce production expected hashes")
    if not version or updated_at is None:
        raise ExpectedHashesRefused(
            "the READY BT generation lacks a version or update timestamp")
    generation = DataGeneration(
        version=str(version), status="READY", source_mode="sharadar",
        updated_at=updated_at, note=(None if note is None else str(note)))
    return generation, {
        "transaction_read_only": True,
        "transaction_isolation": "repeatable read",
        "corpus_lock_key": f"0x{BT_CORPUS_LOCK_KEY:016x}",
    }


def load_corpus(conn, *, start: str, end: str, bt) -> dict[str, Any]:
    """Load one measured window plus feature-only warm-up through ``bt``."""
    from stock_strategy_shared.wealth_core.signals import REQUIRED_CLOSES

    start_day, _ = validate_window(start, end)
    warmup_needed = REQUIRED_CLOSES - 1
    warmup_from = str(start_day - timedelta(days=WARMUP_CALENDAR_DAYS))

    coverage = bt.assert_raw_price_domain(conn, warmup_from, end)
    all_sessions = list(bt.load_sessions(conn, warmup_from, end))
    if all_sessions != sorted(set(all_sessions)):
        raise ExpectedHashesRefused(
            "the canonical loader returned duplicate or unordered sessions")
    before = [session for session in all_sessions if session < start]
    measured = [session for session in all_sessions if session >= start]
    warmup = before[-warmup_needed:]
    if len(warmup) != warmup_needed:
        raise ExpectedHashesRefused(
            f"only {len(warmup)} pre-start sessions are available; exactly "
            f"{warmup_needed} are required to warm the rolling features")
    if len(before) <= warmup_needed:
        raise ExpectedHashesRefused(
            f"the {warmup_needed} retained warm-up sessions have no immediately "
            "preceding trading session inside the lookup window; the exclusive "
            "corporate-action cutoff cannot be identified")
    actions_exclusive_prior_session = before[-warmup_needed - 1]
    if not measured:
        raise ExpectedHashesRefused(
            f"the requested window {start}..{end} contains no sessions")
    if measured[0] != start or measured[-1] != end:
        raise ExpectedHashesRefused(
            f"requested bounds must be trading sessions and must not shift: "
            f"requested {start}..{end}, observed "
            f"{measured[0]}..{measured[-1]}")

    metadata_timeline = bt.load_meta_timeline(conn, sessions=measured)
    identity = bt.load_identity(conn, as_of=end)
    actions_ingestion = load_actions_ingestion_evidence(
        conn, start=date.fromisoformat(warmup_from), end=date.fromisoformat(end))
    source_action_rows = list(bt.load_actions(conn, warmup_from, end))
    actions_first_retained_session = warmup[0]
    action_rows = list(bt.actions_after_session(
        source_action_rows, actions_exclusive_prior_session))
    if not action_rows:
        raise ExpectedHashesRefused(
            f"bt_actions has no rows after the exclusive prior-session cutoff "
            f"{actions_exclusive_prior_session} through {end}; derived price "
            "splits are forbidden for certification")

    full_index = bt.sessions_index([*warmup, *measured])
    splits = bt.split_ratios_from_actions(action_rows, full_index)
    dividends = bt.dividends_from_actions(action_rows, full_index)
    reconciliation: dict[str, int] = {}
    bars = bt.load_bars(
        conn, warmup_from, end, authoritative_splits=splits,
        reconciliation=reconciliation, dividends=dividends, identity=identity)

    bt.require_usable_bars(
        bars, start=warmup_from, end=end,
        context="wealth_core_expected_hashes")
    bt.require_usable_decision_bars(
        bars, metadata_timeline, start=start, end=end,
        context="wealth_core_expected_hashes")
    normalized_bars = sum(len(rows) for rows in bars.values())
    measured_actions = bt.actions_effective_in_sessions(
        action_rows, full_index, measured)
    unresolved = getattr(identity, "unresolved", {})
    terminals = bt.terminal_events_from_actions(
        measured_actions, full_index,
        known_securities=set(metadata_timeline.security_ids),
        identity=identity, metadata_timeline=metadata_timeline,
        unresolved=unresolved)

    return {
        "sessions": measured,
        "warmup_sessions": warmup,
        "bars_by_session": bars,
        "meta": {},
        "metadata_timeline": metadata_timeline,
        "terminal_events": terminals,
        "source": {
            "split_source": "actions",
            "raw_close_coverage": round(float(coverage), 4),
            "normalized_bars": normalized_bars,
            "actions_rows": len(action_rows),
            "actions_rows_loaded": len(source_action_rows),
            "actions_rows_at_or_before_prior_cutoff":
                len(source_action_rows) - len(action_rows),
            "actions_first_retained_session":
                actions_first_retained_session,
            "actions_exclusive_prior_session":
                actions_exclusive_prior_session,
            "actions_sha256": actions_sha256(action_rows),
            "actions_ingestion": actions_ingestion,
            "terminal_events_applied": len(terminals),
            "split_reconciliation": dict(sorted(reconciliation.items())),
            "dividend_rows_unusable": bt.unusable_dividend_rows(action_rows),
            "identity_unresolved": dict(sorted(unresolved.items())),
            "excluded_unknown_tickers": 0,
        },
    }


def run_corpus(corpus: Mapping[str, Any]) -> tuple[Any, dict[str, str], str]:
    """Run the canonical shared engine, warming features but no portfolio."""
    from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
    from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
    from stock_strategy_shared.wealth_core.feed import Feed
    from stock_strategy_shared.wealth_core.run import run_with_hashes

    cfg = WealthCoreConfig()
    eligibility = EligibilityConfig()
    feed = Feed(corpus["meta"], eligibility,
                corpus.get("metadata_timeline"))
    feed.warmup(corpus["warmup_sessions"], corpus["bars_by_session"])
    result, hashes = run_with_hashes(
        sessions=corpus["sessions"],
        bars_by_session=corpus["bars_by_session"],
        meta=corpus["meta"],
        metadata_timeline=corpus.get("metadata_timeline"),
        starting_cash=1_000_000.0,
        cfg=cfg,
        eligibility_cfg=eligibility,
        terminal_events=corpus["terminal_events"],
        feed=feed,
        hash_mode="streaming",
    )
    return result, hashes.to_dict(), cfg.config_hash()


def causal_input_sha256(corpus: Mapping[str, Any]) -> str:
    """Hash the whole feature-causal stream without changing HASH_ORDER.

    The canonical ``normalized_input`` parity layer intentionally covers only
    measured sessions.  Feature values on the first measured day also depend
    on 126 pre-start sessions, so certification records this supplemental hash
    over warm-up + measured bars.  It remains provenance, not an eighth parity
    layer.
    """
    from stock_strategy_shared.wealth_core.hashes import normalized_input_hash

    sessions = [*corpus["warmup_sessions"], *corpus["sessions"]]
    if sessions != sorted(set(sessions)):
        raise ExpectedHashesRefused(
            "warm-up plus measured sessions are duplicate or unordered; the "
            "causal input cannot be identified")
    return normalized_input_hash(
        sessions, corpus["bars_by_session"],
        corpus.get("metadata_timeline"))


def validate_hashes(hashes: Mapping[str, str]) -> dict[str, str]:
    from stock_strategy_shared.wealth_core.hashes import HASH_ORDER

    actual = set(hashes)
    expected = set(HASH_ORDER)
    if actual != expected:
        raise ExpectedHashesRefused(
            "expected-hash producer did not emit exactly HASH_ORDER: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")
    ordered = {name: str(hashes[name]) for name in HASH_ORDER}
    invalid = [name for name, value in ordered.items()
               if _SHA256.fullmatch(value) is None]
    if invalid:
        raise ExpectedHashesRefused(
            f"expected hashes are missing or not 64-character lowercase hex: "
            f"{invalid}")
    return ordered


def produce(conn, *, start: str, end: str, bt=None) -> dict[str, Any]:
    """Produce one complete artifact from the caller's fresh transaction."""
    validate_window(start, end)
    generation, snapshot = prepare_snapshot(conn)
    if bt is None:
        _add_backtester_to_path()
        from app import wealth_core_replay as bt  # noqa: PLC0415

    corpus = load_corpus(conn, start=start, end=end, bt=bt)
    result, raw_hashes, config_hash = run_corpus(corpus)
    hashes = validate_hashes(raw_hashes)

    from stock_strategy_shared import identity_hashes
    from stock_strategy_shared.runtime_identity import (
        wealth_core_baseline_identity,
    )
    from stock_strategy_shared.wealth_core.run import STRATEGY_ID, STRATEGY_VERSION

    wealth_core_hash = identity_hashes.wealth_core_source_hash()
    loader_file = Path(bt.__file__).resolve()
    if not wealth_core_hash or not loader_file.is_file():
        raise ExpectedHashesRefused(
            "the imported Wealth Core or canonical loader source cannot be "
            "hashed; the output would not identify its producer")
    loader_hash = hashlib.sha256(loader_file.read_bytes()).hexdigest()
    producer_file = Path(__file__).resolve()
    if not producer_file.is_file():
        raise ExpectedHashesRefused(
            "the expected-hash producer source cannot be hashed")
    producer_hash = hashlib.sha256(producer_file.read_bytes()).hexdigest()

    from sentinel import identity as sentinel_identity
    runtime = sentinel_identity.rehearsal_identity()
    runtime_hash = str(runtime.get("identity_hash") or "")
    runtime_environment = runtime.get("environment")
    if (_SHA256.fullmatch(runtime_hash) is None
            or not isinstance(runtime_environment, dict)):
        raise ExpectedHashesRefused(
            "the certification runtime could not produce a complete identity")
    if (runtime_environment.get("certified") is not True
            or runtime_environment.get("pins_match") is not True
            or runtime_environment.get("sources_known") is not True
            or runtime_environment.get("pin_drift") != {}
            or runtime_environment.get("lock_present") is not True
            or _SHA256.fullmatch(str(
                runtime_environment.get("image_lock_sha256") or "")) is None):
        raise ExpectedHashesRefused(
            "the expected-hash producer is not running in the certified, "
            "source-known, lock-identified Sentinel test environment")

    behavior_identity = wealth_core_baseline_identity()
    if config_hash != behavior_identity["engine_config_hash"]:
        raise ExpectedHashesRefused(
            "baseline run config differs from the canonical behavior identity")

    sessions = corpus["sessions"]
    warmup = corpus["warmup_sessions"]
    return {
        "schema": SCHEMA,
        "status": "ready",
        "window": {
            "requested_start": start,
            "requested_end": end,
            "first_session": sessions[0],
            "last_session": sessions[-1],
            "sessions": len(sessions),
            "warmup_sessions": len(warmup),
            "warmup_first_session": warmup[0],
            "warmup_last_session": warmup[-1],
        },
        "hashes": hashes,
        "corpus": {
            **generation.to_dict(),
            **corpus["source"],
            "securities": len(corpus["meta"]),
            "normalized_input_hash": hashes["normalized_input"],
            "causal_input_sha256": causal_input_sha256(corpus),
        },
        "run": {
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "starting_cash": 1_000_000.0,
            "config_hash": config_hash,
            "behavior_identity": behavior_identity,
            "final_cash": round(float(result.state.cash), 2),
            "final_positions": len(result.state.episodes),
            "blocked_sessions": len(result.blocked_sessions),
        },
        "provenance": {
            **snapshot,
            "hash_order": list(hashes),
            "hash_mode": "streaming",
            "python": platform.python_version(),
            "wealth_core_source_hash": wealth_core_hash,
            "canonical_loader":
                "services/backtester/app/wealth_core_replay.py",
            "canonical_loader_sha256": loader_hash,
            "producer": "tools/wealth_core_expected_hashes.py",
            "producer_sha256": producer_hash,
            "runtime_identity_hash": runtime_hash,
            "runtime_environment": runtime_environment,
        },
    }


def _fsync_directory(path: Path) -> None:
    """Persist directory entries without letting close mask the first error."""
    if not hasattr(os, "O_DIRECTORY"):
        return
    dir_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    failure: Exception | None = None
    try:
        os.fsync(dir_fd)
    except Exception as exc:  # noqa: BLE001 - preserve the first I/O failure
        failure = exc
    try:
        os.close(dir_fd)
    except Exception as exc:  # noqa: BLE001 - close is part of durability
        if failure is None:
            failure = exc
        else:
            failure.add_note(
                f"directory descriptor close also failed: {exc!r}")
    if failure is not None:
        raise failure


def _unlink_best_effort(path: Path) -> None:
    """Rollback helper; a transient cleanup failure gets one immediate retry."""
    for _attempt in range(2):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            continue


def _rollback_artifact(parent: Path, target: Path, temp: Path, *,
                       linked: bool) -> None:
    """Remove every authoritative name while preserving the caller's error."""
    if linked:
        _unlink_best_effort(target)
    _unlink_best_effort(temp)
    try:
        _fsync_directory(parent)
    except Exception:  # noqa: BLE001 - never mask the publication failure
        # Rollback is best-effort because its failure must never mask the I/O
        # exception that caused publication to fail. The target removal gets
        # two attempts above; a surviving hidden temp is not authoritative.
        pass


def write_artifact_atomic(path: str | Path, artifact: Mapping[str, Any]) -> None:
    """Atomically install one complete JSON artifact without overwriting."""
    target = Path(path)
    parent = target.parent
    if not parent.is_dir():
        raise ExpectedHashesRefused(
            f"output directory does not exist: {parent}")
    if target.exists():
        raise ExpectedHashesRefused(
            f"output already exists; refusing to overwrite: {target}")

    payload = (json.dumps(artifact, indent=2, sort_keys=True, default=str,
                          allow_nan=False) + "\n").encode("utf-8")
    temp = parent / f".{target.name}.{secrets.token_hex(12)}.tmp"
    linked = False
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            # fdopen owns the descriptor once entered.
            raise
        try:
            # Same-directory hard-link publication is atomic and, unlike
            # replace(), has a no-clobber primitive on every supported host.
            os.link(temp, target)
            linked = True
        except FileExistsError as exc:
            raise ExpectedHashesRefused(
                f"output already exists; refusing to overwrite: {target}") from exc

        # Publication is not successful until both the authoritative link and
        # removal of its staging name are durable. If either cleanup or either
        # directory sync fails, the except block removes the final name too;
        # the CLI must never report failure beside a valid-looking ready JSON.
        _fsync_directory(parent)
        temp.unlink()
        _fsync_directory(parent)
    except ExpectedHashesRefused:
        _rollback_artifact(parent, target, temp, linked=linked)
        raise
    except Exception as exc:  # noqa: BLE001 - incomplete output is a refusal
        _rollback_artifact(parent, target, temp, linked=linked)
        raise ExpectedHashesRefused(
            f"could not atomically publish output {target}") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument(
        "--output", help="atomically create this JSON artifact (no overwrite)")
    args = parser.parse_args(argv)

    url = os.environ.get("BT_DATABASE_URL")
    if not url:
        print("REFUSED: BT_DATABASE_URL is unset", file=sys.stderr)
        return 2

    engine = None
    try:
        import sqlalchemy as sa

        parsed = sa.engine.make_url(url)
        if parsed.drivername != "postgresql+psycopg":
            raise ExpectedHashesRefused(
                "BT_DATABASE_URL must use postgresql+psycopg so the certified "
                "image's installed driver is explicit")
        engine = sa.create_engine(url)
        with engine.connect() as conn:
            with conn.begin():
                artifact = produce(conn, start=args.start, end=args.end)
        if args.output:
            write_artifact_atomic(args.output, artifact)
        else:
            print(json.dumps(artifact, indent=2, sort_keys=True, default=str,
                             allow_nan=False))
        return 0
    except ExpectedHashesRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - unreadable input is a refusal
        # Database exceptions commonly embed their connection URL.  The URL is
        # an authority and may contain a password, so the unexpected path names
        # the exception class only.  Typed refusals above carry safe remedies.
        print(f"REFUSED: expected-hash production failed "
              f"({type(exc).__name__}); no artifact was emitted",
              file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


__all__ = [
    "DataGeneration", "ExpectedHashesRefused", "SCHEMA",
    "WARMUP_CALENDAR_DAYS", "actions_sha256", "causal_input_sha256",
    "load_actions_ingestion_evidence", "load_corpus", "main",
    "prepare_snapshot", "produce", "run_corpus", "validate_hashes",
    "validate_window", "write_artifact_atomic",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

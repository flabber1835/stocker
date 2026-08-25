"""Bounded post-seed SEP generation proof.

Annual source stability proves each year at the time it was read.  A multi-hour
seed also needs a *sequencing* proof: changes published for an early year while
later years are loading must be reconciled before the candidate can publish.
This module performs that final bounded catch-up, then compares a complete
trailing normalized source window with the effective local candidate.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import pickle
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import BinaryIO, Callable, Iterable, Iterator, Mapping, Optional

from sentinel.feed import (
    calendar, coherence, domains, ingest_impl, sharadar, store, universe)

SCHEMA = "sentinel.seed-post-coherence/1"
START_SCHEMA = "sentinel.seed-post-coherence-start/1"
_MASK_256 = (1 << 256) - 1
_MAX_DATE_SAMPLE = 16


class SeedCoherenceRefused(RuntimeError):
    """A seed candidate cannot yet be granted publication authority."""


@dataclass(frozen=True)
class NormalizedProof:
    rows: int
    key_digest: str
    value_digest: str

    def to_dict(self) -> dict:
        return {
            "rows": int(self.rows),
            "key_sha256": self.key_digest,
            "value_sha256": self.value_digest,
        }


@dataclass(frozen=True)
class SourceObservation:
    rows: int
    digest: str

    def to_dict(self) -> dict:
        return {"rows": int(self.rows), "sha256": self.digest}


@dataclass(frozen=True)
class SeedCoherenceProof:
    payload: dict

    @property
    def final_cursor(self) -> dt.date:
        return dt.date.fromisoformat(str(self.payload["final_mutation_cursor"]))


class _CommutativeFingerprint:
    def __init__(self) -> None:
        self.rows = 0
        self._a = 0
        self._b = 0

    def add_payload(self, payload: bytes) -> None:
        self.rows += 1
        self._a = (self._a + int.from_bytes(
            hashlib.sha256(b"\x00" + payload).digest(), "big")) & _MASK_256
        self._b = (self._b + int.from_bytes(
            hashlib.sha256(b"\x01" + payload).digest(), "big")) & _MASK_256

    def digest(self) -> str:
        witness = (
            self.rows.to_bytes(16, "big")
            + self._a.to_bytes(32, "big")
            + self._b.to_bytes(32, "big"))
        return hashlib.sha256(witness).hexdigest()


class _KeyFingerprint(_CommutativeFingerprint):
    def add(self, security_id, session, ticker) -> None:
        self.add_payload(json.dumps(
            [str(security_id), str(session), str(ticker)],
            separators=(",", ":")).encode("utf-8"))


class _ValueFingerprint(_CommutativeFingerprint):
    def add(self, security_id, session, ticker, close_signal, raw_close,
            raw_open, volume) -> None:
        self.add_payload(json.dumps([
            str(security_id), str(session), str(ticker),
            _number(close_signal), _number(raw_close), _number(raw_open),
            _number(volume),
        ], separators=(",", ":")).encode("utf-8"))


def _number(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SeedCoherenceRefused(
            f"non-numeric SEP proof value {value!r}") from exc
    if not number.is_finite():
        raise SeedCoherenceRefused(f"non-finite SEP proof value {value!r}")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _canonical(value):
    if value is None:
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return str(value)
        if not number.is_finite():
            return str(value)
        if number == 0:
            return "0"
        return format(number.normalize(), "f")
    return str(value)


def _source_payload(row: Mapping) -> bytes:
    fields = (
        "date", "ticker", "open", "close", "closeunadj", "volume",
        "lastupdated")
    return json.dumps(
        {key: _canonical(row.get(key)) for key in fields},
        sort_keys=True, separators=(",", ":")).encode("utf-8")


def _strict_date(value, *, label: str) -> dt.date:
    text = str(value or "")
    try:
        parsed = dt.date.fromisoformat(text)
    except ValueError as exc:
        raise SeedCoherenceRefused(
            f"{label} is not a valid ISO date: {value!r}") from exc
    if parsed.isoformat() != text:
        raise SeedCoherenceRefused(
            f"{label} is not canonical YYYY-MM-DD: {value!r}")
    return parsed


def capture_update_boundary(now_utc: dt.datetime | None = None) -> str:
    """Capture a causal vendor-update boundary before the first seed request."""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return now.astimezone(dt.timezone.utc).date().isoformat()


def capture_update_ceiling(now_utc: dt.datetime | None = None) -> str:
    """Freeze the update ceiling once, at finalization start."""
    return capture_update_boundary(now_utc)


def record_start_boundary(conn, *, run_id: str, boundary: str) -> None:
    """Durably bind the pre-source boundary to a newly opened seed run."""
    value = _strict_date(boundary, label="seed start update boundary").isoformat()
    marker = {
        "schema": START_SCHEMA,
        "phase": "started",
        "seed_start_update_boundary": value,
    }
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE feed_ingest_runs"
            " SET publication_recovery=jsonb_set("
            "   publication_recovery,'{seed_coherence}',%s::jsonb,true),"
            " updated_at=NOW()"
            " WHERE run_id=%s AND kind='seed' AND status='running'",
            (json.dumps(marker, sort_keys=True), str(run_id)))
        changed = int(cur.rowcount)
    if changed != 1:
        conn.rollback()
        raise SeedCoherenceRefused(
            f"cannot bind seed-start update boundary to running seed {run_id}")
    conn.commit()


def _run_row(conn, run_id: str) -> tuple[str, str, str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status,date_from,date_to,publication_recovery"
            " FROM feed_ingest_runs WHERE run_id=%s AND kind='seed'",
            (str(run_id),))
        row = cur.fetchone()
    if row is None:
        raise SeedCoherenceRefused(f"seed run {run_id} has no lifecycle row")
    raw = row[3]
    recovery = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    if not isinstance(recovery, dict):
        raise SeedCoherenceRefused(
            f"seed run {run_id} has invalid publication recovery evidence")
    return str(row[0]), str(row[1]), str(row[2]), recovery


def _require_start_marker(conn, *, run_id: str, boundary: str,
                          market_start: str, market_end: str) -> None:
    status, date_from, date_to, recovery = _run_row(conn, run_id)
    if status not in {"running", "success"}:
        raise SeedCoherenceRefused(
            f"seed {run_id} is {status!r}; post-seed proof requires RUNNING/SUCCESS")
    if (date_from, date_to) != (str(market_start), str(market_end)):
        raise SeedCoherenceRefused(
            f"seed {run_id} lifecycle window {date_from}..{date_to} differs from "
            f"proof window {market_start}..{market_end}")
    marker = recovery.get("seed_coherence")
    if not isinstance(marker, dict):
        raise SeedCoherenceRefused(
            f"seed {run_id} lacks its durable pre-source update boundary")
    if (marker.get("schema") not in {START_SCHEMA, SCHEMA}
            or marker.get("seed_start_update_boundary") != str(boundary)):
        raise SeedCoherenceRefused(
            f"seed {run_id} durable start boundary differs from in-memory proof")


def reopen_successful_run(conn, progress):
    """Return an IngestRun facade, reopening SUCCESS only for final proof work."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE feed_ingest_runs SET status='running',completed_at=NULL,"
            " updated_at=NOW(),error_message=NULL"
            " WHERE run_id=%s AND kind='seed' AND status='success'",
            (str(progress.run_id),))
        reopened = int(cur.rowcount)
        if not reopened:
            cur.execute(
                "SELECT status FROM feed_ingest_runs WHERE run_id=%s AND kind='seed'",
                (str(progress.run_id),))
            row = cur.fetchone()
            if row is None or str(row[0]) != "running":
                conn.rollback()
                raise SeedCoherenceRefused(
                    f"seed {progress.run_id} cannot enter post-seed proof from "
                    f"status {None if row is None else row[0]!r}")
    conn.commit()
    run = object.__new__(store.IngestRun)
    run.conn = conn
    run.progress = progress
    return run


def _set_additional_chunks(conn, run, count: int) -> None:
    if count < 0:
        raise ValueError("additional chunk count cannot be negative")
    target = int(run.progress.chunks_done) + int(count)
    if target > int(run.progress.chunks_total):
        run.progress.chunks_total = target
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE feed_ingest_runs SET chunks_total=%s,updated_at=NOW()"
            " WHERE run_id=%s AND status='running'",
            (run.progress.chunks_total, str(run.progress.run_id)))
        changed = int(cur.rowcount)
    if changed != 1:
        conn.rollback()
        raise SeedCoherenceRefused(
            f"seed {run.progress.run_id} lost RUNNING state before proof")
    conn.commit()


def _validate_update_row(
        row: Mapping, *, update_start: dt.date, update_through: dt.date,
        market_sessions: set[str], resolver: Callable[[str, str], Optional[str]],
        collect_dates: set[str]) -> dict:
    item = dict(row)
    updated = _strict_date(
        item.get("lastupdated"), label="SEP mutation lastupdated")
    if not update_start <= updated <= update_through:
        raise SeedCoherenceRefused(
            f"SEP mutation {item.get('ticker')}/{item.get('date')} has "
            f"lastupdated {updated} outside fixed interval "
            f"{update_start}..{update_through}")
    session = _strict_date(item.get("date"), label="SEP mutation date").isoformat()
    ticker = str(item.get("ticker") or "").strip().upper()
    if not ticker:
        raise SeedCoherenceRefused(
            f"SEP mutation row on {session} has no ticker")
    if session in market_sessions:
        if resolver(ticker, session) is None:
            raise SeedCoherenceRefused(
                f"SEP mutation {ticker}/{session} has no candidate permanent "
                "identity; cursor advancement would skip unresolved economics")
        try:
            raw_close = float(item.get("closeunadj"))
        except (TypeError, ValueError) as exc:
            raise SeedCoherenceRefused(
                f"SEP mutation {ticker}/{session} has invalid raw close") from exc
        if not math.isfinite(raw_close) or raw_close <= 0:
            raise SeedCoherenceRefused(
                f"SEP mutation {ticker}/{session} has no positive raw close")
        collect_dates.add(session)
    return item


def _observe_mutations(
        fetch, *, update_start: str, update_through: str,
        market_start: str, market_end: str, resolver) -> tuple[SourceObservation,
                                                               SourceObservation,
                                                               set[str]]:
    lo = _strict_date(update_start, label="mutation interval start")
    hi = _strict_date(update_through, label="mutation interval end")
    if lo > hi:
        raise SeedCoherenceRefused(
            f"reversed seed mutation interval {lo}..{hi}")
    market_sessions = set(calendar.sessions_in_range(market_start, market_end))
    params = {"lastupdated.gte": lo.isoformat(),
              "lastupdated.lte": hi.isoformat()}
    observations: list[SourceObservation] = []
    second_dates: set[str] = set()
    for pass_number in (1, 2):
        fingerprint = _CommutativeFingerprint()
        dates: set[str] = set()
        for raw in fetch(sharadar.SEP, params):
            row = _validate_update_row(
                raw, update_start=lo, update_through=hi,
                market_sessions=market_sessions, resolver=resolver,
                collect_dates=dates)
            fingerprint.add_payload(_source_payload(row))
        observations.append(SourceObservation(
            rows=fingerprint.rows, digest=fingerprint.digest()))
        if pass_number == 2:
            second_dates = dates
    if observations[0] != observations[1]:
        raise SeedCoherenceRefused(
            "Sharadar SEP mutation set changed across two complete bounded "
            f"observations: {observations[0].to_dict()} -> "
            f"{observations[1].to_dict()}")
    return observations[0], observations[1], second_dates


def _validate_date_stream(
        rows: Iterable[Mapping], *, start: str, end: str,
        update_through: dt.date, resolver, counts: dict,
        fingerprint: _CommutativeFingerprint,
        spool: BinaryIO | None = None) -> None:
    expected = set(calendar.sessions_in_range(start, end))
    if not expected:
        raise SeedCoherenceRefused(
            f"source proof window {start}..{end} contains no XNYS sessions")
    for raw in rows:
        row = dict(raw)
        session = _strict_date(row.get("date"), label="SEP source date").isoformat()
        if session not in expected:
            raise SeedCoherenceRefused(
                f"SEP source row {row.get('ticker')}/{session} lies outside exact "
                f"XNYS request {start}..{end}")
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker:
            raise SeedCoherenceRefused(
                f"SEP source row on {session} has no ticker")
        raw_updated = row.get("lastupdated")
        if raw_updated not in (None, ""):
            updated = _strict_date(raw_updated, label="SEP source lastupdated")
            if updated > update_through:
                raise SeedCoherenceRefused(
                    f"SEP {ticker}/{session} lastupdated {updated} exceeds fixed "
                    f"seed update ceiling {update_through}; retry finalization "
                    "under a new ceiling")
        row["ticker"] = ticker
        resolved = resolver(ticker, session) is not None
        counts[session] = counts.get(
            session, coherence.SeedSessionCounts()).add(row, resolved=resolved)
        fingerprint.add_payload(_source_payload(row))
        if spool is not None:
            pickle.dump(row, spool, protocol=pickle.HIGHEST_PROTOCOL)


@dataclass(frozen=True)
class StableDateEvidence:
    start: str
    end: str
    first: SourceObservation
    second: SourceObservation

    def to_dict(self) -> dict:
        return {
            "start": self.start, "end": self.end,
            "first": self.first.to_dict(), "second": self.second.to_dict(),
        }


@contextmanager
def _stable_date_rows(
        fetch, *, start: str, end: str, update_through: dt.date,
        resolver) -> Iterator[tuple[Iterator[dict], StableDateEvidence]]:
    params = sharadar.date_params(start, end)
    first_counts: dict = {}
    first_fp = _CommutativeFingerprint()
    _validate_date_stream(
        fetch(sharadar.SEP, params), start=start, end=end,
        update_through=update_through, resolver=resolver,
        counts=first_counts, fingerprint=first_fp)
    coherence.assert_seed_history(first_counts, date_from=start, date_to=end)

    spool = tempfile.TemporaryFile(mode="w+b")
    try:
        second_counts: dict = {}
        second_fp = _CommutativeFingerprint()
        _validate_date_stream(
            fetch(sharadar.SEP, params), start=start, end=end,
            update_through=update_through, resolver=resolver,
            counts=second_counts, fingerprint=second_fp, spool=spool)
        coherence.assert_seed_history(second_counts, date_from=start, date_to=end)
        first = SourceObservation(first_fp.rows, first_fp.digest())
        second = SourceObservation(second_fp.rows, second_fp.digest())
        if first != second:
            raise SeedCoherenceRefused(
                f"Sharadar SEP {start}..{end} changed across two complete "
                f"observations: {first.to_dict()} -> {second.to_dict()}")
        spool.seek(0)

        def replay() -> Iterator[dict]:
            while True:
                try:
                    yield pickle.load(spool)
                except EOFError:
                    return

        yield replay(), StableDateEvidence(start, end, first, second)
    finally:
        spool.close()


def _replay_mutation_windows(
        conn, *, run, fetch, dates: Iterable[str], market_start: str,
        market_end: str, resolver, update_through: dt.date) -> list[dict]:
    from sentinel.feed import renormalize

    windows = renormalize.correction_windows(
        dates, market_start=market_start, market_end=market_end)
    results: list[dict] = []
    for index, (start, end) in enumerate(windows, 1):
        label = f"seed-mutation:{index}:{start}:{end}"
        with run.chunk(label):
            with _stable_date_rows(
                    fetch, start=start, end=end,
                    update_through=update_through, resolver=resolver) as pair:
                rows, source_evidence = pair
                report = domains.NormalisationReport()
                splits, divs, action_rows, ambiguous = ingest_impl._action_maps(
                    conn, start, end, include_run_id=run.progress.run_id)
                ordered = ingest_impl._ordered_sep(
                    conn, rows, run_id=run.progress.run_id, chunk=label)
                bars = domains.normalise_sep_rows(
                    ordered, resolve_identity=resolver,
                    authoritative_splits=splits, dividends=divs,
                    prior_observations=store.previous_observations(conn, start),
                    report=report)
                written = store.write_bars(
                    conn, bars, run_id=run.progress.run_id, require_lock=True)
                ingest_impl._persist_chunk_evidence(
                    conn, run, label, start, end, report, splits,
                    action_rows, action_rows, ambiguous)
                dropped = (report.dropped_no_raw_close
                           + report.dropped_no_identity)
                run.progress.rows_written += written
                run.progress.rows_dropped += dropped
                results.append({
                    "start": start, "end": end,
                    "source": source_evidence.to_dict(),
                    "bars_written": int(written),
                    "rows_dropped": int(dropped),
                })
    return results


def _normalised_source_partition(
        conn, *, rows: Iterable[dict], run_id: str, start: str, end: str,
        target_start: str, target_end: str, resolver,
        key_fp: _KeyFingerprint, value_fp: _ValueFingerprint) -> None:
    scratch = str(uuid.uuid4())
    chunk = f"seed-overlap-source:{start}:{end}:{scratch}"
    report = domains.NormalisationReport()
    splits, divs, _action_rows, _ambiguous = ingest_impl._action_maps(
        conn, start, end, include_run_id=run_id)
    ordered = ingest_impl._ordered_sep(
        conn, rows, run_id=scratch, chunk=chunk)
    normalised = domains.normalise_sep_rows(
        ordered, resolve_identity=resolver,
        authoritative_splits=splits, dividends=divs,
        prior_observations=store.previous_observations(conn, start),
        report=report)
    for item in normalised:
        bar = item.vendor
        if not target_start <= str(bar.session) <= target_end:
            continue
        key_fp.add(bar.security_id, bar.session, bar.ticker)
        value_fp.add(
            bar.security_id, bar.session, bar.ticker,
            item.close_signal, bar.raw_close, bar.raw_open, bar.volume)


def _candidate_local_proof(conn, *, run_id: str,
                           start: str, end: str) -> NormalizedProof:
    from sentinel.feed import publication

    key_fp = _KeyFingerprint()
    value_fp = _ValueFingerprint()
    sql = (
        "SELECT b.security_id,b.session,b.ticker,b.close_signal,"
        " b.close_unadjusted,b.open_unadjusted,b.volume"
        " FROM sentinel_bars b"
        " WHERE b.session BETWEEN %s AND %s"
        "   AND (b.last_written_run_id=%s OR "
        + publication.visible_predicate("b") + ")"
        " ORDER BY b.session,b.security_id")
    with store.streaming_cursor(conn, sql, (start, end, str(run_id))) as cur:
        for (security_id, session, ticker, close_signal, raw_close, raw_open,
             volume) in cur:
            key_fp.add(security_id, session, ticker)
            value_fp.add(
                security_id, session, ticker, close_signal, raw_close, raw_open,
                volume)
    if key_fp.rows != value_fp.rows:
        raise AssertionError("candidate local SEP key/value counts diverged")
    return NormalizedProof(
        rows=key_fp.rows, key_digest=key_fp.digest(),
        value_digest=value_fp.digest())


def _combined_observation(parts: list[dict], side: str) -> SourceObservation:
    payload = json.dumps([
        {
            "start": item["start"], "end": item["end"],
            "rows": item[side]["rows"], "sha256": item[side]["sha256"],
        }
        for item in parts
    ], sort_keys=True, separators=(",", ":")).encode("utf-8")
    return SourceObservation(
        rows=sum(int(item[side]["rows"]) for item in parts),
        digest=hashlib.sha256(payload).hexdigest())


def _trailing_overlap_proof(
        conn, *, run, fetch, market_start: str, market_end: str,
        resolver, update_through: dt.date,
        required_closes: int | None = None) -> tuple[dict, NormalizedProof,
                                                     NormalizedProof]:
    if required_closes is None:
        from stock_strategy_shared.wealth_core.signals import REQUIRED_CLOSES
        required_closes = int(REQUIRED_CLOSES)
    if required_closes < 1:
        raise SeedCoherenceRefused("required trailing close count must be positive")
    sessions = calendar.previous_sessions(market_end, required_closes)
    if len(sessions) != required_closes or not sessions or sessions[-1] != market_end:
        raise SeedCoherenceRefused(
            f"seed frontier {market_end} cannot expose the complete "
            f"{required_closes}-session Wealth Core close window")
    target_start = sessions[0]
    target_end = sessions[-1]

    label = f"seed-overlap:{target_start}:{target_end}"
    source_key = _KeyFingerprint()
    source_value = _ValueFingerprint()
    partition_evidence: list[dict] = []
    with run.chunk(label):
        for year in range(dt.date.fromisoformat(target_start).year,
                          dt.date.fromisoformat(target_end).year + 1):
            raw_start = max(
                dt.date.fromisoformat(market_start), dt.date(year, 1, 1))
            raw_end = min(
                dt.date.fromisoformat(market_end), dt.date(year, 12, 31))
            year_sessions = calendar.sessions_in_range(raw_start, raw_end)
            if not year_sessions:
                continue
            start, end = year_sessions[0], year_sessions[-1]
            if end < target_start or start > target_end:
                continue
            with _stable_date_rows(
                    fetch, start=start, end=end,
                    update_through=update_through, resolver=resolver) as pair:
                rows, evidence = pair
                _normalised_source_partition(
                    conn, rows=rows, run_id=str(run.progress.run_id),
                    start=start, end=end, target_start=target_start,
                    target_end=target_end, resolver=resolver,
                    key_fp=source_key, value_fp=source_value)
                partition_evidence.append(evidence.to_dict())

        source = NormalizedProof(
            rows=source_key.rows, key_digest=source_key.digest(),
            value_digest=source_value.digest())
        local = _candidate_local_proof(
            conn, run_id=str(run.progress.run_id),
            start=target_start, end=target_end)
        if source.rows != local.rows or source.key_digest != local.key_digest:
            raise SeedCoherenceRefused(
                "stable trailing SEP source and candidate local normalized key "
                f"sets disagree over {target_start}..{target_end}: source "
                f"{source.rows}/{source.key_digest[:16]}, local "
                f"{local.rows}/{local.key_digest[:16]}")
        if source.value_digest != local.value_digest:
            raise SeedCoherenceRefused(
                "stable trailing SEP source and candidate local strategy values "
                f"disagree over {target_start}..{target_end}: source "
                f"{source.value_digest[:16]}, local {local.value_digest[:16]}")

    if not partition_evidence:
        raise SeedCoherenceRefused("trailing source proof produced no partitions")
    first = _combined_observation(partition_evidence, "first")
    second = _combined_observation(partition_evidence, "second")
    return ({
        "interval": [target_start, target_end],
        "required_closes": int(required_closes),
        "normalization_partitions": partition_evidence,
        "source_first": first.to_dict(),
        "source_second": second.to_dict(),
    }, source, local)


def _persist_complete_proof(conn, *, run_id: str, payload: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE feed_ingest_runs"
            " SET publication_recovery=jsonb_set("
            "   publication_recovery,'{seed_coherence}',%s::jsonb,true),"
            " updated_at=NOW()"
            " WHERE run_id=%s AND kind='seed' AND status='running'"
            "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
            "                   WHERE p.run_id=feed_ingest_runs.run_id)",
            (json.dumps(payload, sort_keys=True, default=str), str(run_id)))
        changed = int(cur.rowcount)
    if changed != 1:
        conn.rollback()
        raise SeedCoherenceRefused(
            f"seed {run_id} lost unpublished RUNNING authority before proof save")
    conn.commit()


def prove(
        conn, *, run, fetch, market_start: str, market_end: str,
        seed_start_update_boundary: str,
        observed_max_lastupdated: dt.date | None,
        resolver=None, update_through: str | None = None,
        required_closes: int | None = None) -> SeedCoherenceProof:
    """Reconcile concurrent mutations and prove bounded source/local equality."""
    store._assert_corpus_locked(conn)
    run_id = str(run.progress.run_id)
    _require_start_marker(
        conn, run_id=run_id, boundary=seed_start_update_boundary,
        market_start=market_start, market_end=market_end)
    ceiling = _strict_date(
        update_through or capture_update_ceiling(),
        label="seed update ceiling")
    start_boundary = _strict_date(
        seed_start_update_boundary, label="seed start update boundary")
    if ceiling < start_boundary:
        raise SeedCoherenceRefused(
            f"seed update ceiling {ceiling} predates start boundary {start_boundary}")
    if observed_max_lastupdated is None:
        raise SeedCoherenceRefused(
            "complete seed exposed no SEP lastupdated value; mutation authority "
            "cannot be bootstrapped")
    observed_max = (observed_max_lastupdated if isinstance(
        observed_max_lastupdated, dt.date) else _strict_date(
            observed_max_lastupdated, label="seed maximum lastupdated"))
    if observed_max > ceiling:
        raise SeedCoherenceRefused(
            f"annual seed observed SEP lastupdated {observed_max} beyond fixed "
            f"finalization ceiling {ceiling}")

    resolver = resolver or universe.load_resolver(
        conn, include_run_id=run_id).resolve
    first_mutation, second_mutation, affected_dates = _observe_mutations(
        fetch, update_start=start_boundary.isoformat(),
        update_through=ceiling.isoformat(), market_start=market_start,
        market_end=market_end, resolver=resolver)

    from sentinel.feed import renormalize
    planned_windows = renormalize.correction_windows(
        affected_dates, market_start=market_start, market_end=market_end)
    _set_additional_chunks(conn, run, len(planned_windows) + 1)
    replayed = _replay_mutation_windows(
        conn, run=run, fetch=fetch, dates=affected_dates,
        market_start=market_start, market_end=market_end, resolver=resolver,
        update_through=ceiling)
    overlap, source, local = _trailing_overlap_proof(
        conn, run=run, fetch=fetch, market_start=market_start,
        market_end=market_end, resolver=resolver, update_through=ceiling,
        required_closes=required_closes)

    payload = {
        "schema": SCHEMA,
        "phase": "complete",
        "run_id": run_id,
        "market_interval": [str(market_start), str(market_end)],
        "seed_start_update_boundary": start_boundary.isoformat(),
        "seed_observed_max_lastupdated": observed_max.isoformat(),
        "mutation_interval": [start_boundary.isoformat(), ceiling.isoformat()],
        "mutation_source_first": first_mutation.to_dict(),
        "mutation_source_second": second_mutation.to_dict(),
        "affected_market_dates": {
            "count": len(affected_dates),
            "sample": sorted(affected_dates)[:_MAX_DATE_SAMPLE],
            "sha256": hashlib.sha256(json.dumps(
                sorted(affected_dates), separators=(",", ":")).encode(
                    "utf-8")).hexdigest(),
        },
        "mutation_replay_windows": replayed,
        "overlap": overlap,
        "normalized_source": source.to_dict(),
        "normalized_local": local.to_dict(),
        "final_mutation_cursor": ceiling.isoformat(),
    }
    _persist_complete_proof(conn, run_id=run_id, payload=payload)
    return SeedCoherenceProof(payload)


def load(conn, *, run_id: str) -> SeedCoherenceProof | None:
    _status, _date_from, _date_to, recovery = _run_row(conn, str(run_id))
    payload = recovery.get("seed_coherence")
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return None
    return SeedCoherenceProof(dict(payload))


def require_for_publication(
        conn, *, run_id: str, window_start: str | None,
        window_end: str | None) -> dict | None:
    """Publication membrane: every seed must carry one exact durable proof."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind,status,date_from,date_to,publication_recovery"
            " FROM feed_ingest_runs WHERE run_id=%s", (str(run_id),))
        row = cur.fetchone()
    if row is None:
        raise SeedCoherenceRefused(
            f"run-backed publication {run_id} has no lifecycle row")
    if str(row[0]) != "seed":
        return None
    if str(row[1]) != "success":
        raise SeedCoherenceRefused(
            f"seed {run_id} is {row[1]!r}; only SUCCESS can publish")
    date_from, date_to = str(row[2]), str(row[3])
    if (str(window_start), str(window_end)) != (date_from, date_to):
        raise SeedCoherenceRefused(
            f"seed publication window {window_start}..{window_end} differs from "
            f"durable run window {date_from}..{date_to}")
    raw = row[4]
    recovery = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    payload = recovery.get("seed_coherence") if isinstance(recovery, dict) else None
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise SeedCoherenceRefused(
            f"seed {run_id} lacks durable post-seed source/local coherence proof")
    required = {
        "schema", "phase", "run_id", "market_interval",
        "seed_start_update_boundary", "mutation_interval",
        "mutation_source_first", "mutation_source_second", "overlap",
        "normalized_source", "normalized_local", "final_mutation_cursor",
    }
    if not required.issubset(payload) or payload.get("phase") != "complete":
        raise SeedCoherenceRefused(
            f"seed {run_id} post-seed proof is incomplete")
    if (str(payload.get("run_id")) != str(run_id)
            or payload.get("market_interval") != [date_from, date_to]):
        raise SeedCoherenceRefused(
            f"seed {run_id} proof is bound to a different run/window")
    if payload.get("mutation_source_first") != payload.get("mutation_source_second"):
        raise SeedCoherenceRefused(
            f"seed {run_id} mutation source observations are not stable")
    overlap = payload.get("overlap")
    if (not isinstance(overlap, dict)
            or overlap.get("source_first") != overlap.get("source_second")):
        raise SeedCoherenceRefused(
            f"seed {run_id} trailing source observations are not stable")
    if payload.get("normalized_source") != payload.get("normalized_local"):
        raise SeedCoherenceRefused(
            f"seed {run_id} normalized source/local proof does not match")
    _strict_date(payload.get("final_mutation_cursor"),
                 label="final mutation cursor")
    return dict(payload)


__all__ = [
    "SCHEMA", "START_SCHEMA", "SeedCoherenceProof", "SeedCoherenceRefused",
    "capture_update_boundary", "capture_update_ceiling", "load", "prove",
    "record_start_boundary", "reopen_successful_run",
    "require_for_publication",
]

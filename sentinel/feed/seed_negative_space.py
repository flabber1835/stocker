"""Bounded self-heal for stable Sharadar SEP negative-space revisions.

A vendor can retract an historical SEP row after Sentinel previously published it.
The ordinary upsert path cannot observe absence, so a later exact trailing-source
proof sees a local-only key.  This module turns only that narrow, independently
re-observed condition into an exact retirement plan.  Missing local source rows,
value disagreements, unstable source observations, ticker/identity changes, and
large drifts continue to fail closed.

The plan does not mutate the published corpus.  Publication applies its exact
keys inside the same transaction as the new corpus version, so a failed publish
rolls the retirement back.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid

from sentinel.feed import (
    _seed_coherence_impl as core,
    calendar,
    domains,
    ingest_impl,
    publication,
    store,
)

RETIREMENT_SCHEMA = "sentinel.seed-stable-source-retirement/1"
RETIREMENT_REASON = "stable_source_absence"
MAX_RETIREMENTS = 256
_TEMP_SOURCE_KEYS = "sentinel_seed_stable_source_keys"
_TEMP_RETIRE_KEYS = "sentinel_seed_publication_retire_keys"


def _key_payload(security_id, session, ticker) -> dict:
    return {
        "security_id": str(security_id),
        "session": str(session),
        "ticker": str(ticker),
    }


def _keys_digest(keys: list[dict]) -> str:
    return hashlib.sha256(json.dumps(
        keys, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _create_source_key_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {_TEMP_SOURCE_KEYS} ("
            " security_id TEXT NOT NULL, session DATE NOT NULL,"
            " ticker TEXT NOT NULL, PRIMARY KEY(security_id,session,ticker))"
            " ON COMMIT PRESERVE ROWS")
        cur.execute(f"TRUNCATE {_TEMP_SOURCE_KEYS}")


def _drop_temp(conn, name: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {name}")
    except Exception:  # pragma: no cover - cleanup must not mask authority error
        pass


def _insert_source_keys(conn, rows: list[tuple[str, str, str]]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {_TEMP_SOURCE_KEYS}(security_id,session,ticker)"
            " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            rows)


def _normalised_source_partition(
        conn, *, rows, run_id: str, start: str, end: str,
        target_start: str, target_end: str, resolver,
        key_fp, value_fp) -> None:
    """Core source normalization plus an exact bounded key relation."""
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
    batch: list[tuple[str, str, str]] = []
    for item in normalised:
        bar = item.vendor
        if not target_start <= str(bar.session) <= target_end:
            continue
        security_id = str(bar.security_id)
        session = str(bar.session)
        ticker = str(bar.ticker)
        key_fp.add(security_id, session, ticker)
        value_fp.add(
            security_id, session, ticker,
            item.close_signal, bar.raw_close, bar.raw_open, bar.volume)
        batch.append((security_id, session, ticker))
        if len(batch) >= 5000:
            _insert_source_keys(conn, batch)
            batch.clear()
    _insert_source_keys(conn, batch)


def _candidate_local_proof(conn, *, run_id: str, start: str, end: str,
                           source_only: bool = False):
    key_fp = core._KeyFingerprint()
    value_fp = core._ValueFingerprint()
    source_filter = (
        f" AND EXISTS (SELECT 1 FROM {_TEMP_SOURCE_KEYS} s"
        " WHERE s.security_id=b.security_id AND s.session=b.session"
        "   AND s.ticker=b.ticker)" if source_only else "")
    sql = (
        "SELECT b.security_id,b.session,b.ticker,b.close_signal,"
        " b.close_unadjusted,b.open_unadjusted,b.volume"
        " FROM sentinel_bars b"
        " WHERE b.session BETWEEN %s AND %s"
        "   AND (b.last_written_run_id=%s OR "
        + publication.visible_predicate("b") + ")"
        + source_filter
        + " ORDER BY b.session,b.security_id")
    with store.streaming_cursor(conn, sql, (start, end, str(run_id))) as cur:
        for (security_id, session, ticker, close_signal, raw_close, raw_open,
             volume) in cur:
            key_fp.add(security_id, session, ticker)
            value_fp.add(
                security_id, session, ticker, close_signal, raw_close, raw_open,
                volume)
    if key_fp.rows != value_fp.rows:
        raise AssertionError("candidate local SEP key/value counts diverged")
    return core.NormalizedProof(
        rows=key_fp.rows, key_digest=key_fp.digest(),
        value_digest=value_fp.digest())


def _retirement_plan(conn, *, run_id: str, start: str, end: str,
                     source, local_before) -> dict:
    visible = publication.visible_predicate("b")
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT s.security_id,s.session,s.ticker FROM {_TEMP_SOURCE_KEYS} s"
            " WHERE NOT EXISTS ("
            "   SELECT 1 FROM sentinel_bars b"
            "    WHERE b.security_id=s.security_id AND b.session=s.session"
            "      AND b.ticker=s.ticker"
            "      AND (b.last_written_run_id=%s OR " + visible + "))"
            " ORDER BY s.session,s.security_id,s.ticker LIMIT 1",
            (str(run_id),))
        missing = cur.fetchone()
        if missing is not None:
            key = _key_payload(*missing)
            raise core.SeedCoherenceRefused(
                "stable trailing SEP source contains a normalized key absent "
                f"from candidate local state; automatic retirement cannot "
                f"repair missing source authority: {key}")

        cur.execute(
            "SELECT b.security_id,b.session,b.ticker FROM sentinel_bars b"
            " WHERE b.session BETWEEN %s AND %s"
            "   AND (b.last_written_run_id=%s OR " + visible + ")"
            f"   AND NOT EXISTS (SELECT 1 FROM {_TEMP_SOURCE_KEYS} s"
            "       WHERE s.security_id=b.security_id AND s.session=b.session"
            "         AND s.ticker=b.ticker)"
            " ORDER BY b.session,b.security_id,b.ticker LIMIT %s",
            (start, end, str(run_id), MAX_RETIREMENTS + 1))
        rows = list(cur.fetchall())
    if not rows:
        raise core.SeedCoherenceRefused(
            "stable trailing SEP source/local key proof disagreed without an "
            "exact local-only negative-space set")
    if len(rows) > MAX_RETIREMENTS:
        raise core.SeedCoherenceRefused(
            "stable trailing SEP source/local negative-space drift exceeds "
            f"bounded automatic retirement cap {MAX_RETIREMENTS}")
    keys = [_key_payload(*row) for row in rows]
    return {
        "schema": RETIREMENT_SCHEMA,
        "reason": RETIREMENT_REASON,
        "interval": [str(start), str(end)],
        "count": len(keys),
        "keys": keys,
        "keys_sha256": _keys_digest(keys),
        "local_rows_before": int(local_before.rows),
        "source_rows": int(source.rows),
        "source_key_sha256": str(source.key_digest),
        "source_value_sha256": str(source.value_digest),
    }


def validate_retirement_plan(plan, *, overlap=None, source=None) -> dict | None:
    if plan is None:
        return None
    if not isinstance(plan, dict):
        raise core.SeedCoherenceRefused("SEP source retirement plan is not an object")
    required = {
        "schema", "reason", "interval", "count", "keys", "keys_sha256",
        "local_rows_before", "source_rows", "source_key_sha256",
        "source_value_sha256",
    }
    if set(plan) != required or plan.get("schema") != RETIREMENT_SCHEMA:
        raise core.SeedCoherenceRefused("SEP source retirement plan schema is invalid")
    if plan.get("reason") != RETIREMENT_REASON:
        raise core.SeedCoherenceRefused("SEP source retirement reason is invalid")
    interval = plan.get("interval")
    if (not isinstance(interval, list) or len(interval) != 2
            or str(interval[0]) > str(interval[1])):
        raise core.SeedCoherenceRefused("SEP source retirement interval is invalid")
    if overlap is not None and interval != overlap.get("interval"):
        raise core.SeedCoherenceRefused(
            "SEP source retirement is bound to a different overlap interval")
    keys = plan.get("keys")
    if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_RETIREMENTS:
        raise core.SeedCoherenceRefused("SEP source retirement key count is invalid")
    normalized = []
    for raw in keys:
        if not isinstance(raw, dict) or set(raw) != {"security_id", "session", "ticker"}:
            raise core.SeedCoherenceRefused("SEP source retirement key is malformed")
        session = core._strict_date(raw.get("session"), label="retirement session")
        key = {
            "security_id": str(raw.get("security_id") or ""),
            "session": session.isoformat(),
            "ticker": str(raw.get("ticker") or "").strip().upper(),
        }
        if not key["security_id"] or not key["ticker"]:
            raise core.SeedCoherenceRefused("SEP source retirement key is incomplete")
        if not str(interval[0]) <= key["session"] <= str(interval[1]):
            raise core.SeedCoherenceRefused(
                "SEP source retirement key lies outside its proved interval")
        normalized.append(key)
    if normalized != sorted(
            normalized, key=lambda item: (item["session"], item["security_id"], item["ticker"])):
        raise core.SeedCoherenceRefused("SEP source retirement keys are not canonical")
    if len({(k["security_id"], k["session"], k["ticker"]) for k in normalized}) != len(normalized):
        raise core.SeedCoherenceRefused("SEP source retirement keys are duplicated")
    if int(plan.get("count")) != len(normalized):
        raise core.SeedCoherenceRefused("SEP source retirement count changed")
    if str(plan.get("keys_sha256")) != _keys_digest(normalized):
        raise core.SeedCoherenceRefused("SEP source retirement key digest changed")
    if source is not None:
        if (int(plan.get("source_rows")) != int(source.get("rows"))
                or str(plan.get("source_key_sha256")) != str(source.get("key_sha256"))
                or str(plan.get("source_value_sha256")) != str(source.get("value_sha256"))):
            raise core.SeedCoherenceRefused(
                "SEP source retirement no longer matches normalized source proof")
    return dict(plan)


def trailing_overlap_proof(
        conn, *, run, fetch, market_start: str, market_end: str,
        resolver, update_through: dt.date,
        required_closes: int | None = None):
    """Core trailing proof plus bounded pure-local negative-space planning."""
    if required_closes is None:
        from stock_strategy_shared.wealth_core.signals import REQUIRED_CLOSES
        required_closes = int(REQUIRED_CLOSES)
    if required_closes < 1:
        raise core.SeedCoherenceRefused(
            "required trailing close count must be positive")
    sessions = calendar.previous_sessions(market_end, required_closes)
    if len(sessions) != required_closes or not sessions or sessions[-1] != market_end:
        raise core.SeedCoherenceRefused(
            f"seed frontier {market_end} cannot expose the complete "
            f"{required_closes}-session Wealth Core close window")
    target_start, target_end = sessions[0], sessions[-1]
    label = f"seed-overlap:{target_start}:{target_end}"
    source_key = core._KeyFingerprint()
    source_value = core._ValueFingerprint()
    partition_evidence: list[dict] = []
    plan = None
    _create_source_key_table(conn)
    try:
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
                with core._stable_date_rows(
                        fetch, start=start, end=end,
                        update_through=update_through, resolver=resolver) as pair:
                    rows, evidence = pair
                    _normalised_source_partition(
                        conn, rows=rows, run_id=str(run.progress.run_id),
                        start=start, end=end, target_start=target_start,
                        target_end=target_end, resolver=resolver,
                        key_fp=source_key, value_fp=source_value)
                    partition_evidence.append(evidence.to_dict())

            source = core.NormalizedProof(
                rows=source_key.rows, key_digest=source_key.digest(),
                value_digest=source_value.digest())
            local_before = _candidate_local_proof(
                conn, run_id=str(run.progress.run_id),
                start=target_start, end=target_end)
            local = local_before
            if (source.rows != local_before.rows
                    or source.key_digest != local_before.key_digest):
                plan = _retirement_plan(
                    conn, run_id=str(run.progress.run_id),
                    start=target_start, end=target_end,
                    source=source, local_before=local_before)
                local = _candidate_local_proof(
                    conn, run_id=str(run.progress.run_id),
                    start=target_start, end=target_end, source_only=True)
                if (source.rows != local.rows
                        or source.key_digest != local.key_digest):
                    raise core.SeedCoherenceRefused(
                        "stable trailing SEP mismatch is not explainable solely "
                        "by the bounded local-only negative-space retirement set")
            if source.value_digest != local.value_digest:
                raise core.SeedCoherenceRefused(
                    "stable trailing SEP source and candidate local strategy values "
                    f"disagree over {target_start}..{target_end}: source "
                    f"{source.value_digest[:16]}, local {local.value_digest[:16]}")

        if not partition_evidence:
            raise core.SeedCoherenceRefused(
                "trailing source proof produced no partitions")
        first = core._combined_observation(partition_evidence, "first")
        second = core._combined_observation(partition_evidence, "second")
        overlap = {
            "interval": [target_start, target_end],
            "required_closes": int(required_closes),
            "normalization_partitions": partition_evidence,
            "source_first": first.to_dict(),
            "source_second": second.to_dict(),
        }
        if plan is not None:
            overlap["source_retirement"] = plan
            overlap["local_before_source_retirement"] = local_before.to_dict()
        return overlap, source, local
    finally:
        _drop_temp(conn, _TEMP_SOURCE_KEYS)


def retirement_from_proof(proof) -> dict | None:
    if not isinstance(proof, dict):
        return None
    overlap = proof.get("overlap")
    if not isinstance(overlap, dict):
        return None
    return validate_retirement_plan(
        overlap.get("source_retirement"), overlap=overlap,
        source=proof.get("normalized_source"))


def apply_publication_retirements(conn, *, run_id: str, proof) -> dict | None:
    """Delete exact proved local-only keys inside the publication transaction."""
    plan = retirement_from_proof(proof)
    if plan is None:
        return None
    if str(proof.get("run_id")) != str(run_id):
        raise core.SeedCoherenceRefused(
            "SEP source retirement proof is bound to a different ingest run")
    store._assert_corpus_locked(conn)
    keys = plan["keys"]
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {_TEMP_RETIRE_KEYS} ("
            " security_id TEXT NOT NULL, session DATE NOT NULL, ticker TEXT NOT NULL,"
            " PRIMARY KEY(security_id,session,ticker)) ON COMMIT PRESERVE ROWS")
        cur.execute(f"TRUNCATE {_TEMP_RETIRE_KEYS}")
        cur.executemany(
            f"INSERT INTO {_TEMP_RETIRE_KEYS}(security_id,session,ticker)"
            " VALUES (%s,%s,%s)",
            [(k["security_id"], k["session"], k["ticker"]) for k in keys])
        visible = publication.visible_predicate("b")
        cur.execute(
            f"SELECT COUNT(*) FROM sentinel_bars b JOIN {_TEMP_RETIRE_KEYS} r"
            " ON r.security_id=b.security_id AND r.session=b.session"
            " AND r.ticker=b.ticker"
            " WHERE b.last_written_run_id=%s OR " + visible,
            (str(run_id),))
        matched = int(cur.fetchone()[0])
        if matched != len(keys):
            raise core.SeedCoherenceRefused(
                "SEP source retirement target changed after durable proof; "
                f"expected {len(keys)} exact rows, found {matched}")
        cur.execute(
            f"DELETE FROM sentinel_bars b USING {_TEMP_RETIRE_KEYS} r"
            " WHERE b.security_id=r.security_id AND b.session=r.session"
            "   AND b.ticker=r.ticker")
        deleted = int(cur.rowcount)
        if deleted != len(keys):
            raise core.SeedCoherenceRefused(
                "SEP source retirement was not exact; publication rolled back")
    _drop_temp(conn, _TEMP_RETIRE_KEYS)
    return {
        "schema": RETIREMENT_SCHEMA,
        "count": deleted,
        "keys_sha256": plan["keys_sha256"],
        "interval": plan["interval"],
    }


__all__ = [
    "MAX_RETIREMENTS", "RETIREMENT_REASON", "RETIREMENT_SCHEMA",
    "apply_publication_retirements", "retirement_from_proof",
    "trailing_overlap_proof", "validate_retirement_plan",
]

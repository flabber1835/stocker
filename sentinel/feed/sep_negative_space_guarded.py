"""Economic safety membrane for SEP negative-space retirement.

The underlying negative-space module proves exact source absence, key/value
stability, bounded cardinality, durability, and atomic publication.  This module
adds the remaining economic proof before any row is retired: a disappearing SEP
bar may not carry a split or dividend, and removing event-free bars may not
change the split edge observed by the next surviving bar.
"""
from __future__ import annotations

import datetime as dt

from sentinel.feed import domains, publication, sep_negative_space as core
from stock_strategy_shared.split_reconciliation import (
    split_ratio_bounds,
    split_ratio_matches,
)

KIND = core.KIND
MAX_RETIREMENTS = core.MAX_RETIREMENTS
SCHEMA = core.SCHEMA
SepNegativeSpaceRefused = core.SepNegativeSpaceRefused


def _assert_retired_rows_have_no_economic_events(conn, keys: list[dict]) -> None:
    """SEP absence cannot cancel an independently established economic event."""
    core._load_retire_table(conn, keys)
    effective = publication.effective_split_ratio("b")
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT b.security_id,b.session,b.ticker,{effective},"
            " b.dividend_per_share"
            f" FROM sentinel_bars b JOIN {core._TEMP_RETIRE_KEYS} r"
            " ON r.security_id=b.security_id AND r.session=b.session"
            " AND r.ticker=b.ticker WHERE " + publication.visible_predicate("b")
            + " ORDER BY b.session,b.security_id,b.ticker")
        rows = list(cur.fetchall())
    if len(rows) != len(keys):
        raise SepNegativeSpaceRefused(
            "SEP retirement target changed before economic-event proof")
    for sid, session, ticker, split_ratio, dividend in rows:
        split = float(split_ratio or 1.0)
        div = float(dividend or 0.0)
        if abs(split - 1.0) > 1e-12:
            raise SepNegativeSpaceRefused(
                "SEP retirement row carries an effective split event: "
                f"{sid}/{session}/{ticker} split_ratio={split:g}")
        if abs(div) > 1e-12:
            raise SepNegativeSpaceRefused(
                "SEP retirement row carries a dividend entitlement: "
                f"{sid}/{session}/{ticker} dividend_per_share={div:g}")


def _assert_retirement_preserves_split_chain(conn, keys: list[dict]) -> None:
    """Verify the next surviving split edge with unsnapped price evidence."""
    effective = publication.effective_split_ratio("b")
    visible = publication.visible_predicate("b")
    for key in keys:
        sid, session = key["security_id"], key["session"]
        with conn.cursor() as cur:
            cur.execute(
                "SELECT b.close_signal,b.close_unadjusted FROM sentinel_bars b"
                " WHERE b.security_id=%s AND b.session<%s AND " + visible +
                f" AND NOT EXISTS (SELECT 1 FROM {core._TEMP_RETIRE_KEYS} r"
                "  WHERE r.security_id=b.security_id AND r.session=b.session"
                "    AND r.ticker=b.ticker)"
                " ORDER BY b.session DESC LIMIT 1",
                (sid, session))
            prev_row = cur.fetchone()
            cur.execute(
                "SELECT b.close_signal,b.close_unadjusted," + effective +
                " FROM sentinel_bars b"
                " WHERE b.security_id=%s AND b.session>%s AND " + visible +
                f" AND NOT EXISTS (SELECT 1 FROM {core._TEMP_RETIRE_KEYS} r"
                "  WHERE r.security_id=b.security_id AND r.session=b.session"
                "    AND r.ticker=b.ticker)"
                " ORDER BY b.session ASC LIMIT 1",
                (sid, session))
            next_row = cur.fetchone()
        if next_row is None or prev_row is None:
            continue
        required = domains.unsnapped_split_ratio(
            prev_row[0], prev_row[1], next_row[0], next_row[1])
        effective_next = float(next_row[2] or 1.0)
        bounds = split_ratio_bounds(
            prev_row[0], prev_row[1], next_row[0], next_row[1])
        matches, _quantized = split_ratio_matches(
            effective_next, required, bounds)
        if not matches:
            raise SepNegativeSpaceRefused(
                "SEP retirement would change the effective split chain for "
                f"{sid} after {session}: surviving successor price evidence "
                f"implies {required!r}, published ratio is {effective_next:g}")


def repair_local_only(
        conn, *, fetch, start: str, end: str, observation_ceiling,
        expected_source):
    """Retire exact negative space only after the complete economic proof."""
    core.store._assert_corpus_locked(conn)
    ceiling = (
        observation_ceiling if isinstance(observation_ceiling, dt.date)
        else dt.date.fromisoformat(str(observation_ceiling)))
    core._create_source_table(conn)
    try:
        source = core._source_proof_and_keys(
            conn, fetch=fetch, start=start, end=end,
            observation_ceiling=ceiling)
        if (source.rows != expected_source.rows
                or source.key_digest != expected_source.key_digest
                or source.value_digest != expected_source.value_digest):
            raise SepNegativeSpaceRefused(
                "SEP source changed between mismatch detection and bounded "
                "retirement re-observation")
        local_source = core._source_only_local_proof(conn, start=start, end=end)
        if (local_source.rows != source.rows
                or local_source.key_digest != source.key_digest):
            raise SepNegativeSpaceRefused(
                "current SEP source contains keys absent from published local state; "
                "automatic negative-space retirement cannot repair insertion or "
                "identity drift")
        if local_source.value_digest != source.value_digest:
            raise SepNegativeSpaceRefused(
                "current SEP source values disagree with published local values; "
                "automatic negative-space retirement cannot repair value drift")
        keys = core._local_only_keys(conn, start=start, end=end)
        if len(keys) != int(core.recon._local_fingerprint(
                conn, start=start, end=end).rows - source.rows):
            raise SepNegativeSpaceRefused(
                "SEP local-only row count changed during retirement planning")
        core._load_retire_table(conn, keys)
        _assert_retired_rows_have_no_economic_events(conn, keys)
        _assert_retirement_preserves_split_chain(conn, keys)
        plan = core._plan(
            start=start, end=end, source=source,
            expected_source=expected_source, keys=keys)
        run = core.store.IngestRun(
            conn, KIND, date_from=start, date_to=end, chunks_total=1)
        run_id = str(run.progress.run_id)
        core._persist_plan(conn, run_id=run_id, plan=plan)
        try:
            published = core._retire_and_publish(conn, run=run, plan=plan)
        except BaseException as exc:  # noqa: BLE001
            conn.rollback()
            if not core._publication_committed_for_run(conn, run_id):
                run.finish("failed", f"{type(exc).__name__}: {exc}")
            raise
        return {"publication": published, "plan": plan}
    finally:
        core._drop_temp(conn, core._TEMP_SOURCE_KEYS)
        core._drop_temp(conn, core._TEMP_RETIRE_KEYS)


__all__ = [
    "KIND", "MAX_RETIREMENTS", "SCHEMA", "SepNegativeSpaceRefused",
    "repair_local_only",
]

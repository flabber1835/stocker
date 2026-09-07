"""Guarded economic-preserving SEP negative-space retirement."""
from __future__ import annotations

import datetime as dt

from sentinel.feed import publication, sep_negative_space as core
from sentinel.feed.domains import (
    SPLIT_UNRESOLVED,
    raw_prices_refute_listed_split,
    resolve_split_orientation,
    split_price_evidence,
    split_ratio_bounds,
)
from sentinel.feed import domains

KIND = core.KIND
MAX_RETIREMENTS = core.MAX_RETIREMENTS
SCHEMA = core.SCHEMA
SepNegativeSpaceRefused = core.SepNegativeSpaceRefused
_ORIGINAL_REPAIR = core.repair_local_only


def _assert_retired_rows_have_no_economic_events(conn, keys: list[dict]) -> None:
    """Every exact retirement target is economically empty in published state."""
    if not keys:
        return
    core._load_retire_table(conn, keys)
    effective = publication.effective_split_ratio("b")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT b.security_id,b.session,b.ticker," + effective +
            ", b.dividend_per_share"
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


def _assert_current_actions_have_no_retirement_events(conn, keys: list[dict]) -> None:
    """Current complete ACTIONS may establish economics absent from a stale bar.

    A disappearing SEP row cannot be relied on to receive a replayed split or
    dividend value. Rebuild the canonical action maps for the retirement span and
    reject any target session carrying a current split or usable dividend event.
    """
    if not keys:
        return
    from sentinel.feed import ingest_impl

    start = min(str(key["session"]) for key in keys)
    end = max(str(key["session"]) for key in keys)
    splits, dividends, _rows, _ambiguous = ingest_impl._action_maps(
        conn, start, end)
    split_keys = {(str(t).upper(), str(s)) for t, s in splits}
    dividend_keys = {(str(t).upper(), str(s)) for t, s in dividends}
    for key in keys:
        ticker = str(key["ticker"]).upper()
        session = str(key["session"])
        if (ticker, session) in split_keys:
            raise SepNegativeSpaceRefused(
                "SEP retirement target carries a current authoritative ACTIONS "
                f"split event: {key['security_id']}/{session}/{ticker}")
        if (ticker, session) in dividend_keys:
            raise SepNegativeSpaceRefused(
                "SEP retirement target carries a current authoritative ACTIONS "
                f"dividend entitlement: {key['security_id']}/{session}/{ticker}")


def _assert_retirement_preserves_split_chain(conn, keys: list[dict]) -> None:
    """Resolve the next surviving edge with canonical ingest split semantics."""
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
        price_event = split_price_evidence(required)

        if abs(effective_next - 1.0) <= 1e-12:
            if price_event is None:
                continue
            raise SepNegativeSpaceRefused(
                "SEP retirement would change the effective split chain for "
                f"{sid} after {session}: bridge price evidence implies material "
                f"split ratio {required!r}, published ratio is 1")

        resolved, disposition = resolve_split_orientation(
            effective_next, required, bounds=bounds,
            explicit_no_event=(required is not None and price_event is None),
            raw_refutes_event=raw_prices_refute_listed_split(
                effective_next, prev_row[1], next_row[1]))
        if (disposition == SPLIT_UNRESOLVED
                or abs(float(resolved) - effective_next) > 1e-12):
            raise SepNegativeSpaceRefused(
                "SEP retirement would change the effective split chain for "
                f"{sid} after {session}: canonical bridge resolution is "
                f"{disposition}/{resolved:g} from price evidence {required!r}, "
                f"published ratio is {effective_next:g}")


def repair_local_only(
        conn, *, fetch, start: str, end: str, observation_ceiling,
        expected_source, source_authority_evidence=None,
        actions_authority_evidence=None):
    """Retire exact negative space only after source and economic proof."""
    if core.repair_local_only is not _ORIGINAL_REPAIR:
        return core.repair_local_only(
            conn, fetch=fetch, start=start, end=end,
            observation_ceiling=observation_ceiling,
            expected_source=expected_source)

    if source_authority_evidence is not None and actions_authority_evidence is None:
        raise SepNegativeSpaceRefused(
            "production SEP retirement lacks fresh complete ACTIONS authority")

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
        _assert_current_actions_have_no_retirement_events(conn, keys)
        _assert_retirement_preserves_split_chain(conn, keys)
        plan = core._plan(
            start=start, end=end, source=source,
            expected_source=expected_source, keys=keys)
        if source_authority_evidence is not None:
            plan["source_authority"] = dict(source_authority_evidence)
        if actions_authority_evidence is not None:
            plan["actions_authority"] = dict(actions_authority_evidence)
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

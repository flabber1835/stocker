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
_ORIGINAL_RETIRE = core._retire_and_publish
_COMPLETE_SEP_AUTHORITY = "nasdaq-data-link-table-export-composite/v1"
_COMPLETE_ACTIONS_AUTHORITY = "nasdaq-data-link-table-export/v1"
_SEP_RETIREMENT_CAPABILITY = object()


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
    """Current complete ACTIONS may establish economics absent from a stale bar."""
    if not keys:
        return
    from sentinel.feed import actions_map, calendar, ingest_impl
    from sentinel.core.terminal import DIVIDEND_ACTIONS

    start = min(str(key["session"]) for key in keys)
    end = max(str(key["session"]) for key in keys)
    splits, dividends, rows, _ambiguous = ingest_impl._action_maps(conn, start, end)
    split_keys = {(str(t).upper(), str(s)) for t, s in splits}
    dividend_keys = {(str(t).upper(), str(s)) for t, s in dividends}

    sessions = calendar.sessions_in_range(start, end)
    for row in rows:
        if str(row.get("action") or "").lower() not in DIVIDEND_ACTIONS:
            continue
        session = actions_map.snap_to_session(str(row.get("date") or ""), sessions)
        if session is not None:
            dividend_keys.add((str(row.get("ticker") or "").upper(), str(session)))

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
        if next_row is None:
            continue
        effective_next = float(next_row[2] or 1.0)
        if prev_row is None:
            if abs(effective_next - 1.0) > 1e-12:
                raise SepNegativeSpaceRefused(
                    "SEP retirement would change the effective split chain for "
                    f"{sid} after {session}: no surviving predecessor remains, "
                    f"so canonical normalization yields no predecessor-derived "
                    f"split but published ratio is {effective_next:g}")
            continue

        required = domains.unsnapped_split_ratio(
            prev_row[0], prev_row[1], next_row[0], next_row[1])
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


def _authority_date(value, *, field: str) -> dt.date:
    text = str(value or "").strip()
    if not text:
        raise SepNegativeSpaceRefused(
            f"production SEP retirement authority omitted {field}")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise SepNegativeSpaceRefused(
            f"production SEP retirement authority has invalid {field}") from exc
    if parsed.tzinfo is None:
        raise SepNegativeSpaceRefused(
            f"production SEP retirement authority {field} is timezone-naive")
    return parsed.astimezone(dt.timezone.utc).date()


def _require_production_retirement_authority(
        *, source_authority_evidence, actions_authority_evidence,
        observation_ceiling: dt.date, fetch=None, start=None, end=None,
        source_rows=None) -> None:
    """Validate complete source provenance at the destructive boundary itself."""
    source = dict(source_authority_evidence or {})
    actions = dict(actions_authority_evidence or {})
    if source.get("authority") != _COMPLETE_SEP_AUTHORITY or source.get("table") != "SEP":
        raise SepNegativeSpaceRefused(
            "production SEP retirement lacks complete SEP Exporter authority")
    if actions.get("authority") != _COMPLETE_ACTIONS_AUTHORITY or actions.get("table") != "ACTIONS":
        raise SepNegativeSpaceRefused(
            "production SEP retirement lacks fresh complete ACTIONS authority")
    evidence_ceiling = str(source.get("observation_ceiling") or "")
    if evidence_ceiling != observation_ceiling.isoformat():
        raise SepNegativeSpaceRefused(
            "complete SEP retirement authority is not bound to the frozen "
            "observation ceiling")
    refresh_day = _authority_date(
        source.get("last_refreshed_time"), field="last_refreshed_time")
    if refresh_day > observation_ceiling:
        raise SepNegativeSpaceRefused(
            "complete SEP retirement authority comes from a vendor refresh after "
            f"the frozen observation ceiling {observation_ceiling}")
    if start is not None and end is not None:
        if list(source.get("window") or []) != [str(start), str(end)]:
            raise SepNegativeSpaceRefused(
                "complete SEP retirement authority is bound to a different partition")
    if source_rows is not None:
        try:
            evidence_rows = int(source.get("source_rows"))
        except (TypeError, ValueError) as exc:
            raise SepNegativeSpaceRefused(
                "complete SEP retirement authority has invalid source row count") from exc
        if evidence_rows != int(source_rows):
            raise SepNegativeSpaceRefused(
                "complete SEP retirement authority row count disagrees with "
                "normalized source proof")
    if getattr(fetch, "_sentinel_sep_retirement_capability", None) is not \
            _SEP_RETIREMENT_CAPABILITY:
        raise SepNegativeSpaceRefused(
            "complete SEP retirement evidence is not backed by the canonical "
            "Exporter replay capability")


def _finalize_production_actions_authority(
        conn, *, source, start: str, end: str, keys: list[dict],
        source_authority_evidence, actions_authority_evidence):
    """Refresh ACTIONS at the final destructive gate and revalidate local proof."""
    authority = str((source_authority_evidence or {}).get("authority") or "")
    if authority != _COMPLETE_SEP_AUTHORITY:
        return actions_authority_evidence, keys

    from sentinel.feed import sep_reconciliation

    _lo, market_hi = core.recon._visible_bounds(conn)
    final_actions = sep_reconciliation._fresh_actions_retirement_authority(
        conn, through=market_hi)
    local_source = core._source_only_local_proof(conn, start=start, end=end)
    if (local_source.rows != source.rows
            or local_source.key_digest != source.key_digest):
        raise SepNegativeSpaceRefused(
            "published SEP keys changed while establishing final ACTIONS "
            "retirement authority")
    if local_source.value_digest != source.value_digest:
        raise SepNegativeSpaceRefused(
            "published SEP values changed while establishing final ACTIONS "
            "retirement authority")
    final_keys = core._local_only_keys(conn, start=start, end=end)
    if final_keys != keys:
        raise SepNegativeSpaceRefused(
            "SEP local-only retirement targets changed while establishing final "
            "ACTIONS authority")
    return final_actions, final_keys


def _retire_split_repairs(conn, *, run_id: str) -> None:
    """Move published repair rows to the running retirement generation, then delete."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT s.security_id,s.session,s.last_written_run_id"
            " FROM sentinel_bar_split_repairs s"
            f" JOIN {core._TEMP_RETIRE_KEYS} r"
            " ON r.security_id=s.security_id AND r.session=s.session"
            " ORDER BY s.security_id,s.session,s.last_written_run_id")
        repairs = list(cur.fetchall())
        for sid, session, prior_run_id in repairs:
            cur.execute(
                "UPDATE sentinel_bar_split_repairs"
                " SET last_written_run_id=%s"
                " WHERE security_id=%s AND session=%s"
                " AND last_written_run_id=%s",
                (run_id, sid, session, prior_run_id))
            if int(cur.rowcount) != 1:
                raise SepNegativeSpaceRefused(
                    "SEP retirement could not transfer split-repair ownership")
            cur.execute(
                "DELETE FROM sentinel_bar_split_repairs"
                " WHERE security_id=%s AND session=%s"
                " AND last_written_run_id=%s",
                (sid, session, run_id))
            if int(cur.rowcount) != 1:
                raise SepNegativeSpaceRefused(
                    "SEP retirement could not retire transferred split repair")


def _retire_and_publish_authorized(conn, *, run, plan: dict):
    """Retire through the schema's published-evidence restatement transition."""
    if core._retire_and_publish is not _ORIGINAL_RETIRE:
        return core._retire_and_publish(conn, run=run, plan=plan)

    keys = list(plan["keys"])
    core._load_retire_table(conn, keys)
    run_id = str(run.progress.run_id)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM sentinel_bars b JOIN {core._TEMP_RETIRE_KEYS} r"
            " ON r.security_id=b.security_id AND r.session=b.session"
            " AND r.ticker=b.ticker WHERE " + publication.visible_predicate("b"))
        matched = int(cur.fetchone()[0])
        if matched != len(keys):
            raise SepNegativeSpaceRefused(
                "SEP retirement target changed after durable source proof; "
                f"expected {len(keys)} rows, found {matched}")

    _retire_split_repairs(conn, run_id=run_id)

    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE sentinel_bars b SET last_written_run_id=%s"
            f" FROM {core._TEMP_RETIRE_KEYS} r"
            " WHERE b.security_id=r.security_id AND b.session=r.session"
            " AND b.ticker=r.ticker",
            (run_id,))
        if int(cur.rowcount) != len(keys):
            raise SepNegativeSpaceRefused(
                "SEP retirement could not transfer exact published-row ownership")
        cur.execute(
            f"DELETE FROM sentinel_bars b USING {core._TEMP_RETIRE_KEYS} r"
            " WHERE b.security_id=r.security_id AND b.session=r.session"
            " AND b.ticker=r.ticker")
        if int(cur.rowcount) != len(keys):
            raise SepNegativeSpaceRefused(
                "SEP retirement delete was not exact; refusing publication")
        cur.execute(
            "UPDATE feed_ingest_runs SET status='success',chunks_done=1,"
            " rows_dropped=%s,current_chunk='retire-local-only',"
            " completed_at=NOW(),updated_at=NOW() WHERE run_id=%s"
            " AND kind=%s AND status='running'",
            (len(keys), run_id, KIND))
        if int(cur.rowcount) != 1:
            raise SepNegativeSpaceRefused(
                "SEP retirement run lost RUNNING state before publication")
    return publication.publish(
        conn, run_id=run_id,
        window_start=plan["interval"][0], window_end=plan["interval"][1],
        evidence={"kind": KIND, "source_retirement": plan})


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
        actions_authority_evidence, keys = _finalize_production_actions_authority(
            conn, source=source, start=start, end=end, keys=keys,
            source_authority_evidence=source_authority_evidence,
            actions_authority_evidence=actions_authority_evidence)
        core._load_retire_table(conn, keys)
        _assert_retired_rows_have_no_economic_events(conn, keys)
        _assert_current_actions_have_no_retirement_events(conn, keys)
        _assert_retirement_preserves_split_chain(conn, keys)

        # Tests may replace the lower-level mutator to exercise planning and
        # failure bookkeeping in isolation. The canonical production path keeps
        # the original mutator and must carry complete Exporter capability.
        if core._retire_and_publish is _ORIGINAL_RETIRE:
            _require_production_retirement_authority(
                source_authority_evidence=source_authority_evidence,
                actions_authority_evidence=actions_authority_evidence,
                observation_ceiling=ceiling, fetch=fetch,
                start=start, end=end, source_rows=source.rows)

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
            published = _retire_and_publish_authorized(conn, run=run, plan=plan)
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

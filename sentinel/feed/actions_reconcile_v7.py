"""ACTIONS epoch v8 — adjudicated cash and typed in-kind distributions.

The v6 implementation remains the complete Sharadar ACTIONS source authority.
This public epoch composes that source proof with the A1 semantic migration: a
reviewed disputed cash action is replayed once through the ordinary normalized
bar path before a current cursor can be earned. The v8 epoch also removes
historical spin-off value that earlier decoders incorrectly booked as cash.
"""
from __future__ import annotations

import datetime as dt

from sentinel.feed import corporate_action_authority
from sentinel.feed import maintenance_impl as _core

ACTIONS_CURSOR_NAME = "sharadar-actions-export-reconcile:v8"
ACTIONS_CURSOR_KIND = "sharadar-actions-export-reconcile/v8"


def load_actions_cursor(conn):
    """Only v8 may authorize current public ACTIONS semantics."""
    return _core._read_cursor(
        conn, ACTIONS_CURSOR_NAME, ACTIONS_CURSOR_KIND)


def _cash_adjudication_audit(conn, *, run_id: str, dates, windows) -> list[dict]:
    """Bind each reviewed source fact to the exact canonical candidate bar.

    The source row itself remains in the published ACTIONS generation. This
    evidence names that immutable row plus the permanent security id and the
    normalized bar that consumed the adjudicated amount. Publication signs the
    resulting object into its normal validation-receipt chain.
    """
    from sentinel.feed import actions, calendar, publication

    source_rows = actions.active_rows(
        conn, start=min(dates), end=max(dates))
    sessions = calendar.sessions_in_range(windows[0][0], windows[-1][1])
    resolution = corporate_action_authority.resolve_dividends(
        source_rows, sessions)
    audit = []
    for adjudication in resolution.adjudications:
        matching_source = [
            row for row in source_rows
            if str(row.get("ticker") or "").upper() == adjudication.ticker
            and str(row.get("action") or "").lower()
                == str(adjudication.event_id).rsplit(":", 1)[-1]
            and str(row.get("date") or "")
                == adjudication.source_action_date
        ]
        if len(matching_source) != 1:
            raise corporate_action_authority.CorporateActionAuthorityRefused(
                f"cash adjudication {adjudication.event_id} lost its exact "
                f"published Sharadar source row while building audit evidence")
        source_row_id = str(matching_source[0].get("source_row_id") or "")
        if not source_row_id:
            raise corporate_action_authority.CorporateActionAuthorityRefused(
                f"cash adjudication {adjudication.event_id} has no durable "
                "Sharadar source-row identity")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT b.security_id,b.dividend_per_share"
                " FROM sentinel_bars b"
                " WHERE UPPER(b.ticker)=%s AND b.session=%s AND ("
                + publication.visible_predicate("b")
                + " OR b.last_written_run_id=%s)",
                (adjudication.ticker, adjudication.effective_session,
                 str(run_id)))
            candidate_rows = cur.fetchall()
        if len(candidate_rows) != 1:
            raise corporate_action_authority.CorporateActionAuthorityRefused(
                f"cash adjudication {adjudication.event_id} requires exactly "
                f"one canonical security/bar mapping; found "
                f"{len(candidate_rows)}")
        security_id, normalized_cash = candidate_rows[0]
        if not security_id:
            raise corporate_action_authority.CorporateActionAuthorityRefused(
                f"cash adjudication {adjudication.event_id} has no permanent "
                "security identity")

        item = adjudication.to_dict()
        item.update({
            "source_row_id": source_row_id,
            "security_id": str(security_id),
            "normalized_bar_dividend_per_share": str(normalized_cash),
        })
        audit.append(item)
    if {item["source_action_date"] for item in audit} != set(dates):
        raise corporate_action_authority.CorporateActionAuthorityRefused(
            "cash-adjudication semantic replay did not produce a canonical "
            "audit binding for every retained disputed action date")
    return sorted(audit, key=lambda item: item["event_id"])


def _cash_semantic_migration(conn, *, fetch, through: dt.date):
    """Replay every retained reviewed cash event through canonical ingest logic."""
    market_start, market_end = _core._retained_market_bounds(conn)
    cash_dates = corporate_action_authority.semantic_replay_dates(
        market_start=market_start,
        market_end=min(market_end, through.isoformat()))
    from sentinel.core.terminal import SPINOFF_ACTIONS
    from sentinel.feed import actions, calendar
    raw_start, raw_end = calendar.action_date_window(
        market_start, min(market_end, through.isoformat()))
    spin_rows = [row for row in actions.active_rows(
        conn, start=raw_start, end=raw_end)
        if str(row.get("action") or "").lower() in SPINOFF_ACTIONS
        and market_start <= calendar.session_on_or_after(str(row["date"])) <= market_end]
    dates = sorted(set(cash_dates) | {str(row["date"]) for row in spin_rows})
    if not dates:
        return _core.publication.require_current(conn)

    windows = _core.renormalize.correction_windows(
        dates, market_start=market_start, market_end=market_end)
    if not windows:
        return _core.publication.require_current(conn)

    run = _core.store.IngestRun(
        conn, "actions_reconcile",
        date_from=windows[0][0], date_to=windows[-1][1],
        chunks_total=len(windows))
    replayed = _core.renormalize.renormalize(
        conn, fetch=fetch, run=run, dates=dates,
        chunk_prefix="action-economics-v8",
        market_start=market_start, market_end=market_end)
    adjudication_audit = _cash_adjudication_audit(
        conn, run_id=run.progress.run_id, dates=cash_dates, windows=windows
    ) if cash_dates else []
    run.finish("success")
    return _core.publication.publish(
        conn, run_id=run.progress.run_id,
        window_start=windows[0][0], window_end=windows[-1][1],
        evidence={
            "kind": "actions_economic_semantics_v8",
            "semantic_epoch": ACTIONS_CURSOR_KIND,
            "authority": corporate_action_authority.authority_manifest(),
            "adjudications": adjudication_audit,
            "in_kind_distributions": [
                {"ticker": str(row["ticker"]), "date": str(row["date"]),
                 "source_row_id": str(row["source_row_id"]),
                 "value_evidence": str(row.get("value")),
                 "policy": "REQUIRE_REVIEWED_CHILD_OWNERSHIP"}
                for row in spin_rows],
            "affected_action_dates": dates,
            "retained_market_window": [market_start, market_end],
            "replay_windows": [
                {"start": item.start, "end": item.end,
                 "source_rows": item.source_rows,
                 "bars_written": item.bars_written,
                 "rows_dropped": item.rows_dropped}
                for item in replayed],
        })


def reconcile_actions_if_due(conn, *, fetch=_core.sharadar.fetch_table,
                             through: str, force: bool = False):
    """Earn complete source authority plus v8 economic semantics."""
    _core.store._assert_corpus_locked(conn)
    hi = dt.date.fromisoformat(str(through))
    prior = load_actions_cursor(conn)
    if prior is not None and prior.processed_through > hi:
        raise _core.SharadarMutationRefused(
            f"ACTIONS v8 reconciliation cursor {prior.processed_through} is "
            f"ahead of requested reconciliation through {hi}")

    # v6 proves the complete current Sharadar ACTIONS snapshot and handles all
    # ordinary changed-row/recovery semantics. v8 may be granted only after it.
    _core.reconcile_actions_if_due(
        conn, fetch=fetch, through=hi.isoformat(), force=force)

    if prior is None:
        current = _cash_semantic_migration(conn, fetch=fetch, through=hi)
    else:
        current = _core.publication.require_current(conn)

    return _core._write_cursor(
        conn, name=ACTIONS_CURSOR_NAME, kind=ACTIONS_CURSOR_KIND,
        through=hi, publication_version=current.version)


__all__ = [
    "ACTIONS_CURSOR_KIND", "ACTIONS_CURSOR_NAME",
    "load_actions_cursor", "reconcile_actions_if_due",
]

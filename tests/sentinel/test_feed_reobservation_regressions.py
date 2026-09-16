from __future__ import annotations

from contextlib import nullcontext
import datetime as dt
from types import SimpleNamespace

from sentinel.feed import actions, ingest, outage_recovery, source_aliases


def test_go_opt_in_reobserves_already_current_market_frontier(monkeypatch):
    target = "2026-09-02"
    calls = []
    start, end = outage_recovery.operational_source.price_window(target)
    monkeypatch.setattr(outage_recovery.publication, "operational_boundary",
                        lambda *_args, **_kwargs: SimpleNamespace(start=start))

    def acquisition(lo, hi, *, download):
        assert download is True
        calls.append(("acquisition", lo, hi))
        return nullcontext()

    monkeypatch.setattr(outage_recovery.operational_source, "acquisition", acquisition)

    monkeypatch.setattr(
        outage_recovery.store, "latest_visible_session", lambda _conn: target)
    monkeypatch.setattr(
        outage_recovery.publication, "operational_coherence",
        lambda _conn, **_kwargs: SimpleNamespace(coherent=True))
    monkeypatch.setattr(
        outage_recovery.publication, "chain_gaps", lambda _conn: [])
    monkeypatch.setattr(
        outage_recovery.publication, "assert_operationally_coherent",
        lambda _conn, **_kwargs: calls.append("coherence"))
    monkeypatch.setattr(
        outage_recovery.backup_guard, "require_writes_permitted",
        lambda *_args, **_kwargs: calls.append("backup"))
    monkeypatch.setattr(
        outage_recovery.ingest, "daily",
        lambda _conn, *, today: calls.append(("daily", today)))

    result = outage_recovery.catch_up(
        SimpleNamespace(), target_session=target, reobserve_current=True)

    assert result.mode == "ALREADY_CURRENT"
    assert result.recovered_from is None
    assert calls == ["backup", ("acquisition", start, end), "backup",
                     ("daily", target), "coherence"]


def test_failed_sep_candidate_retries_on_vendor_clock_when_cursor_leads_market(
        monkeypatch):
    source_day = dt.datetime.now(dt.timezone.utc).date()
    market_day = source_day - dt.timedelta(days=1)
    identity_reads = []

    def production_fetch(table, params):
        identity_reads.append((table, dict(params)))
        return []

    failed = SimpleNamespace(kind="sep_mutations", run_id="failed-sep")
    candidate_reads = iter((failed, None))
    reconcile_calls = []

    monkeypatch.setattr(
        ingest, "_authoritative_source", lambda _fetch: production_fetch)
    monkeypatch.setattr(
        ingest, "_validate_source_before_run", lambda _fetch: None)
    monkeypatch.setattr(
        ingest.snapshot_source, "fetch_table", production_fetch)
    monkeypatch.setattr(
        ingest.feed_store, "corpus_write_lock", lambda _conn: nullcontext())
    monkeypatch.setattr(ingest, "_recover_before_run", lambda _conn: None)
    monkeypatch.setattr(source_aliases, "load", lambda _conn: source_aliases.evidence())
    monkeypatch.setattr(
        ingest.maintenance, "load_sep_cursor",
        lambda _conn: SimpleNamespace(processed_through=source_day))
    monkeypatch.setattr(
        ingest, "_single_failed_live_candidate",
        lambda _conn: next(candidate_reads))

    def reconcile(_conn, *, fetch, through, reobserve_equal=False):
        reconcile_calls.append((fetch, through, reobserve_equal))
        return SimpleNamespace(processed_through=source_day)

    monkeypatch.setattr(
        ingest.maintenance, "reconcile_sep_mutations", reconcile)
    monkeypatch.setattr(
        ingest, "_require_failed_owner_cleared", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ingest.feed_store, "latest_visible_session",
        lambda _conn: market_day.isoformat())
    monkeypatch.setattr(
        ingest.feed_store, "latest_session",
        lambda _conn: market_day.isoformat())
    monkeypatch.setattr(
        actions, "active_rows",
        lambda _conn, *, start, end, action_types: [])
    monkeypatch.setattr(
        ingest.identity_refresh, "stable_current_tickers", lambda _fetch: [])
    monkeypatch.setattr(
        ingest.identity_refresh, "assert_candidate_history_safe",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ingest.identity_refresh, "prevalidate_pending_sep_mutations",
        lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        ingest.identity_refresh, "PinnedInitialTickersFetch",
        lambda fetch, _rows: fetch)
    monkeypatch.setattr(
        ingest.source_authority, "StableSharadarFetch",
        lambda fetch, **_kwargs: fetch)
    monkeypatch.setattr(
        ingest.recovery, "extended_overlap_days",
        lambda _conn, overlap: overlap)
    progress = SimpleNamespace(run_id="daily")
    monkeypatch.setattr(
        ingest._impl, "_daily_locked", lambda *_args, **_kwargs: progress)
    monkeypatch.setattr(
        ingest, "_finish_publication_or_refuse", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ingest.sep_reconciliation, "reconcile_next",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ingest, "_reconcile_sep_for_market_target",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ingest.maintenance, "reconcile_actions_if_due",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ingest, "_actions_reconciliation_source", lambda fetch: fetch)
    monkeypatch.setattr(ingest, "_prove_recent_frontier", lambda *_args, **_kwargs: None)

    got = ingest.daily(
        object(), fetch=object(), today=market_day.isoformat())

    assert got is progress
    assert reconcile_calls == [(
        production_fetch, source_day.isoformat(), True)]
    assert identity_reads == [(ingest.sharadar.ACTIONS, {
        "action": "tickerchangeto,tickerchangefrom",
        "date.gte": "1900-01-01",
        "date.lte": market_day.isoformat(),
    })] * 2

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from sentinel import identity
from sentinel.cli import feed as feed_cli
from sentinel.cli import main as cli
from sentinel.feed import ingest, manual_daily, source_aliases, store as feed_store

ET = ZoneInfo("America/New_York")


def test_extract_requires_exactly_one_explicit_through():
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid):
        manual_daily.extract_through(["feed-daily"])
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid):
        manual_daily.extract_through([
            "feed-daily", "--through", "2026-08-24",
            "--through=2026-08-24",
        ])
    clean, value = manual_daily.extract_through([
        "--config", "x", "feed-daily", "--through=2026-08-24"])
    assert clean == ["--config", "x", "feed-daily"]
    assert value == "2026-08-24"


def test_latest_fully_closed_session_is_accepted_and_future_is_refused():
    after_close = dt.datetime(2026, 8, 24, 16, 30, tzinfo=ET)
    boundary = manual_daily.validate_through("2026-08-24", now_et=after_close)
    assert boundary.through == "2026-08-24"
    assert boundary.latest_closed == "2026-08-24"
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid, match="latest closed"):
        manual_daily.validate_through("2026-08-25", now_et=after_close)


def test_current_session_before_official_close_is_refused():
    before_close = dt.datetime(2026, 8, 24, 15, 59, tzinfo=ET)
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid, match="latest closed"):
        manual_daily.validate_through("2026-08-24", now_et=before_close)


@pytest.mark.parametrize("value", [
    "2026-08-23",       # Sunday
    "2026-07-04",       # holiday/weekend
    "2026-8-24",        # noncanonical
    "2026-02-30",       # invalid date
])
def test_non_session_or_malformed_boundary_refuses(value):
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid):
        manual_daily.validate_through(
            value, now_et=dt.datetime(2026, 8, 24, 17, 0, tzinfo=ET))


def test_utc_tomorrow_does_not_advance_exchange_session():
    # 20:30 PT is already the next UTC date, but XNYS authority remains Aug 24.
    instant = dt.datetime(2026, 8, 24, 20, 30,
                          tzinfo=ZoneInfo("America/Los_Angeles"))
    boundary = manual_daily.validate_through("2026-08-24", now_et=instant)
    assert boundary.latest_closed == "2026-08-24"
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid):
        manual_daily.validate_through("2026-08-25", now_et=instant)


def test_ingest_daily_has_no_wall_clock_fallback():
    with pytest.raises(ValueError, match="explicit through-session"):
        ingest.daily(object())


def test_ingest_daily_passes_explicit_session_verbatim(monkeypatch):
    observed = {}

    @contextmanager
    def lock(_conn):
        yield

    source = lambda *args, **kwargs: []
    monkeypatch.setattr(ingest, "_authoritative_source", lambda fetch: fetch)
    monkeypatch.setattr(ingest, "_validate_source_before_run", lambda fetch: None)
    monkeypatch.setattr(ingest.feed_store, "corpus_write_lock", lock)
    monkeypatch.setattr(ingest, "_recover_before_run", lambda conn: None)
    monkeypatch.setattr(source_aliases, "load", lambda _conn: source_aliases.evidence())
    monkeypatch.setattr(
        ingest.maintenance, "load_sep_cursor", lambda conn: object())
    monkeypatch.setattr(ingest, "_single_failed_live_candidate", lambda conn: None)
    monkeypatch.setattr(
        ingest.feed_store, "latest_visible_session", lambda conn: "2026-08-21")
    monkeypatch.setattr(
        ingest.recovery, "extended_overlap_days", lambda conn, requested: requested)

    def stable_fetch(fetch, *, after_session=None, sep_update_envelope=None,
                     reference_recovery=False, identity_actions=(),
                     identity_through=None, identity_fetch=None, alias_rejections=None):
        assert identity_actions == ()
        assert identity_fetch is None
        assert alias_rejections == source_aliases.evidence()
        observed["identity_through"] = identity_through
        return fetch

    monkeypatch.setattr(
        ingest.source_authority, 'StableTableFetch',
        stable_fetch)

    def daily_locked(conn, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(run_id="daily-test")

    monkeypatch.setattr(ingest._impl, "_daily_locked", daily_locked)
    monkeypatch.setattr(
        ingest, "_finish_publication_or_refuse", lambda conn, progress: object())
    monkeypatch.setattr(
        ingest.sep_reconciliation, "reconcile_next", lambda conn, **kwargs: None)
    monkeypatch.setattr(
        ingest.maintenance, "reconcile_sep_mutations", lambda conn, **kwargs: None)
    monkeypatch.setattr(
        ingest.maintenance, "reconcile_actions_if_due", lambda conn, **kwargs: None)
    monkeypatch.setattr(ingest, "_prove_recent_frontier", lambda conn, **kwargs: None)

    result = ingest.daily("conn", fetch=source, today="2026-08-24")
    assert result.run_id == "daily-test"
    assert observed["today"] == "2026-08-24"
    assert observed["identity_through"] == "2026-08-24"


def test_cli_missing_boundary_refuses_before_configuration(monkeypatch, capsys):
    called = False

    def forbidden(_cls):
        nonlocal called
        called = True
        raise AssertionError("CLI must not construct DB/vendor state")

    monkeypatch.setattr(
        cli.SentinelConfig, "from_env", classmethod(forbidden))
    assert cli.main(["feed-daily"]) == cli.EXIT_CONFIG
    assert called is False
    assert "requires" in capsys.readouterr().err


def test_cli_prints_and_passes_resolved_session(monkeypatch, capsys):
    from sentinel import rolling_checkpoint, rolling_runtime
    validate = manual_daily.validate_through
    now = dt.datetime(2026, 8, 24, 16, 30, tzinfo=ET)
    monkeypatch.setattr(
        manual_daily, "validate_through", lambda value: validate(value, now_et=now))
    monkeypatch.setattr(
        feed_cli.SentinelConfig,
        "from_env",
        classmethod(lambda cls: SimpleNamespace(database_url="postgresql://test/db")),
    )
    monkeypatch.setattr(
        identity,
        "require_feed_producer_identity",
        lambda: {
            "git_commit": "a" * 40,
            "runtime_image_digest": "sha256:" + "b" * 64,
        },
    )

    conn = object()
    monkeypatch.setattr(feed_store, "connect", lambda _url: nullcontext(conn))
    monkeypatch.setattr(rolling_checkpoint, "read", lambda _conn: SimpleNamespace(
        observation_id="test-shadow", starting_cash="50000"))
    def classify(_conn, **kwargs):
        assert kwargs["unchanged_through"] == "2026-08-24"
        return {"status": "ATTESTED_STRUCTURAL", "latest_session": "2026-08-21"}
    monkeypatch.setattr(rolling_runtime, "classify", classify)
    calls = []
    monkeypatch.setattr(rolling_runtime, "prepare_adjacent",
                        lambda c, *, previous, through, acquisition_deadline:
                        calls.append((c, previous, through)))

    assert cli.main(["feed-daily", "--through", "2026-08-24"]) == 0
    assert calls == [(conn, "2026-08-21", "2026-08-24")]
    assert "through-session 2026-08-24" in capsys.readouterr().out

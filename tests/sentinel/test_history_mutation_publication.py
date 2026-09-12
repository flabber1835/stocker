"""Real publication/SQL proofs for historical economic mutation detection."""
from types import SimpleNamespace

import pytest

from sentinel.core.history import HistoryReconstructionRequired, require_history_compatible
from sentinel.feed import publication, store
from stock_strategy_shared.wealth_core.feed import VendorBar
from tests.support.postgres import _EphemeralPostgres

H, D = "2026-08-10", "2026-08-11"


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    try:
        server.start()
    except Exception as exc:
        pytest.skip(f"ephemeral PostgreSQL unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def conn(pg):
    c = store.connect(pg.sync_dsn)
    with c.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    c.commit()
    store.migrate_schema(c)
    yield c
    c.close()


def bar(**changes):
    values = dict(session=H, security_id="P:AAA", ticker="AAA", raw_close=100,
                  raw_open=99, volume=1000000, split_ratio=1, dividend_per_share=0)
    signal = changes.pop("close_signal", 100)
    values.update(changes)
    return SimpleNamespace(vendor=VendorBar(**values), close_signal=signal)


def base(c, *, actions=()):
    store.write_bars(c, [bar()])
    store.write_actions(c, actions)
    return publication.publish(c, window_start=H, window_end=D)


def publish_run(c, writer):
    writer.finish("success")
    return publication.publish(c, run_id=writer.progress.run_id, window_start=H, window_end=D)


def refuses(prior, current):
    with pytest.raises(HistoryReconstructionRequired, match="RECONSTRUCTION_REQUIRED"):
        require_history_compatible(
            prior_version=prior.version, last_processed_session=D,
            version=current.version, proof=current.evidence["strategy_history"])


@pytest.mark.parametrize("field,value", [
    ("raw_close", 101), ("raw_open", 98), ("volume", 1000001),
    ("split_ratio", 2), ("dividend_per_share", 1), ("close_signal", 101),
])
def test_changed_sep_fields_bind_earliest_history_before_new_publication(conn, field, value):
    prior = base(conn)
    with store.corpus_write_lock(conn):
        run = store.IngestRun(conn, "daily", date_from=H, date_to=D)
        store.write_bars(conn, [bar(**{field: value})], run_id=run.progress.run_id)
        current = publish_run(conn, run)
    assert current.evidence["strategy_history"]["changes"][-1] == [current.version, H]
    refuses(prior, current)


def test_failed_write_reclaimed_unchanged_still_carries_original_mutation(conn):
    prior = base(conn)
    with store.corpus_write_lock(conn):
        failed = store.IngestRun(conn, "daily", date_from=H, date_to=D)
        store.write_bars(conn, [bar(volume=900000)], run_id=failed.progress.run_id)
        failed.finish("failed")
        retry = store.IngestRun(conn, "daily", date_from=H, date_to=D)
        store.write_bars(conn, [bar(volume=900000)], run_id=retry.progress.run_id)
        current = publish_run(conn, retry)
    refuses(prior, current)
    later = publication.publish(conn, window_start=D, window_end=D)
    refuses(prior, later)
    require_history_compatible(prior_version=current.version, last_processed_session=D,
                              version=later.version, proof=later.evidence["strategy_history"])


def test_unchanged_bar_and_forward_extension_do_not_invalidate_prior_state(conn):
    prior = base(conn)
    with store.corpus_write_lock(conn):
        run = store.IngestRun(conn, "daily", date_from=H, date_to="2026-08-12")
        store.write_bars(conn, [bar(), bar(session="2026-08-12")], run_id=run.progress.run_id)
        current = publish_run(conn, run)
    assert current.evidence["strategy_history"]["changes"] == []


@pytest.mark.parametrize("mutation", ["add", "remove", "change"])
def test_terminal_only_generation_cannot_advance_old_path(conn, mutation):
    source = {"ticker": "AAA", "date": H, "action": "delisted", "value": 1}
    prior = base(conn, actions=[] if mutation == "add" else [source])
    new = [] if mutation == "remove" else [{**source, "value": 2} if mutation == "change" else source]
    with store.corpus_write_lock(conn):
        run = store.IngestRun(conn, "actions_reconcile", date_from=H, date_to=D)
        store.write_actions(conn, new, run_id=run.progress.run_id, window_start=H, window_end=D)
        current = publish_run(conn, run)
    refuses(prior, current)


@pytest.mark.parametrize("ticker", ["SPY", "BIL"])
def test_reference_history_restatement_has_the_same_reconstruction_fence(conn, ticker):
    row = {"ticker": ticker, "date": H, "open": 99, "close": 100,
           "closeadj": 100, "closeunadj": 100}
    writer = store.write_spy_total_return if ticker == "SPY" else store.write_defensive_bars
    writer(conn, [row])
    prior = base(conn)
    with store.corpus_write_lock(conn):
        run = store.IngestRun(conn, "daily", date_from=H, date_to=D)
        writer(conn, [{**row, "closeadj": 101}], run_id=run.progress.run_id)
        current = publish_run(conn, run)
    refuses(prior, current)


def test_mutation_footprints_are_append_only_and_schema_proves_trigger_presence(conn):
    from sentinel.feed import runtime_schema
    base(conn)
    with store.corpus_write_lock(conn):
        run = store.IngestRun(conn, "daily", date_from=H, date_to=D)
        store.write_bars(conn, [bar(volume=900000)], run_id=run.progress.run_id)
        publish_run(conn, run)
    with pytest.raises(Exception, match="append-only"):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sentinel_history_mutations")
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("DROP TRIGGER sentinel_record_history_mutation ON sentinel_bars")
    conn.commit()
    with pytest.raises(runtime_schema.FeedSchemaRefused, match="triggers"):
        runtime_schema.require_feed_schema(conn)


def test_upgrade_from_cash_spinoff_semantics_replays_and_preserves_source(conn, monkeypatch):
    from datetime import date
    from sentinel.feed import calendar, corporate_action_authority, ingest, maintenance, sharadar

    start, event, end = "2014-09-22", "2014-10-01", "2014-10-03"
    days = calendar.sessions_in_range(start, end)

    def fetch(table, params=None, **_kwargs):
        lo, hi = (params or {}).get("date.gte", "0000"), (params or {}).get("date.lte", "9999")
        if table == sharadar.ACTIONS:
            return [{"ticker": "ADP", "contraticker": "CDK", "date": event,
                     "action": "spinoffdividend", "value": "10"}] if lo <= event <= hi else []
        if table == sharadar.TICKERS:
            return [{"ticker": "ADP", "permaticker": "P:ADP", "firstpricedate": start,
                     "category": "Domestic Common Stock"}]
        if table == sharadar.SEP:
            return [{"ticker": "ADP", "date": day, "close": 100, "closeunadj": 100,
                     "open": 100, "volume": 1000000, "lastupdated": day}
                    for day in days if lo <= day <= hi]
        return []

    with monkeypatch.context() as legacy:
        legacy.setattr(corporate_action_authority, "DIVIDEND_ACTIONS",
                       corporate_action_authority.DIVIDEND_ACTIONS | {"spinoffdividend"})
        legacy.setattr(maintenance, "reconcile_actions_if_due",
                       maintenance._core.reconcile_actions_if_due)
        ingest.seed(conn, date_from=start, date_to=end, fetch=fetch)
    prior = publication.require_current(conn)
    with store.corpus_write_lock(conn):
        maintenance._core._write_cursor(
            conn, name="sharadar-actions-export-reconcile:v7",
            kind="sharadar-actions-export-reconcile/v7", through=date.fromisoformat(end),
            publication_version=prior.version)
        assert maintenance.load_actions_cursor(conn) is None
        cursor = maintenance.reconcile_actions_if_due(conn, fetch=fetch, through=end)
    assert cursor.kind == "sharadar-actions-export-reconcile/v9"
    with conn.cursor() as cur:
        cur.execute("SELECT dividend_per_share FROM sentinel_bars WHERE session=%s", (event,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT value FROM sentinel_active_actions WHERE action='spinoffdividend'")
        assert cur.fetchone()[0] == 10
    current = publication.require_current(conn)
    assert current.evidence["strategy_history"]["changes"][-1] == [current.version, event]
    with pytest.raises(HistoryReconstructionRequired):
        require_history_compatible(prior_version=prior.version, last_processed_session=end,
                                  version=current.version, proof=current.evidence["strategy_history"])

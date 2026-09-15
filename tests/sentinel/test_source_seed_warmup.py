"""Bounded production cold seed -> 252-session warmup -> daily -> restart.

HTTP delivery, wall clock, receipt secret, producer provenance and the absent
deployment backup marker are synthetic. Source guards, PostgreSQL, loaders,
strategy, transitions and WAL-health guards are real. The private test WAL
archive is not NAS backup media or production restore authority.
"""
import datetime as dt
import json
import sys
import threading
import time
from decimal import Decimal
from types import SimpleNamespace
import uuid

import pytest

from research.sharadar_replay.model import Corpus, Step
from research.sharadar_replay.provider import Provider
from research.sharadar_replay.runtime import simulated_runtime
from sentinel import shadow_runtime
from sentinel.core import production
from sentinel.core.session import SessionState
from sentinel.feed import (
    calendar, ingest, maintenance, operational_source, outage_recovery, progress,
    publication, snapshot_source, source_aliases, store,
)
from sentinel.strategy import production_strategy
from test_concurrent_source_symbols import DAY, source
from tests.support.postgres import _EphemeralPostgres
from tools.sentinel_operational_parity import prove_transition


@pytest.fixture(scope="module", autouse=True)
def warmup_diagnostics():
    stopped = threading.Event()
    main_thread = threading.get_ident()
    started = time.monotonic()

    def report():
        while not stopped.wait(30):
            frame = sys._current_frames().get(main_thread)
            stack = []
            while frame is not None and len(stack) < 8:
                stack.append({"file": frame.f_code.co_filename, "line": frame.f_lineno,
                              "function": frame.f_code.co_name})
                frame = frame.f_back
            del frame
            progress.emit("acceptance_diagnostic", "working",
                          elapsed_ms=int((time.monotonic() - started) * 1000), stack=stack)

    thread = threading.Thread(target=report, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=2)


@pytest.fixture(scope="module")
def seed_backup_policy(tmp_path_factory):
    # The root backup-policy fixture is function-scoped and therefore runs
    # after this module's database seed. Establish the same test filesystem
    # identity before seeding; explicit REQUIRED_V1 remains fully enforced.
    from sentinel import backup_runtime_authority

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(backup_runtime_authority, "POLICY_MARKER",
                      tmp_path_factory.mktemp("seed-policy") / "absent-production-backup-policy")
        yield


@pytest.fixture(scope="module")
def seeded_market(seed_backup_policy, warmup_diagnostics):
    server = _EphemeralPostgres()
    server.start()
    data, _, _ = source()
    sessions = calendar.previous_sessions(DAY, 300)
    ordinary = [dict(data["tickers"][0], ticker=f"T{i}", permaticker=i + 1,
                     firstpricedate=sessions[0], lastpricedate=DAY, relatedtickers="") for i in range(4001)]
    bars = []
    # The real cash-authority membrane requires its retained TRI event inside
    # this date range. Supply both economic legs; never disable that guard.
    tri = dict(data["tickers"][0], ticker="TRI", permaticker=90001000,
               firstpricedate="2026-05-01", lastpricedate="2026-05-04", isdelisted="Y")
    for day, raw, volume in (("2026-05-01", 98.456, 984560), ("2026-05-04", 100., 1000000)):
        bars.append(dict(ticker="TRI", date=day, open=99.5, close=100., closeunadj=raw,
                         volume=volume, lastupdated=day))
    actions = [*data["actions"], *[dict(ticker="TRI", date="2026-05-04", action=kind,
                name="TRI", value=value, contraticker=None, contraname=None)
                for kind, value in (("dividend", 1.36), ("split", .98456))]]
    for index, day in enumerate(sessions):
        for i in range(4001):
            px = (50. + i % 30) * (1.0004 + (i % 30) * .00002) ** index
            bars.append(dict(ticker=f"T{i}", date=day, open=px, close=px, closeunadj=px,
                             volume=2000000 if i < 30 else 1000, lastupdated=day))
        for row in data["tickers"]:
            if day >= row["firstpricedate"]:
                bars.append(dict(next(b for b in data["sep"] if b["ticker"] == row["ticker"]),
                                 date=day, lastupdated=day))
        for ticker, first in (("OCLT", DAY), ("BRTM", "2026-09-10")):
            if day >= first:
                bars.append(dict(next(b for b in data["sep"] if b["ticker"] == ticker), date=day))
    references = [dict(ticker=ticker, date=day, open=100. + index * .05,
                       close=100. + index * .05, closeadj=100. + index * .05,
                       closeunadj=100. + index * .05)
                  for index, day in enumerate(sessions) for ticker in ("SPY", "BIL")]
    # SFP and nullable TICKERS metadata still use real paginated transport;
    # operational SEP uses the production bounded snapshot acquisition.
    provider = Provider(page_size=200000, variation_seed=19)
    provider.advance(Step(name="full_initial_seed", at=dt.datetime(2026, 9, 14, 6, tzinfo=dt.timezone.utc),
        through=dt.date.fromisoformat(DAY), tables={"TICKERS": (*ordinary, *data["tickers"], tri),
        "ACTIONS": tuple(actions), "SEP": tuple(bars), "SFP": tuple(references)},
        expected=Corpus(bars=(), actions=(), identities=(), spy=(), defensive=())))
    del bars
    try:
        server.enable_archive()
        with simulated_runtime(provider, commit="a" * 40):
            with store.connect(server.sync_dsn) as conn:
                store.migrate_schema(conn)
                with progress.phase("acceptance_source_seed", source_rows=len(provider.step.tables["SEP"]),
                                    sessions=len(sessions), securities=len(ordinary),
                                    unit="acquired_sep_source_rows") as count:
                    assert len(provider.step.tables["SEP"]) > 1000000
                    result = outage_recovery.catch_up(conn, target_session=DAY)
                    assert result.mode == "BOUNDED_INITIAL_SEED"
                    published = publication.require_current(conn)
                    seed_run = conn.execute("SELECT status,rows_written FROM feed_ingest_runs WHERE run_id=%s",
                                            (published.run_id,)).fetchone()
                    assert seed_run[0] == "success"
                    count[0] = acquired_sep_source_rows(published.evidence["operational_source"],
                                                       expected_rows=len(provider.step.tables["SEP"]))
                    assert_single_sep_acquisition(provider, start=sessions[0], end=DAY)
                    assert published.evidence["operational_source"]["window"] == [sessions[0], DAY]
                    assert maintenance.load_sep_cursor(conn).price_window == (sessions[0], DAY)
                aliases = source_aliases.load(conn)
                assert {r["permaticker"] for r in aliases["records"]} == {"6401005", "6399775"}
                assert conn.execute("SELECT COUNT(DISTINCT session) FROM sentinel_bars").fetchone()[0] == 300
                assert publication.require_current(conn).window_end == DAY
            controller, strategy = production_strategy()
            yield SimpleNamespace(server=server, provider=provider, sessions=sessions,
                                  controller=controller, strategy=strategy)
    finally:
        server.stop()


def assert_single_sep_acquisition(provider, *, start, end, since=0):
    downloads = [row for row in provider.transcript[since:]
                 if row["channel"] == "download" and row["download_table"] == "SEP"]
    expected = [{"date.gte": lo, "date.lte": hi, "qopts.export": "true"}
                for lo, hi in operational_source._months(start, end)]
    assert [row["download_query"] for row in downloads] == expected
    assert not any(row.get("table") == "SEP" and row["channel"] == "pages"
                   for row in provider.transcript[since:])


def acquired_sep_source_rows(source, *, expected_rows):
    rows = sum(file["source_rows"] for file in source["files"] if file["table"] == "SEP")
    assert rows == expected_rows
    return rows


@pytest.mark.parametrize("fault", [None, "duplicate", "missing", "count"])
def test_source_seed_progress_counts_acquired_sep_receipts(fault):
    files = [{"table": "SEP", "source_rows": 3}, {"table": "ACTIONS", "source_rows": 19},
             {"table": "TICKERS", "source_rows": 33}, {"table": "SEP", "source_rows": 2}]
    if fault == "duplicate":
        files.append(files[-1])
    elif fault == "missing":
        files.pop()
    elif fault == "count":
        files[0]["source_rows"] += 1
    if fault is None:
        assert acquired_sep_source_rows({"files": files}, expected_rows=5) == 5
    else:
        with pytest.raises(AssertionError):
            acquired_sep_source_rows({"files": files}, expected_rows=5)


@pytest.mark.parametrize("fault", [None, "duplicate", "missing", "unbounded", "pages", "wrong_export"])
def test_single_sep_acquisition_contract(fault):
    downloads = [{"channel": "download", "download_table": "SEP", "download_query": query}
                 for query in ({"date.gte": "2026-08-01", "date.lte": "2026-08-31", "qopts.export": "true"},
                               {"date.gte": "2026-09-01", "date.lte": DAY, "qopts.export": "true"})]
    if fault == "duplicate":
        downloads.append(downloads[-1])
    elif fault == "missing":
        downloads.pop()
    elif fault == "unbounded":
        downloads[0]["download_query"]["date.gte"] = "2000-01-01"
    elif fault == "pages":
        downloads.append({"channel": "pages", "table": "SEP"})
    elif fault == "wrong_export":
        downloads[0]["download_query"].pop("qopts.export")
    provider = SimpleNamespace(transcript=downloads)
    if fault is None:
        assert_single_sep_acquisition(provider, start="2026-08-01", end=DAY)
    else:
        with pytest.raises(AssertionError):
            assert_single_sep_acquisition(provider, start="2026-08-01", end=DAY)


def fresh(conn, market):
    with progress.phase("acceptance_canonical_warmup", sessions=252,
                        unit="security_feature_series") as count:
        with publication.pinned(conn, commit=False) as held:
            state, identity = shadow_runtime._fresh_seed(conn, first_session=DAY,
                starting_cash=Decimal("1000000"), controller_config=market.controller,
                strategy_identity=market.strategy, publication_version=held.version)
        count[0] = len(state.feed["series"])
    conn.rollback()
    return state, identity


def test_canonical_warmup_progress_names_its_counter_unit(monkeypatch, capsys):
    from contextlib import nullcontext

    state = SimpleNamespace(feed={"series": {"1": {}, "2": {}}})
    identity = {"session_count": 252}
    monkeypatch.setattr(shadow_runtime, "_fresh_seed", lambda *args, **kwargs: (state, identity))
    monkeypatch.setattr(publication, "pinned", lambda *args, **kwargs: nullcontext(SimpleNamespace(version=1)))
    conn = SimpleNamespace(rollback=lambda: None)
    assert fresh(conn, SimpleNamespace(controller={}, strategy={})) == (state, identity)
    events = [json.loads(line.split("=", 1)[1]) for line in capsys.readouterr().err.splitlines()
              if line.startswith("SENTINEL_FEED_PROGRESS=")]
    events = [event for event in events if event["stage"] == "acceptance_canonical_warmup"]
    assert [event["status"] for event in events] == ["started", "completed"]
    assert all(event["unit"] == "security_feature_series" and event["sessions"] == 252
               for event in events)
    assert events[-1]["rows"] == 2
    assert events[-1]["elapsed_ms"] >= 0


def stage_unpublished_session(conn, table, day, *, security_id=None):
    """Model interrupted restatement without disabling append-only triggers.

    All writes, including the candidate run, are rolled back by each test.
    """
    assert table in {"sentinel_bars", "sentinel_spy_total_return"}
    run_id = str(uuid.uuid4())
    conn.execute("INSERT INTO feed_ingest_runs(run_id,kind,status) VALUES (%s,'seed','running')", (run_id,))
    condition = " AND security_id=%s" if security_id is not None else ""
    params = (run_id, day, security_id) if security_id is not None else (run_id, day)
    conn.execute(f"UPDATE {table} SET last_written_run_id=%s WHERE session=%s" + condition, params)


def test_full_seed_current_champion_warmup_and_restart(seeded_market):
    market = seeded_market
    with store.connect(market.server.sync_dsn) as conn:
        state, identity = fresh(conn, market)
        assert identity["session_count"] == 252
        assert identity["last_warmup_session"] == market.sessions[-2]
        assert state.last_processed_session is None
        assert state.pending == []
        assert not state.wealth_core["episodes"]
        assert state.wealth_core["cash"] == 1000000
        assert not state.ledger["events"]
        assert not state.ledger["receivables"]
        assert state.controller_session_history == []
        assert state.concordance_witness_origin == production.CONCORDANCE_WITNESS_PROSPECTIVE
        restored = SessionState.from_dict(json.loads(json.dumps(state.to_dict())))
        assert restored.to_dict() == state.to_dict()
        with publication.pinned(conn, commit=False) as held:
            published = production.load_published_session(
                conn, DAY, known_feed_security_ids=tuple(state.feed["series"]))
            result = prove_transition(state, published, held=held,
                                      controller=market.controller, strategy=market.strategy)
            assert all(result["checks"].values())
        conn.rollback()
    with store.connect(market.server.sync_dsn) as conn:
        restarted, after = fresh(conn, market)
        assert restarted.state_hash == state.state_hash
        assert after == identity


@pytest.mark.parametrize("index", [0, 120, 251])
def test_missing_warmup_session_refuses_at_the_real_database_loader(seeded_market, index):
    market = seeded_market
    warmup_sessions = market.sessions[-253:-1]
    with store.connect(market.server.sync_dsn) as conn:
        stage_unpublished_session(conn, "sentinel_bars", warmup_sessions[index])
        with pytest.raises(shadow_runtime.ShadowRuntimeRefused, match="warm-up is incomplete"):
            shadow_runtime._load_warmup_material(conn, first_session=DAY, strategy_identity=market.strategy)
        conn.rollback()


@pytest.mark.parametrize("index", [0, 120, 251])
def test_missing_spy_history_refuses_current_champion_warmup(seeded_market, index):
    market = seeded_market
    warmup_sessions = market.sessions[-253:-1]
    with store.connect(market.server.sync_dsn) as conn:
        stage_unpublished_session(conn, "sentinel_spy_total_return", warmup_sessions[index])
        with pytest.raises(shadow_runtime.ShadowRuntimeRefused, match="exact dated SPY history"):
            shadow_runtime._load_warmup_material(
                conn, first_session=DAY, strategy_identity=market.strategy)
        conn.rollback()


def test_initial_warmup_does_not_include_the_first_decision_session(seeded_market):
    market = seeded_market
    with store.connect(market.server.sync_dsn) as conn:
        before, witness_before = fresh(conn, market)
        # Keep the published frontier and its source-identity horizon intact.
        # Only the first decision day's price availability changes.
        stage_unpublished_session(conn, "sentinel_bars", DAY, security_id="1")
        window, prospective, witness_after = shadow_runtime._load_warmup_material(
            conn, first_session=DAY, strategy_identity=market.strategy)
        assert witness_before == witness_after
        conn.rollback()


def test_published_daily_update_preserves_alias_evidence_and_restart_transition(seeded_market):
    market, provider = seeded_market, seeded_market.provider
    tomorrow = calendar.next_session(DAY)
    tables = dict(provider.step.tables)
    prices = [dict(row, date=tomorrow, lastupdated="2026-09-14")
              for row in tables["SEP"] if row["date"] == DAY]
    references = [dict(row, date=tomorrow) for row in tables["SFP"] if row["date"] == DAY]
    tables["SEP"] = (*tables["SEP"], *prices)
    tables["SFP"] = (*tables["SFP"], *references)
    tables["TICKERS"] = tuple(dict(row, lastpricedate=tomorrow) if row["isdelisted"] == "N" else row
                              for row in tables["TICKERS"])
    with store.connect(market.server.sync_dsn) as conn:
        state, identity = fresh(conn, market)
        with publication.pinned(conn, commit=False):
            first = production.load_published_session(
                conn, DAY, known_feed_security_ids=tuple(state.feed["series"]))
            from sentinel.core.kernel import advance_session
            advanced = advance_session(state, first, controller_config=market.controller,
                                       strategy_identity=market.strategy)
        conn.rollback()
        provider.advance(provider.step.model_copy(update={"name": "first_daily_after_warmup",
            "at": dt.datetime(2026, 9, 15, 6, tzinfo=dt.timezone.utc),
            "through": dt.date.fromisoformat(tomorrow), "tables": tables}))
        observations = len(provider.transcript)
        ingest.daily(conn, today=tomorrow, fetch=snapshot_source.fetch_table)
        start, end = operational_source.price_window(tomorrow)
        assert_single_sep_acquisition(provider, start=start, end=end, since=observations)
        assert len(source_aliases.load(conn)["records"]) == 2
        with publication.pinned(conn, commit=False) as held:
            daily = production.load_published_session(
                conn, tomorrow, known_feed_security_ids=tuple(advanced.feed["series"]))
            proof = prove_transition(advanced, daily, held=held,
                                    controller=market.controller, strategy=market.strategy)
            assert all(proof["checks"].values())
        conn.rollback()

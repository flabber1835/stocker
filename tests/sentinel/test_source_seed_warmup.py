"""Full production source seed -> 252-session warmup -> daily -> restart.

HTTP delivery, wall clock, receipt secret, producer provenance and the absent
deployment backup marker are synthetic. Source guards, PostgreSQL, loaders,
strategy and transitions are real.
"""
import datetime as dt
import json
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
from sentinel.feed import calendar, ingest, publication, snapshot_source, source_aliases, store
from sentinel.strategy import production_strategy
from test_concurrent_source_symbols import DAY, source
from tests.support.postgres import _EphemeralPostgres
from tools.sentinel_operational_parity import prove_transition


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
def seeded_market(seed_backup_policy):
    server = _EphemeralPostgres()
    server.start()
    data, _, _ = source()
    sessions = calendar.previous_sessions(DAY, 253)
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
    # Keep multiple source pages while avoiding re-sorting/hashing the entire
    # million-row synthetic provider once per tiny simulated HTTP page.
    provider = Provider(page_size=200000, variation_seed=19)
    provider.advance(Step(name="full_initial_seed", at=dt.datetime(2026, 9, 14, 6, tzinfo=dt.timezone.utc),
        through=dt.date.fromisoformat(DAY), tables={"TICKERS": (*ordinary, *data["tickers"], tri),
        "ACTIONS": tuple(actions), "SEP": tuple(bars), "SFP": tuple(references)},
        expected=Corpus(bars=(), actions=(), identities=(), spy=(), defensive=())))
    del bars
    try:
        with simulated_runtime(provider, commit="a" * 40):
            with store.connect(server.sync_dsn) as conn:
                store.migrate_schema(conn)
                result = ingest.seed(conn, date_from=sessions[0], date_to=DAY,
                                     fetch=snapshot_source.fetch_table)
                assert conn.execute("SELECT status FROM feed_ingest_runs WHERE run_id=%s",
                                    (result.run_id,)).fetchone() == ("success",)
                aliases = source_aliases.load(conn)
                assert {r["permaticker"] for r in aliases["records"]} == {"6401005", "6399775"}
                assert conn.execute("SELECT COUNT(DISTINCT session) FROM sentinel_bars").fetchone()[0] == 253
                assert publication.require_current(conn).window_end == DAY
            controller, strategy = production_strategy()
            yield SimpleNamespace(server=server, provider=provider, sessions=sessions,
                                  controller=controller, strategy=strategy)
    finally:
        server.stop()


def fresh(conn, market):
    with publication.pinned(conn, commit=False) as held:
        state, identity = shadow_runtime._fresh_seed(conn, first_session=DAY,
            starting_cash=Decimal("1000000"), controller_config=market.controller,
            strategy_identity=market.strategy, publication_version=held.version)
    conn.rollback()
    return state, identity


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
    with store.connect(market.server.sync_dsn) as conn:
        stage_unpublished_session(conn, "sentinel_bars", market.sessions[index])
        with pytest.raises(shadow_runtime.ShadowRuntimeRefused, match="warm-up is incomplete"):
            shadow_runtime._load_warmup_material(conn, first_session=DAY, strategy_identity=market.strategy)
        conn.rollback()


@pytest.mark.parametrize("index", [0, 120, 251])
def test_missing_spy_history_refuses_current_champion_warmup(seeded_market, index):
    market = seeded_market
    with store.connect(market.server.sync_dsn) as conn:
        stage_unpublished_session(conn, "sentinel_spy_total_return", market.sessions[index])
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
        ingest.daily(conn, today=tomorrow, fetch=snapshot_source.fetch_table)
        assert len(source_aliases.load(conn)["records"]) == 2
        with publication.pinned(conn, commit=False) as held:
            daily = production.load_published_session(
                conn, tomorrow, known_feed_security_ids=tuple(advanced.feed["series"]))
            proof = prove_transition(advanced, daily, held=held,
                                    controller=market.controller, strategy=market.strategy)
            assert all(proof["checks"].values())
        conn.rollback()

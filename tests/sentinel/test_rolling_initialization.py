"""Real source/publication/canonical-state cold start, rollback and restart."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sentinel import rolling_initialization as init, rolling_checkpoint as cp, schema
from sentinel import shadow_observation as shadow, shadow_runtime
from sentinel.feed import operational_snapshot as op, publication, store
from sentinel.feed.rolling_contract import FormationWindow, digest, canonical_json
from sentinel.strategy import production_strategy
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401

NOW = datetime(2026, 9, 15, 4, tzinfo=timezone.utc)
OBS = "rolling-first"


def test_composed_input_keeps_spy_equity_and_bil_domains_separate():
    from stock_strategy_shared.wealth_core.feed import VendorBar
    from sentinel.core.loader import CorpusWindow
    from sentinel.core.rolling_inputs import ColdStartInputs
    from sentinel.core.session import DefensiveBar
    from sentinel.feed.rolling_contract import CanonicalBenchmark

    axis = ("2026-09-11", "2026-09-14")
    benchmarks = tuple(CanonicalBenchmark(
        session=day, spy_total_return=600. + i,
        bil_open_signal=91. + i, bil_close_signal=101. + i,
        bil_close_adjusted=121. + i, bil_close_unadjusted=111. + i,
    ) for i, day in enumerate(axis))
    equity = VendorBar(session=axis[-1], security_id="1", ticker="AAA",
                       raw_open=19., raw_close=20., volume=1_000_000., signal_close=10.)
    material = ColdStartInputs(
        snapshot_id="a" * 64, reference_sha256="b" * 64, session=axis[-1],
        warmup=CorpusWindow([], {}, {}), bars=(equity,), meta={}, sectors={},
        benchmarks=benchmarks, terminal_events=(), spinoff_distributions=())
    pub = SimpleNamespace(version=7, evidence={"strategy_history": {}})

    published = init._published(material, pub)
    assert published.spy_closeadj == (600., 601.)
    assert published.spy_sessions == published.spy_expected_sessions == axis
    assert published.bars == (equity,)
    assert published.bars[0].signal_close == 10.
    assert published.bars[0].raw_open == 19.
    assert published.bars[0].raw_close == 20.
    assert published.defensive_previous_bar == DefensiveBar(
        axis[0], "SENTINEL:BIL", "BIL", 91., 101., 121., 111.)
    assert published.defensive_bar == DefensiveBar(
        axis[1], "SENTINEL:BIL", "BIL", 92., 102., 122., 112.)
    committed = shadow._published_input_value(published)
    assert committed["spy_closeadj"] == [600., 601.]
    assert committed["bars"][0]["signal_close"] == 10.
    assert committed["bars"][0]["raw_close"] == 20.
    assert committed["defensive_previous_bar"]["close_adjusted"] == 121.
    assert committed["defensive_bar"]["close_adjusted"] == 122.


@pytest.fixture
def ready(conn, operational_source, monkeypatch):
    schema.ensure_schema(conn)
    data = operational_source
    template = deepcopy(data["TICKERS"][0])
    axis = [str(day) for day in FormationWindow.through('2026-09-14').sessions]
    template['firstpricedate'] = axis[0]
    symbols = ["AAA", "BBB", *[f"S{i:02}" for i in range(3, 26)]]
    data["TICKERS"] = [{**template, "ticker": symbol, "permaticker": str(i)}
                       for i, symbol in enumerate(symbols, 1)]
    data["SEP"] = [{"ticker": symbol, "date": day, "open": str(50 + i * .2 + j * .03),
                    "close": str(50 + i * .2 + j * .03), "closeunadj": str((50 + i * .2 + j * .03) * 2),
                    "volume": "1000000", "lastupdated": "2026-09-15"}
                   for i, day in enumerate(axis) for j, symbol in enumerate(symbols)]
    data['SFP'] = [{**data['SFP'][0], 'date': day, 'ticker': ticker, 'closeadj': str(600 + i)}
                   for i, day in enumerate(axis) for ticker in ('SPY', 'BIL')]
    controller, strategy = production_strategy()
    job = op.enqueue(conn, strategy_sha256=digest(strategy), dependencies_sha256=digest("fixture"))
    conn.commit()
    binding = op.prepare(conn, job)
    with op.pinned(conn) as (pub, _):
        subject = shadow_runtime._data_publication_subject_sha256(pub, pub.window_end)
    # Deployment certification is an external authority, not manufactured by
    # this integration test. All acquisition, input and state code is real.
    monkeypatch.setattr(shadow_runtime, "_validated_runtime_identity", lambda **kwargs: {
        "schema": "test-reviewed-runtime/1", "validated_data_publication_sha256": subject})
    monkeypatch.setattr(init, "_now", lambda conn: NOW)
    return binding


def start(conn, **kwargs):
    return init.initialize(conn, observation_id=kwargs.get("observation_id", OBS),
                           starting_cash=kwargs.get("starting_cash", 100_000))


def resume(conn, **kwargs):
    return init.resume(conn, observation_id=kwargs.get("observation_id", OBS),
                       starting_cash=kwargs.get("starting_cash", 100_000))


def test_real_publication_forms_historical_book_and_atomic_checkpoint(conn, ready):
    result = start(conn)
    state = result.state
    assert state.wealth_core['episodes'] and state.ledger['events']
    assert result.strategy_nav == '100000' and result.strategy_cumulative_return == '0'
    assert state.ledger['events'][0]['session'] < '2026-09-14'
    assert state.last_processed_session == "2026-09-14"
    assert state.data_version == ready["data_version"]
    assert result.verification == shadow.CANDIDATE and result.shadow_verdict == shadow.NOT_DEPLOYABLE
    checkpoint = cp.read(conn)
    assert checkpoint.status == "FORMED_START_COMMITTED"
    assert checkpoint.state_sha256 == state.state_hash
    assert checkpoint.snapshot == ready
    assert checkpoint.warmup_input_identity['schema'] == 'sentinel.formed-origin/1'
    assert checkpoint.warmup_input_identity['formation_count'] == 126
    assert checkpoint.pitr["schema"] == publication.PITR_EVIDENCE_SCHEMA
    assert len(cp.lineage_names(conn)) == 3
    for table in ("sentinel_execution_plans", "sentinel_commands", "sentinel_fills", "sentinel_bars"):
        assert conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
    conn.commit()
    assert resume(conn).state.state_hash == state.state_hash


def test_restart_does_not_read_prices_warm_or_transition_again(conn, ready, monkeypatch):
    original = start(conn)
    def forbidden(*args, **kwargs):
        pytest.fail("restart must not reconstruct the original cold start")
    monkeypatch.setattr(init, "cold_start_inputs", forbidden)
    monkeypatch.setattr(init, "warm_session_state", forbidden)
    monkeypatch.setattr(shadow, "advance_state", forbidden)
    monkeypatch.setattr(op, "published", forbidden)
    # The time of a read-only historical checkpoint check grants no new order.
    monkeypatch.setattr(init, "_now", lambda conn: datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert resume(conn).state.state_hash == original.state.state_hash
    assert start(conn).state.state_hash == original.state.state_hash


def test_restart_survives_absent_original_price_payloads(conn, ready):
    original = start(conn)
    # Simulate restored/archive-only input payloads in this disposable database.
    # Production retention and immutable-table permissions are not changed.
    conn.execute("SET LOCAL session_replication_role=replica")
    conn.execute("DELETE FROM sentinel_snapshot_bars")
    conn.execute("DELETE FROM sentinel_snapshot_benchmarks")
    conn.commit()
    assert resume(conn).state.state_hash == original.state.state_hash


def test_restart_reads_a_consistent_read_only_snapshot(conn, ready, monkeypatch):
    start(conn)
    original = cp.restore
    def restore(conn, *args, **kwargs):
        assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        assert conn.execute("SHOW transaction_isolation").fetchone()[0] == "repeatable read"
        return original(conn, *args, **kwargs)
    monkeypatch.setattr(cp, "restore", restore)
    assert resume(conn).state.wealth_core['episodes']


@pytest.mark.parametrize("name,value", [("starting_cash", 200_000), ("observation_id", "other")])
def test_checkpoint_cannot_change_capital_or_observation(conn, ready, name, value):
    start(conn)
    with pytest.raises(cp.RollingColdStartRefused, match="CONFIG_CHANGED"):
        resume(conn, **{name: value})


@pytest.mark.parametrize("name", ["catchup", "catchup:resume_commitment:v1",
    "shadow-observation:v1:other:genesis", "shadow-segment:v3:other:00000001", "unexpected-book"])
def test_partial_state_is_never_interpreted_as_fresh(conn, ready, name):
    payload = {"wealth_core": {}} if name == "unexpected-book" else {"partial": True}
    conn.execute("INSERT INTO sentinel_processed_sessions (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)",
                 (name, "2026-09-11", canonical_json(payload)))
    conn.commit()
    with pytest.raises(cp.RollingColdStartRefused, match="EXISTING_STRATEGY_STATE"):
        start(conn)
    assert cp.read(conn) is None
    assert conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s", (name,)).fetchone()[0] == payload


def test_existing_execution_history_prevents_new_genesis(conn, ready):
    conn.execute("INSERT INTO sentinel_fills (broker_order_id,fill_key,quantity,price) VALUES ('old','old',1,100)")
    conn.commit()
    with pytest.raises(cp.RollingColdStartRefused, match="EXISTING_EXECUTION_HISTORY"):
        start(conn)
    assert cp.lineage_names(conn) == set()
    assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone()[0] == 1


def test_orphaned_strategy_evidence_prevents_new_genesis(conn, ready):
    conn.execute("INSERT INTO sentinel_trial_strategy_evidence "
                 "(session,data_version,state_sha256,strategy_identity,decision,evidence,payload_sha256) "
                 "VALUES ('2026-09-11',1,%s,'{}','{}','{}',%s)", ("a" * 64, "b" * 64))
    conn.commit()
    with pytest.raises(cp.RollingColdStartRefused, match="EXISTING_STRATEGY_EVIDENCE"):
        start(conn)
    assert cp.lineage_names(conn) == set()
    assert conn.execute("SELECT COUNT(*) FROM sentinel_trial_strategy_evidence").fetchone()[0] == 1


@pytest.mark.parametrize("boundary", ["genesis", "session", "checkpoint"])
def test_failed_first_state_leaves_no_partial_seed(conn, ready, monkeypatch, boundary):
    target, method = ((cp, "write") if boundary == "checkpoint" else
                      (shadow.PostgresShadowObservationStore, "append_genesis" if boundary == "genesis" else "append"))
    original = getattr(target, method)
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected cold-start failure")
    monkeypatch.setattr(target, method, fail)
    with pytest.raises((RuntimeError, shadow.ShadowObservationRefused), match="injected|append failed|could not be persisted"):
        start(conn)
    assert cp.lineage_names(conn) == set()
    monkeypatch.setattr(target, method, original)
    assert start(conn).state.wealth_core['episodes']


def test_lost_ack_recovers_exact_checkpoint(conn, ready, monkeypatch):
    original = cp.write
    def lost_ack(conn, checkpoint):
        original(conn, checkpoint)
        conn.commit()
        raise ConnectionError("commit reply lost")
    monkeypatch.setattr(cp, "write", lost_ack)
    with pytest.raises(ConnectionError, match="reply lost"):
        start(conn)
    expected = cp.read(conn).state_sha256
    conn.commit()
    assert resume(conn).state.state_hash == expected


@pytest.mark.parametrize("field", ["input_value", "state_sha256", "starting_cash"])
def test_checkpoint_authentication_detects_valid_json_mutations(conn, ready, field):
    start(conn)
    raw = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s", (cp.CURSOR,)).fetchone()[0]
    raw["checkpoint"][field] = {} if field == "input_value" else "1" * 64
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s",
                 (canonical_json(raw), cp.CURSOR))
    conn.commit()
    with pytest.raises(cp.RollingColdStartRefused, match="AUTHENTICATION_FAILED"):
        resume(conn)


def test_changed_state_cannot_be_self_rehashed_into_checkpoint(conn, ready):
    start(conn)
    key = f"shadow-observation:v1:{OBS}:session:2026-09-14"
    raw = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s", (key,)).fetchone()[0]
    raw["state"]["wealth_core"]["cash"] = 99_000
    raw["state_sha256"] = digest(raw["state"])
    raw["record_sha256"] = digest({k: v for k, v in raw.items() if k != "record_sha256"})
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s", (canonical_json(raw), key))
    conn.commit()
    with pytest.raises(cp.RollingColdStartRefused, match="RECORD_BINDING_CHANGED"):
        resume(conn)


def test_missing_checkpoint_does_not_reseed_existing_state(conn, ready):
    result = start(conn)
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s", (cp.CURSOR,))
    conn.commit()
    with pytest.raises(cp.RollingColdStartRefused, match="EXISTING_STRATEGY_STATE"):
        start(conn)
    assert len(cp.lineage_names(conn)) == 2


def test_extra_shadow_lineage_prevents_checkpoint_admission(conn, ready):
    start(conn)
    conn.execute("INSERT INTO sentinel_processed_sessions (cursor_name,session,state) VALUES (%s,%s,'{}')",
                 ("shadow-observation:v1:other:genesis", "2026-09-14"))
    conn.commit()
    with pytest.raises(cp.RollingColdStartRefused, match="LINEAGE_CHANGED"):
        resume(conn)


def test_transition_that_crosses_next_open_is_not_committed(conn, ready, monkeypatch):
    original = shadow.ShadowObserver.observe
    def late(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(init, "_now", lambda conn: datetime(2026, 9, 15, 13, 30, tzinfo=timezone.utc))
        return result
    monkeypatch.setattr(shadow.ShadowObserver, "observe", late)
    with pytest.raises(cp.RollingColdStartRefused, match="MISSED_OPEN"):
        start(conn)
    assert cp.lineage_names(conn) == set()


def test_final_checkpoint_write_cannot_extend_opening_deadline(conn, ready, monkeypatch):
    original = cp.write
    def late(conn, checkpoint):
        original(conn, checkpoint)
        monkeypatch.setattr(init, "_now", lambda conn: datetime(2026, 9, 15, 13, 30, tzinfo=timezone.utc))
    monkeypatch.setattr(cp, "write", late)
    with pytest.raises(cp.RollingColdStartRefused, match="MISSED_OPEN"):
        start(conn)
    assert cp.lineage_names(conn) == set()


def test_unreviewed_publication_cannot_seed(conn, ready, monkeypatch):
    monkeypatch.setattr(shadow_runtime, "_validated_runtime_identity", lambda **kwargs: {
        "validated_data_publication_sha256": "0" * 64})
    with pytest.raises(cp.RollingColdStartRefused, match="UNREVIEWED_GENESIS_PUBLICATION"):
        start(conn)
    assert cp.lineage_names(conn) == set()


def test_acquisition_bound_to_another_strategy_cannot_seed(conn, ready, monkeypatch):
    controller, strategy = production_strategy()
    monkeypatch.setattr(shadow_runtime, "_strategy", lambda: (controller, {**strategy, "other": "profile"}))
    with pytest.raises(cp.RollingColdStartRefused, match="ACQUISITION_STRATEGY_CHANGED"):
        start(conn)
    assert cp.lineage_names(conn) == set()


def test_backup_gate_precedes_any_genesis_write(conn, ready, monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("backup unavailable")
    monkeypatch.setattr(init.backup_runtime_authority, "require", refuse)
    with pytest.raises(RuntimeError, match="backup unavailable"):
        start(conn)
    assert cp.lineage_names(conn) == set()


def test_common_writer_lock_excludes_another_initializer(conn, ready):
    from sentinel.execution import journal
    other = store.connect(conn.info.dsn)
    try:
        with journal.writer_lock(other):
            with pytest.raises(journal.WriterLockUnavailable):
                start(conn)
        assert cp.lineage_names(conn) == set()
    finally:
        other.close()


def test_failed_publication_does_not_burn_a_committed_version(conn, operational_source, monkeypatch):
    original = publication._insert_receipted_publication
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("write rolled back")
    monkeypatch.setattr(publication, "_insert_receipted_publication", fail)
    job = op.enqueue(conn, strategy_sha256=digest("fixture"), dependencies_sha256=digest("fixture"))
    conn.commit()
    with pytest.raises(RuntimeError, match="rolled back"):
        op.prepare(conn, job)
    monkeypatch.setattr(publication, "_insert_receipted_publication", original)
    job = op.enqueue(conn, strategy_sha256=digest("fixture"), dependencies_sha256=digest("fixture"))
    conn.commit()
    assert op.prepare(conn, job)["data_version"] == 1

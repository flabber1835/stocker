"""Real snapshot/shadow inputs at the simulated paper execution membrane."""
import asyncio
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import binding, dual_plan_authority, rolling_runtime, rolling_initialization, paper
from sentinel import automation_runtime
from sentinel.execution import feed_inputs, feed_actions, journal, certification, target_reprojection
from sentinel.execution.feed_cash import SnapshotCashInputs
from sentinel.execution.contract import BrokerAccountIdentity, CapabilityNotCertified
from sentinel.execution.opening_prices import parse_bars
from sentinel.execution.simulator import SimulatedBroker
from sentinel.config import DEFAULT_BASE_URL
from sentinel.feed import calendar, publication, operational_snapshot as snapshots, rolling_store, universe
from sentinel.feed.rolling_contract import digest
from sentinel.paper import preparation, inspection, execution, recovery, validation
from sentinel.authority import load_rollout_state
from sentinel.strategy import production_strategy
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS, NOW

DAY = "2026-09-14"


def approve(conn):
    return rolling_runtime.advance(conn, through=DAY, observation_id=OBS, starting_cash=100000)


def test_readers_bind_snapshot_raw_marks_and_leave_legacy_readers_closed(conn, published):
    with pytest.raises(publication.CorpusIncoherent, match="VERSIONED_READER"):
        publication.require_current(conn)
    with feed_inputs.pinned(conn, commit=False) as pub:
        assert feed_inputs.frontier(conn, pub) == DAY
        assert feed_inputs.readiness(conn, today=NOW.isoformat()).ready
        marks, symbols = feed_inputs.marks(conn, pub, session=DAY, security_ids=["1"], tickers={})
        row = conn.execute("SELECT close_signal,close_unadjusted FROM sentinel_snapshot_bars "
                           "WHERE candidate_id=%s AND session=%s AND security_id='1'",
                           (published["candidate_id"], DAY)).fetchone()
        assert marks["1"] == Decimal(str(row[1])) and marks["1"] != Decimal(str(row[0]))
        assert symbols == {"1": "AAA", "SENTINEL:BIL": "BIL"}
        assert marks["SENTINEL:BIL"] == Decimal("51")
        with pytest.raises(feed_inputs.ExecutionInputsRefused, match="CURRENT_DECISION"):
            feed_inputs.marks(conn, pub, session="2026-09-11", security_ids=["1"], tickers={})
        with pytest.raises(feed_inputs.ExecutionInputsRefused, match="MARKS_MISSING"):
            feed_inputs.marks(conn, pub, session=DAY, security_ids=["missing"], tickers={})
    conn.rollback()


def test_next_open_resolver_is_bounded_and_historical_dates_do_not_borrow_extension(conn, published):
    pub = feed_inputs.require_current(conn)
    resolve = paper.build_security_resolver(conn, "2026-09-15")
    assert resolve("AAA") == "1" and resolve("BIL") == "SENTINEL:BIL"
    assert resolve("AAA", DAY) == "1"
    assert resolve("AAA", "2026-09-16") is None
    assert resolve("missing") is None
    opening = feed_inputs.opening_resolver(conn, session="2026-09-15")
    assert opening.ticker_for_security("1", "2026-09-15") == "AAA"
    assert opening.resolve("AAA", "2026-09-15") == "1"
    with pytest.raises(feed_inputs.ExecutionInputsRefused, match="BEYOND_NEXT_SESSION"):
        feed_inputs.opening_resolver(conn, session="2026-09-16")
    with pytest.raises(feed_inputs.ExecutionInputsRefused, match="BEYOND_NEXT_SESSION"):
        feed_inputs.resolver(conn, pub, session="2026-09-16")


def test_action_reader_requires_retained_predecessor_and_never_reads_legacy_rows(conn, published):
    refs = feed_inputs.references(conn, feed_inputs.require_current(conn))
    lookup = feed_actions.action_lookup(conn, start=date(2026, 9, 11), end=date(2026, 9, 15))
    assert lookup("1") == Decimal(1) and lookup("SENTINEL:BIL") == Decimal(1)
    assert lookup.material_events_for(security_ids=["1"]) == ()
    with pytest.raises(feed_inputs.ExecutionInputsRefused, match="HISTORY_UNAVAILABLE"):
        feed_actions.action_lookup(conn, start=refs.manifest.window.start - timedelta(days=5), end=date.fromisoformat(DAY))


def test_corrupt_receipt_cannot_trigger_a_permissive_reader_fallback(monkeypatch):
    def refuse(*_):
        raise publication.CorpusIncoherent("receipt authentication failed")
    monkeypatch.setattr(publication, "require_current", refuse)
    monkeypatch.setattr(publication, "current", refuse)
    monkeypatch.setattr(snapshots, "_current", lambda *_: pytest.fail("integrity refusal bypassed"))
    with pytest.raises(publication.CorpusIncoherent, match="authentication"):
        feed_inputs.require_current(object())
    with pytest.raises(publication.CorpusIncoherent, match="authentication"):
        feed_inputs.opening_resolver(object(), session="2026-09-15")


def test_legacy_opening_identity_uses_the_publication_reader(monkeypatch):
    conn, published, expected = object(), object(), object()
    monkeypatch.setattr(feed_inputs, "current", lambda c: published)
    monkeypatch.setattr(feed_inputs, "is_rolling", lambda p: p is not published)
    seen = []

    def legacy(c, *, execution_session):
        seen.append((c, execution_session))
        return expected

    monkeypatch.setattr(universe, "load_resolver", legacy)
    assert feed_inputs.opening_resolver(conn, session="2026-09-15") is expected
    assert seen == [(conn, "2026-09-15")]


@pytest.fixture
def gateway(conn, published, monkeypatch, request):
    result = approve(conn)
    broker_name = getattr(request, "param", "sim")
    bound = binding.bind(conn, deployment_id="rolling-paper-test", broker=broker_name, broker_account_id="paper-fixture")
    conn.execute("INSERT INTO sentinel_system_certificates "
                 "(certificate_sha256,manifest_bytes,manifest,allowed_rollout_modes) "
                 "VALUES (%s,'{}'::bytea,'{}'::jsonb,'[\"CONTROLLER\"]'::jsonb)", ("a" * 64,))
    conn.execute("UPDATE sentinel_rollout_state SET mode='CONTROLLER',version=2,certificate_sha256=%s WHERE id=1",
                 ("a" * 64,))
    conn.execute("INSERT INTO sentinel_rollout_events (version,from_mode,to_mode,certificate_sha256,reason) "
                 "VALUES (2,'PINNED_1_00','CONTROLLER',%s,'test certificate fixture')", ("a" * 64,))
    conn.commit()
    broker = SimulatedBroker(account=BrokerAccountIdentity(broker_name, "paper-fixture"),
                             equity=Decimal("250000"), cash=Decimal("250000"))
    monkeypatch.setattr(inspection, "require_certified", certification.require_certified_adapter)
    # Offline signed certificate issuance is covered by the existing authority
    # suite. The gateway, reconciliation, sizing, persistence and restart are real.
    for owner in (preparation, execution, recovery, validation):
        monkeypatch.setattr(owner, "require_current_authority", lambda *_a, **_k: SimpleNamespace(
            certificate_sha256="a" * 64, authorization_mode="PAPER_OBSERVATION_ONLY"))
    monkeypatch.setattr(preparation.system_identity, "rehearsal_identity", lambda: {})
    monkeypatch.setattr(preparation, "_guard_broker", lambda **kwargs: kwargs["broker"])
    return result, bound, broker


def prepare(conn, broker, **overrides):
    values = dict(conn=conn, broker=broker, through=DAY, expected_account="paper-fixture",
        dual_shadow_observation_id=OBS, dual_shadow_starting_cash=100000, now_et=NOW, base_url=DEFAULT_BASE_URL)
    values.update(overrides)
    return asyncio.run(paper.prepare_paper_plan(**values))


@pytest.mark.parametrize("opening_capability", [False, True])
@pytest.mark.parametrize("gateway", ["alpaca"], indirect=True)
def test_real_paper_preparation_and_restart_reuse_only_verified_rolling_shadow(
        conn, gateway, operational_source, monkeypatch, opening_capability):
    shadow, bound, broker = gateway
    monkeypatch.setattr(preparation, "_fresh_warmed_state", lambda *_a, **_k: pytest.fail("second strategy book"))
    monkeypatch.setattr(preparation.catchup, "resume_state", lambda *_: pytest.fail("legacy strategy read"))
    first = prepare(conn, broker)
    assert first.sessions_replayed == first.warmup_sessions == 0
    assert first.state_fingerprint == shadow.state.state_hash
    assert first.plan.account_nav == Decimal("250000")
    proof = dual_plan_authority.rederive_plan(conn, plan=first.plan, binding=bound,
        rollout_state=load_rollout_state(conn), expected_shadow_result=shadow)
    assert proof["verdict"] == "MATCH"
    conn.rollback()
    assert prepare(conn, broker).plan.to_dict() == first.plan.to_dict()
    assert paper.current_paper_plan(conn, dual_shadow_observation_id=OBS,
                                   dual_shadow_starting_cash=100000)["plan"]["plan_id"] == first.plan.plan_id
    assert conn.execute("SELECT COUNT(*) FROM sentinel_processed_sessions WHERE cursor_name='catchup'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sentinel_commands").fetchone()[0] == 0

    # Certificate-free execution retains real opening sizing and durable retry
    # identity. Only broker-delivered opening bars are simulated here.
    from sentinel.execution.guarded import AutomationExecutionGrant
    assert first.plan.opening_intents
    monkeypatch.setattr(execution, "_guard_broker", lambda **kwargs: kwargs["broker"])
    grant = AutomationExecutionGrant("EXECUTE", "rolling-test-cycle", 1, "test", 1,
        "paper-fixture", bound.takeover_epoch, "CONTROLLER", 2, "a" * 64)
    monkeypatch.setattr(execution, "_validate_automation_grant", lambda *_: (None, SimpleNamespace(
        plan_id=first.plan.plan_id, plan_fingerprint=first.plan.fingerprint())))
    opened, _ = calendar.session_window(first.plan.effective_session)
    opening_reads = []

    async def opening_prices(*, session, instruments):
        opening_reads.append(dict(instruments))
        payload = {"bars": {item.symbol: [
            {"t": opened.isoformat(), "o": "100", "v": 10}]
            for item in instruments.values()}, "next_page_token": None}
        return parse_bars(payload, session=session, instruments=instruments,
                          observed_at=opened + timedelta(minutes=1))

    broker.capabilities = replace(broker.capabilities,
                                  regular_session_open_prices=opening_capability)
    monkeypatch.setattr(broker, "opening_prices", opening_prices)
    monkeypatch.setattr(universe, "load_resolver",
                        lambda *_a, **_k: pytest.fail("legacy opening identity read"))

    def execute(seconds):
        return asyncio.run(paper.execute_automated_paper_plan(
            conn=conn, broker=broker, base_url=DEFAULT_BASE_URL,
            grant=grant, automation_config_sha256="b" * 64,
            today=opened + timedelta(seconds=seconds),
            dual_shadow_observation_id=OBS, dual_shadow_starting_cash=100000))

    if not opening_capability:
        with pytest.raises(CapabilityNotCertified, match="regular_session_open_prices"):
            execute(60)
        assert opening_reads == []
        assert conn.execute("SELECT COUNT(*) FROM sentinel_commands").fetchone()[0] == 0
        return

    result = execute(60)
    assert result.session.submitted
    projection = target_reprojection.load_projection(conn, plan_id=first.plan.plan_id)
    assert projection.opening_sizing["mode"] == "V5_OPEN_WHOLE_SHARES"
    assert len(opening_reads) == 1
    assert {command.security_id: command.quantity for command in result.session.submitted} == {
        sid: quantity for sid, quantity in projection.target_basket.items() if quantity > 0}
    for command in result.session.submitted:
        broker.fill(command.client_key)
    retry = execute(90)
    assert retry.session.submitted == ()
    assert target_reprojection.load_projection(conn, plan_id=first.plan.plan_id) == projection
    assert len(opening_reads) == 1
    assert len(journal.load_commands(conn, bound.identity, plan_id=first.plan.plan_id)) == len(result.session.submitted)
    assert paper.current_paper_plan(conn, dual_shadow_observation_id=OBS,
        dual_shadow_starting_cash=100000)["plan"]["plan_id"] == first.plan.plan_id

    # Forward paper preparation does not need a certified historical close.
    # Continue through real publication, shadow transition and reconciliation.
    from tests.sentinel.test_rolling_daily import refresh
    # Durable succeeded-cycle evidence exercises the legacy finalization
    # branch too; merely preparing a second plan would not reach that gate.
    _, decision_close = calendar.session_window(DAY)
    _, execution_close = calendar.session_window(first.plan.effective_session)
    conn.execute("INSERT INTO sentinel_automation_cycles (cycle_id,state,decision_session,"
        "effective_session,deployment_id,broker,broker_account_id,takeover_epoch,"
        "control_generation,certificate_sha256,rollout_mode,rollout_version,config_sha256,"
        "decision_close_at,prepare_at,execution_open_at,execute_at,execution_close_at,plan_id) "
        "VALUES ('rolling-test-cycle','SUCCEEDED',%s,%s,'rolling-paper-test','alpaca',"
        "'paper-fixture',%s,1,%s,'CONTROLLER',2,%s,%s,%s,%s,%s,%s,%s)",
        (DAY, first.plan.effective_session, bound.takeover_epoch, "a" * 64, "b" * 64,
         decision_close, NOW, opened, opened + timedelta(seconds=60), execution_close, first.plan.plan_id))
    conn.commit()
    broker.capabilities = replace(broker.capabilities, account_close_valuation=False,
                                  recent_fill_history=False)
    monkeypatch.setattr(preparation, "_finalize_due_succeeded_cycle_or_refuse",
                        lambda *a, **k: pytest.fail("historical certification blocked forward paper"))
    refresh(conn, operational_source, monkeypatch)
    next_day = "2026-09-15"
    advanced = rolling_runtime.advance(conn, through=next_day, observation_id=OBS, starting_cash=100000)
    next_plan = prepare(conn, broker, through=next_day, now_et=NOW + timedelta(days=1))
    assert next_plan.plan.plan_id != first.plan.plan_id
    assert next_plan.state_fingerprint == advanced.state.state_hash
    assert prepare(conn, broker, through=next_day, now_et=NOW + timedelta(days=1)).plan == next_plan.plan
    assert len(journal.load_commands(conn, bound.identity, plan_id=first.plan.plan_id)) == len(result.session.submitted)
    assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sentinel_processed_sessions "
                        "WHERE cursor_name LIKE 'paper-entitlement-gap:v1:%'").fetchone()[0] == 1
    broker.cash -= Decimal(10)
    with pytest.raises(paper.PaperActivationRefused, match="cash.*not explained"):
        prepare(conn, broker, through=next_day, now_et=NOW + timedelta(days=1))


def test_rolling_preparation_refuses_non_shadow_mode_before_broker_read(conn, gateway, monkeypatch):
    _, _, broker = gateway
    monkeypatch.setattr(broker, "observe", lambda: pytest.fail("unapproved broker read"))
    with pytest.raises(feed_inputs.ExecutionInputsRefused, match="REQUIRES_VERIFIED_SHADOW"):
        prepare(conn, broker, dual_shadow_observation_id=None, dual_shadow_starting_cash=None)


def test_candidate_only_shadow_cannot_become_a_paper_plan(conn, gateway, monkeypatch):
    _, _, broker = gateway
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name LIKE 'shadow-rolling-runtime:%'")
    conn.commit()
    monkeypatch.setattr(broker, "observe", lambda: pytest.fail("candidate reached broker"))
    with pytest.raises(paper.PaperActivationRefused, match="ATTESTATION_REQUIRED"):
        prepare(conn, broker)
    assert journal.latest_plan(conn) is None


def test_automation_refresh_consumes_current_shadow_without_acquisition(conn, published, monkeypatch):
    approve(conn)
    class Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    runtime = object.__new__(automation_runtime.ProductionAutomation)
    runtime._dual_run_enabled = True
    runtime._shadow_observation_id, runtime._shadow_starting_cash = OBS, 100000
    runtime.connect = lambda: Borrowed()
    runtime._assert_cycle_authority = lambda *_a, **_k: (SimpleNamespace(decision_session=date.fromisoformat(DAY)), None)
    result = asyncio.run(runtime.refresh(SimpleNamespace()))
    assert result.already_published and result.diagnostic["scope"] == "ROLLING_VERIFIED_SHADOW"
    runtime._fenced_data_next_wake = None
    runtime._fenced_data_poll_seconds = 300
    runtime.automation_config = SimpleNamespace(alert_max_attempts=3)
    monkeypatch.setattr(automation_runtime.schedule, "for_clock",
        lambda *_: SimpleNamespace(decision_session=date.fromisoformat(DAY)))
    monkeypatch.setattr(automation_runtime.ingest, "daily", lambda *_a, **_k: pytest.fail("paper acquisition"))
    monkeypatch.setattr(rolling_runtime, "advance", lambda *_a, **_k: pytest.fail("paper advanced shadow"))
    assert asyncio.run(runtime._fenced_data_wake(conn)) is not None


def test_fresh_broker_guard_rechecks_snapshot_receipt_after_read(conn, gateway):
    import psycopg
    from sentinel.execution.authority_gate import build_fresh_execution_guard
    from sentinel.execution.guarded import PaperPreparationGrant, BrokerOperation
    seen = []
    def certificate(conn, **kwargs):
        seen.append(kwargs["current_publication_version"])
        return SimpleNamespace(certificate_sha256="a" * 64)
    guard = build_fresh_execution_guard(connection_factory=lambda: psycopg.connect(conn.info.dsn),
        paper_base_url=DEFAULT_BASE_URL, runtime_identity=lambda: {},
        strategy_identity=lambda: production_strategy()[1], authority_check=certificate,
        validate_grant=lambda fresh, grant, operation, result: validation._validate_broker_grant(
            fresh, grant, operation, result, now_provider=lambda: NOW,
            strategy_provider=lambda: production_strategy()[1]))
    grant = PaperPreparationGrant("paper-fixture", date.fromisoformat(DAY))
    asyncio.run(guard.before_read(grant, BrokerOperation.OBSERVE))
    assert seen == [1]
    conn.execute("SET LOCAL session_replication_role=replica")
    conn.execute("UPDATE sentinel_publication_validation_receipts SET receipt_hmac_sha256=%s", ("0" * 64,))
    conn.commit()
    with pytest.raises(publication.CorpusIncoherent):
        asyncio.run(guard.after_read(grant, BrokerOperation.OBSERVE, None))


def test_snapshot_dividend_inputs_reuse_entitlement_domains(conn, operational_source):
    from sentinel.trial import _expected_effective_equity_dividends, _expected_defensive_dividends
    data = operational_source
    data["ACTIONS"].extend([dict(ticker=ticker, date=DAY, action="dividend", name="fixture",
        value="1", contraticker=None, contraname=None) for ticker in ("AAA", "BIL")])
    _, strategy = production_strategy()
    job = snapshots.enqueue(conn, strategy_sha256=digest(strategy), dependencies_sha256=digest("cash fixture"))
    conn.commit()
    snapshots.prepare(conn, job)
    source = SnapshotCashInputs(conn, feed_inputs.require_current(conn))
    assert source.days(date.fromisoformat(DAY), date.fromisoformat(DAY)) == [DAY]
    with pytest.raises(feed_inputs.ExecutionInputsRefused, match="DIVIDEND_HISTORY_UNAVAILABLE"):
        source.days(source.refs.manifest.window.start - timedelta(days=1), date.fromisoformat(DAY))
    expected = _expected_effective_equity_dividends(conn, date.fromisoformat(DAY), {"1": Decimal(10)}, [], source=source)
    assert expected[0]["per_share"] == "2.0" and Decimal(expected[0]["amount"]) == Decimal(20)
    bil = _expected_defensive_dividends(conn, date.fromisoformat(DAY), {"SENTINEL:BIL": Decimal(10)}, [], source=source)
    assert Decimal(bil[0]["amount"]) == Decimal(10)


def test_snapshot_actions_preserve_scalar_and_material_reconciliation_policy(conn, operational_source):
    data = operational_source
    for row in data["SEP"]:
        if row["ticker"] == "AAA" and row["date"] == DAY:
            row["closeunadj"] = "50"
    for row in data["SFP"]:
        if row["ticker"] == "BIL" and row["date"] == DAY:
            row["closeunadj"] = "25.5"
    data["ACTIONS"].extend([dict(ticker=ticker, date=DAY, action=action, name="fixture",
        value=value, contraticker=None, contraname=None) for ticker, action, value in
        (("AAA", "split", "2"), ("BIL", "split", "2"), ("BBB", "reorganization", None))])
    _, strategy = production_strategy()
    job = snapshots.enqueue(conn, strategy_sha256=digest(strategy), dependencies_sha256=digest("action fixture"))
    conn.commit()
    snapshots.prepare(conn, job)
    lookup = feed_actions.action_lookup(conn, start=date(2026, 9, 11), end=date(2026, 9, 14))
    assert lookup("1") == Decimal(2)
    assert lookup("SENTINEL:BIL") == Decimal(2)
    assert len(lookup.scalar_evidence_for(["1", "SENTINEL:BIL"])) == 2
    assert len(lookup.material_events_for(security_ids=["2"], symbols=["BBB"])) == 1
    assert lookup("1", since=date(2026, 9, 14)) == Decimal(1)


@pytest.mark.parametrize("defect", ["delisted", "competing", "successor"])
def test_next_open_identity_never_extends_a_delisted_or_reused_symbol(conn, operational_source, defect):
    data = operational_source
    if defect == "delisted":
        data["TICKERS"][0]["isdelisted"] = "Y"
    else:
        data["TICKERS"].append({**data["TICKERS"][0],
            "permaticker": "999" if defect == "competing" else "1",
            "ticker": "AAA" if defect == "competing" else "NEW",
            "firstpricedate": "2026-09-15", "lastpricedate": "2026-09-15"})
    _, strategy = production_strategy()
    job = snapshots.enqueue(conn, strategy_sha256=digest(strategy), dependencies_sha256=digest("identity fixture"))
    conn.commit()
    snapshots.prepare(conn, job)
    resolve = paper.build_security_resolver(conn, "2026-09-15")
    assert resolve("AAA", DAY) == "1"
    assert resolve("AAA") is None
    opening = feed_inputs.opening_resolver(conn, session="2026-09-15")
    assert opening.ticker_for_security("1", "2026-09-15") == (
        "NEW" if defect == "successor" else None)

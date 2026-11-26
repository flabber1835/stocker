"""Recovery must bind live execution to the verified share and asset identities."""
import asyncio
from contextlib import nullcontext
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import automation_runtime as A
from sentinel import binding, dual_plan_authority, dual_reconciliation, handover, informational_paper_mirror, schema
from sentinel.authority import RolloutMode, RolloutState
from sentinel.core.decision import DEFENSIVE_SECURITY_ID as BIL, build_execution_plan
from sentinel.execution import (
    broker_cash, executor, feed_inputs, fractional_sizing, held_targets, journal, preopen_authority,
    reconcile, target_reprojection,
)
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerInstrument, BrokerObservation, BrokerOrder, BrokerPosition, Completeness, Side)
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.states import CommandState as S
from sentinel.feed import calendar
from sentinel.paper import recovery as P
from sentinel.paper import targets
from sentinel.paper.model import PaperActivationRefused
from tests.sentinel import test_automation_runtime as t
from tests.sentinel.test_fractional_flow import DollarBroker, fractional_environment
from tests.sentinel.test_issue_183_alpaca_hardening import adapter
from tests.sentinel.test_market_day_execution import DEPLOYMENT, wrapper
from tests.sentinel.test_production_decision import _account, _episode, _observation, _position, _publication, _state
from tests.sentinel.test_order_terms_schema import database, pg
from tests.v5.test_opening import base, case
from tests.sentinel.test_limit_day_sizing import references

SID = "SEC-AAA"


class ActivitiesBroker(DollarBroker):
    supports_account_cash_activities = True
    financial_activity_sse = True

    async def account_cash_activities(self, *, after, through, since_event_id=None):
        return broker_cash.BrokerCashActivityBatch((), through, Completeness.COMPLETE)

@pytest.mark.parametrize("ratio,attempted", [(D("0.5"), False), (D(1), False), (D("0.5"), True)])
def test_share_only_recovery_requires_its_verified_next_open_projection(database, pg, monkeypatch, ratio, attempted):
    close = date(2026, 8, 11)
    effective = date.fromisoformat(calendar.next_session(close.isoformat()))
    opened, _ = calendar.session_window(effective)
    core = BrokerInstrument(SID, "AAA", "asset-" + SID)
    bills = BrokerInstrument(BIL, "BIL", "asset-bil")
    conn, m = database, monkeypatch
    schema.ensure_schema(conn)
    bound = binding.bind(conn, deployment_id="isolated", broker="alpaca", broker_account_id="fixture")
    conn.execute("UPDATE sentinel_account_binding SET established_at=%s", (opened - timedelta(days=40),))
    conn.commit()
    owner = BrokerAccountIdentity(bound.broker, bound.broker_account_id)
    snapshots = _state(episodes=[_episode(0, SID, "AAA", 100.)], equity="100000", exposure="0.5")
    snapshots.last_processed_session = close.isoformat()
    snapshots.last_decision["session"] = close.isoformat()
    account = _account(account_id="fixture", equity="100000", cash="40000")
    paper_positions = (_position(SID, "AAA", "100"), _position(BIL, "BIL", "500"))
    close_observation = replace(_observation(positions=paper_positions), account_identity=owner)
    publication = replace(_publication(), window_end=close.isoformat())
    rollout = RolloutState(RolloutMode.CONTROLLER, 1, "a"*64)
    marks = {SID: D(100), BIL: D(100)}
    tickers = {SID: "AAA", BIL: "BIL"}
    plan = build_execution_plan(snapshots, bound, publication, account, close_observation,
        marks, tickers, close, effective, rollout_state=rollout, fractional_sizing=True).plan
    assert plan.target_basket == {SID: D(50), BIL: D(500)} and not plan.opening_intents
    journal.save_plan(conn, plan)
    baseline = held_targets.build_basis(conn, previous=None, state=snapshots, binding=bound, rollout=rollout)
    assert not baseline.get("purchase_budgets")
    verified = SimpleNamespace(state=snapshots, record_sha256="a"*64, runtime_authority_sha256="b"*64)
    authority = dual_plan_authority.build_authority(plan=plan, shadow_result=verified,
        publication=publication, account_snapshot=account, observation=close_observation,
        marks=marks, tickers=tickers, held_share_targets=baseline,
        market_buy_policy_sha256=MarketBuyPolicy(True).fingerprint())
    dual_plan_authority.record_authority(conn, authority)
    proof = dual_plan_authority.rederive_plan(conn, plan=plan, binding=bound, rollout_state=rollout,
                                             expected_shadow_result=verified)
    assert proof["verdict"] == "MATCH"
    for asset, qty in ((core, D(100)), (bills, D(500))):
        command = Command(CommandIdentity(bound.identity, "prior-plan", asset.security_id, 0),
            asset, Side.BUY, qty, state=S.FILLED, broker_order_id="prior-" + asset.broker_id,
            filled_quantity=qty, filled_average_price=D(100))
        journal.save_command(conn, command)
    conn.execute("UPDATE sentinel_commands SET created_at=%s", (opened - timedelta(days=6),))
    conn.commit()
    empty_actions = reconcile.CorpusActionLookup(start=close - timedelta(days=10), events={})
    coverage = preopen_authority.ShareUnitCoverage.no_event(SID)
    if ratio != 1:
        event = preopen_authority.ShareUnitEvent("reverse-split", "v1", effective, ratio,
                                                canonical_numerator=1, canonical_denominator=2)
        coverage = preopen_authority.ShareUnitCoverage.oriented(SID, (event,))
    preopen_authority.record_authority(conn, preopen_authority.PreOpenShareUnitAuthority(
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(), effective_session=effective,
        provider="offline-fixture", publication_id="preopen-fixture",
        as_of=opened, cutoff_at=opened, complete=True,
        coverage=(coverage, preopen_authority.ShareUnitCoverage.no_event(BIL))))
    if attempted:
        journal.save_command(conn, Command(CommandIdentity(bound.identity, plan.plan_id, SID, 0),
            core, Side.SELL, D(25), state=S.REJECTED))
    inner = ActivitiesBroker(account=owner, equity=D(100000), cash=D(40000))
    inner.now = opened + timedelta(seconds=65)
    inner.seed_position(core, str(D(100) * ratio))
    inner.seed_position(bills, "500")
    async def original_cash_boundary():
        state = await broker_cash.ingest_account_cash(conn, broker_adapter=inner, broker=bound.broker,
            account_id=bound.broker_account_id, through=opened - timedelta(hours=15))
        return broker_cash.record_plan_baseline(conn, plan_id=plan.plan_id, decision_session=close,
                                               activity_state=state)
    with journal.writer_lock(conn, recovery_only=True):
        cash_proof = asyncio.run(original_cash_boundary())
        conn.commit()
    assert cash_proof.activity_identity_authoritative and not cash_proof.activity_membership

    cfg = t.config()
    context = t.context(cfg, state=t.CycleState.RECONCILING, plan=plan)
    cycle = context.cycle.model_copy(update={**bound.identity.to_dict(),
        "decision_session": close, "effective_session": effective})
    context = context.model_copy(update={"cycle": cycle})
    runtime = t.production(cfg)
    runtime._dual_run_enabled = True
    runtime._shadow_observation_id = "offline-fixture"
    runtime._shadow_starting_cash = D(100000)
    t.install_runtime_seams(m, runtime, conn, context, inner)
    m.setattr(runtime, "connect", lambda: psycopg.connect(pg.sync_dsn))
    m.setattr(A, "require_observation_integrity", lambda _: None)
    m.setattr(A.schema, "require_runtime_schema", lambda _: None)
    m.setattr(A, "_now_utc", lambda: cycle.execute_at + timedelta(seconds=5))
    m.setattr(A.feed_inputs, "require_current", lambda *_a: SimpleNamespace(version=7))
    m.setattr(A.feed_inputs, "frontier", lambda *_a: close.isoformat())
    m.setattr(runtime, "_require_dual_plan_shadow_match", lambda *_a, **_k:
        {"sizing_authority_sha256": proof["authority_sha256"],
         "shadow_record_sha256": proof["shadow_record_sha256"]})
    m.setattr(informational_paper_mirror, "require_transport_permitted", lambda *_a, **_k: None)
    def unstamped(*_a, **_k):
        raise informational_paper_mirror.InformationalPaperMirrorUnstamped("fixture crash before projection")
    m.setattr(informational_paper_mirror, "require_pending_for_plan", unstamped)
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return inner.now if tz is None else inner.now.astimezone(tz)

    m.setattr(P, "datetime", FixedClock)
    m.setattr(P, "_require_certified_paper_broker", lambda *a, **k: None)
    m.setattr(handover, "assert_no_legacy_path", lambda _: bound)
    m.setattr(P, "load_rollout_state", lambda _: rollout)
    m.setattr(P, "_default_paper_strategy", lambda: (None, snapshots.strategy_identity))
    m.setattr(P.system_identity, "rehearsal_identity", lambda: {})
    m.setattr(P.feed_inputs, "require_shadow_mode", lambda *a, **k: None)
    m.setattr(P.feed_inputs, "is_rolling", lambda _: False)
    m.setattr(P.feed_inputs, "coherent", lambda _: None)
    m.setattr(P.feed_inputs, "pinned", lambda *a, **k: nullcontext(publication))
    m.setattr(P, "require_current_authority", lambda *a, **k:
              SimpleNamespace(certificate_sha256=t.control(cfg).certificate_sha256))
    m.setattr(P, "_validate_automation_grant", lambda *a, **k: (t.control(cfg), cycle))
    real_grant = A._grant
    m.setattr(A, "_grant", lambda context, scope, binding=None:
        replace(real_grant(context, scope, binding=binding), broker_account_id=bound.broker_account_id))
    m.setattr(P, "_guard_broker", lambda **k: k["broker"])
    m.setattr(dual_reconciliation, "verified_shadow_intent", lambda *a, **k: verified)
    m.setattr(informational_paper_mirror, "revalidate_all", lambda *a, **k: None)
    # Daily source ends at close. The retained pre-open authority is the only
    # source of the reverse-split evidence admitted for the effective session.
    m.setattr(P, "_action_lookup", lambda *a, **k: empty_actions)
    m.setattr(P, "_target_action_lookup", lambda *a, **k: empty_actions)
    original_cash_check = P._cash_authority_or_refuse
    cash_checks = []

    def cash_check(*args, **kwargs):
        result = original_cash_check(*args, **kwargs)
        cash_checks.append((result, kwargs["account"].cash))
        return result

    m.setattr(P, "_cash_authority_or_refuse", cash_check)
    if attempted:
        with pytest.raises(A.NonRetryableCallbackRefused, match="projection is absent"):
            asyncio.run(runtime.recover(context))
        assert not cash_checks
    else:
        result = asyncio.run(runtime.recover(context))
        assert result.disposition is t.ExecuteDisposition.READY_TO_EXECUTE
        assert result.failure_code == "OPENING_SIZING_REQUIRED"
        assert D(result.diagnostic["observed"][SID]) == D(100) * ratio
        assert cash_checks == [(False, D(40000))]
    assert target_reprojection.load_projection(conn, plan_id=plan.plan_id) is None


def buy_basket(database):
    schema.ensure_schema(database)
    state, raw = case(entries=2, sale=True)
    plan = replace(raw, **DEPLOYMENT.to_dict())
    plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
    initial = base(state, plan)
    projected = fractional_sizing.resolve(state, plan, initial, references(plan, initial),
        MarketBuyPolicy(True), baseline={"through_event_seq": 0, "commands": [],
            "holdings": {"SEC-X": "10"}}, retained_targets={})
    journal.save_plan(database, plan)
    target_reprojection.record_projection(database, projected)
    return state, plan, projected


def test_plan_preparation_does_not_look_up_native_purchase_instruments(database, monkeypatch):
    from sentinel.execution.alpaca import MalformedBrokerPayload
    from sentinel.paper.model import PaperActivationRefused

    state, plan, projection = buy_basket(database)
    monkeypatch.setattr(feed_inputs, "metadata", lambda _: {})
    broker = DollarBroker()
    lookups = []

    async def resolve_purchase(**kwargs):
        lookups.append(kwargs)
        raise MalformedBrokerPayload("native purchase identity is unmapped")

    monkeypatch.setattr(broker, "resolve_instrument", resolve_purchase)

    async def check():
        observation = await broker.observe()
        mapped = await targets._instrument_map(
            database, broker, state, plan, observation, preparation=True)
        assert not mapped and not lookups
        with pytest.raises(PaperActivationRefused, match="invalid broker instrument identity"):
            await targets._instrument_map(database, broker, state, plan, observation,
                target_basket=projection.target_basket, increase_security_ids={"SEC-AAA"},
                buy_deferrals={})
        assert lookups == [{"security_id": "SEC-AAA", "symbol": "AAA"}]
        assert not any(call.startswith("submit:") for call in broker.calls)

    asyncio.run(check())


@pytest.mark.parametrize("availability", ["initially-inactive", "became-inactive", "conflicting-native-id"])
def test_inactive_buy_defers_only_its_identity_and_keeps_other_transport(database, monkeypatch, availability):
    state, plan, projection = buy_basket(database)
    binding.bind(database, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                 broker_account_id=DEPLOYMENT.broker_account_id)
    native_id = "changed-native-id" if availability == "conflicting-native-id" else "asset-SEC-AAA"
    venue, _ = adapter(routes={"/v2/assets/AAA": {
        "symbol": "AAA", "id": native_id, "status": "inactive", "tradable": False}})
    sold = BrokerInstrument("SEC-X", "X", "asset-SEC-X")
    seed = Command(CommandIdentity(DEPLOYMENT, "predecessor", sold.security_id, 0),
        sold, Side.BUY, D(10), state=S.FILLED, broker_order_id="prior-sale-source",
        filled_quantity=D(10), filled_average_price=D(100))
    journal.save_command(database, seed)
    opened, _ = calendar.session_window(plan.effective_session)
    database.execute("UPDATE sentinel_account_binding SET established_at=%s", (opened,))
    database.commit()
    monkeypatch.setattr(feed_inputs, "metadata", lambda _: {})

    class VenueWithInactivePurchase(DollarBroker):
        aaa_reads = 0

        async def resolve_instrument(self, *, security_id, symbol):
            if symbol == "AAA":
                self.aaa_reads += 1
                if availability == "became-inactive" and self.aaa_reads == 1:
                    return BrokerInstrument(security_id, symbol, native_id)
                return await venue.resolve_instrument(security_id=security_id, symbol=symbol)
            return BrokerInstrument(security_id, symbol, "asset-" + security_id)

        async def submit(self, **kwargs):
            result = await super().submit(**kwargs)
            if kwargs["side"] is Side.SELL and result.state is S.ACKNOWLEDGED:
                self.fill(kwargs["client_key"])
            return result

    async def execute():
        broker = VenueWithInactivePurchase(cash=D(30000))
        broker.now = opened + timedelta(seconds=65)
        broker.seed_position(sold, "10")
        guarded = wrapper(broker)
        observed = await guarded.observe()
        deferred = {}
        mapped = await targets._instrument_map(database, guarded, state, plan, observed,
            target_basket=projection.target_basket, buy_deferrals=deferred)
        expected_refusal = {SID: "BUY_INSTRUMENT_UNAVAILABLE: asset 'AAA' is not active"}
        initially_inactive = availability == "initially-inactive"
        assert deferred == (expected_refusal if initially_inactive else {})
        assert (SID not in mapped) is initially_inactive
        assert mapped[sold.security_id] == sold
        with journal.writer_lock(database, recovery_only=True):
            result = await executor._execute_session_locked(broker=guarded, conn=database,
                deployment=DEPLOYMENT, plan=plan, instruments=mapped, today=plan.effective_session,
                actions=lambda *_: D(1), target_projection=projection, min_increment=D("0.000000001"),
                buy_admission=lambda **_: SimpleNamespace(allowed=True), buy_deferrals=deferred)
        assert [(row.side, row.security_id) for row in result.submitted] == [
            (Side.SELL, "SEC-X"), (Side.BUY, "SEC-BBB")]
        assert result.deferral_reasons == expected_refusal and SID in result.deferred
        hidden_orders = journal.load_commands(database, DEPLOYMENT, plan_id=plan.plan_id, security_id=SID)
        assert tuple(c.state for c in hidden_orders) == (() if initially_inactive else (S.PLANNED,))

    if availability == "conflicting-native-id":
        with pytest.raises(PaperActivationRefused, match="authenticated source identity"):
            asyncio.run(execute())
    else:
        asyncio.run(execute())


@pytest.mark.parametrize("old_state", [S.FILLED, S.ACKNOWLEDGED])
def test_terminal_order_cannot_replace_the_live_position_asset(database, monkeypatch, old_state):
    state, plan, projection = buy_basket(database)
    monkeypatch.setattr(feed_inputs, "metadata", lambda _: {})
    opened, _ = calendar.session_window(plan.effective_session)
    position = BrokerInstrument("SEC-X", "X", "live-asset")
    outdated = BrokerOrder("old-order", None, replace(position, broker_id="retired-asset"),
        Side.SELL, old_state, D(1), filled_quantity=D(1) if old_state is S.FILLED else D(0),
        filled_average_price=D(100) if old_state is S.FILLED else None, submitted_at=opened)
    observation = BrokerObservation(observed_at=opened, orders=(outdated,),
        positions=(BrokerPosition(position, D(10)),))
    deferred = {}
    # Other purchase legs are irrelevant to this test's active share reduction.
    kwargs = dict(target_basket=projection.target_basket, restricted_security_ids={SID, "SEC-BBB"},
                  buy_deferrals=deferred)
    if old_state is S.FILLED:
        mapped = asyncio.run(targets._instrument_map(database, DollarBroker(), state, plan,
                                                     observation, **kwargs))
        assert mapped[position.security_id] == position
    else:
        with pytest.raises(PaperActivationRefused, match="disagree on the native asset"):
            asyncio.run(targets._instrument_map(database, DollarBroker(), state, plan,
                                                 observation, **kwargs))

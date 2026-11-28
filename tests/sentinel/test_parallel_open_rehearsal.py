"""Dispatch and restart regression with prepared strategy inputs and fixture buy admission.

The scheduler, journal, recovery, fractional execution and cash reservations
run here. Elapsed times describe this private fixture with a delayed venue.
"""
import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path
import os
import shutil
import tempfile
from time import monotonic, sleep
from types import SimpleNamespace
from copy import deepcopy
from contextlib import contextmanager

import psycopg
import pytest

from sentinel import authority as certificates
from sentinel import automation_recovery, automation_runtime, backup_runtime_authority as backup, binding, dual_plan_authority, schema
from sentinel.automation import schedule, store
from sentinel.automation.model import ControlBinding, CycleState
from sentinel.automation_resilience import RecoveryAutomationService
from sentinel.core.decision import DEFENSIVE_SECURITY_ID
from sentinel.execution import executor, fractional_progress, fractional_sizing, held_targets, journal, reconcile, target_reprojection
from sentinel.execution.simulator import FaultKind
from sentinel.execution.guarded import OrderEvidenceNotReady
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerAccountIdentity, BrokerInstrument, BrokerAssetRules, Side
from sentinel.execution.fractional_progress import PostingFunds
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.states import CommandState
from sentinel.feed import runtime_schema
from sentinel.paper import market_reservations, reconciliation_evidence, validation
from tests.sentinel.test_automation_service import refresh_result
from tests.sentinel.test_fractional_flow import DollarBroker, fractional_environment
from tests.sentinel.test_limit_day_sizing import references
from tests.sentinel.test_market_day_execution import wrapper
from tests.sentinel import test_signed_authority as signing
from tests.sentinel.test_order_terms_schema import database
from tests.support.postgres import _EphemeralPostgres, _as_pg_user, _find_pg_bin, _run
from tests.support.current_workflow_run import live_lease
from tests.sentinel.test_production_decision import _publication, _episode, _binding, _account, _observation, _position
from tests.v5.test_opening import case


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        server.enable_archive()
        # Use the production archive publisher and a real private physical base.
        # All media and the cluster disappear at fixture teardown.
        with tempfile.TemporaryDirectory(dir=Path(server.datadir).parent) as folder:
            root = Path(folder)
            base_root, wal_root = root/"base", root/"wal"
            for directory in (root, base_root, wal_root):
                directory.mkdir(exist_ok=True)
                if os.geteuid() == 0:
                    shutil.chown(directory, user="postgres", group="postgres")
            for directory in (base_root, wal_root):
                (directory/backup.MARKER).write_text(backup.MARKER_CONTENT+"\n")
            base_name = "base-20261127T000000Z"
            marker = "sentinel-backup-20261127T000000Z-1"
            archive = Path(__file__).resolve().parents[2]/"scripts"/"sentinel-archive-wal.sh"
            pg_bin = Path(_find_pg_bin("pg_ctl")).parent
            with psycopg.connect(server.sync_dsn, autocommit=True) as conn:
                command = f"PATH={pg_bin}:$PATH sh {archive} %p %f {wal_root}"
                conn.execute(psycopg.sql.SQL("ALTER SYSTEM SET archive_command={}").format(psycopg.sql.Literal(command)))
                conn.execute("SELECT pg_reload_conf()")
                system = backup.current_system_id(conn)
                copied = _run(_as_pg_user([str(pg_bin/"pg_basebackup"), "-h", "127.0.0.1", "-p", str(server.port),
                    "-U", server.user, "-D", str(base_root/base_name), "-Fp", "-Xs", "-c", "fast"]))
                assert copied.returncode == 0, copied.stderr
                lsn = conn.execute("SELECT pg_create_restore_point(%s)::text", (marker,)).fetchone()[0]
                wal = conn.execute("SELECT pg_walfile_name(%s::pg_lsn)", (lsn,)).fetchone()[0]
                conn.execute("SELECT pg_switch_wal()")
                until = monotonic()+15
                while not (wal_root/f"cluster-{system}"/(wal+".sha256")).exists():
                    assert monotonic() < until, (Path(server.datadir)/"server.log").read_text()[-1500:]
                    sleep(.1)
            (base_root/base_name/"sentinel-pitr-base-identity").write_text(f"system_identifier={system}\n")
            (base_root/base_name/"sentinel-recovery-marker").write_text(
                f"marker={marker}\nlsn={lsn}\nwal={wal}\nsystem_identifier={system}\n")
            (base_root/f".sentinel-runtime-base-{system}-v1").write_text(
                f"schema=sentinel.runtime-base/1\nsystem_identifier={system}\nbase_backup={base_name}\n")
            with pytest.MonkeyPatch.context() as paths:
                paths.setattr(backup, "BASE_ROOT", str(base_root))
                paths.setattr(backup, "WAL_ROOT", str(wal_root))
                yield server
    finally:
        server.stop()


class WorkerRefused(BaseException):
    """Make an unexpected callback refusal immediately visible to the test."""


class WorkerLost(BaseException):
    """The provider accepted the order and the worker lost its response."""


class DelayedExchange(DollarBroker):
    def __init__(self, deployment, cash, equity, fail_after):
        super().__init__(account=BrokerAccountIdentity(deployment.broker, deployment.broker_account_id),
                         cash=cash, equity=equity)
        self.fail_after = fail_after
        self.accepted = []
        self.due = {}
        self.active = self.peak = 0
        self.slow = os.environ.get("SENTINEL_TEST_SLOW_OPEN") == "1"
        self.first_acceptance = None
        self.peak_working_buys = 0

    async def submit(self, **kwargs):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.35 if self.slow else 0.10)
            result = await super().submit(**kwargs)
            key = kwargs["client_key"]
            assert result.state is CommandState.ACKNOWLEDGED and key not in self.accepted
            self.accepted.append(key)
            self.first_acceptance = self.first_acceptance or monotonic()
            self.peak_working_buys = max(self.peak_working_buys,
                                         sum(o.is_working and o.side is Side.BUY for o in self._snapshot_orders()))
            fill_delay = 42 if kwargs["side"] is Side.SELL else 6
            self.due[key] = monotonic() + (fill_delay if self.slow else 0.35)
            if len(self.accepted) == self.fail_after:
                raise WorkerLost()
            return result
        finally:
            self.active -= 1

    async def find_by_client_key(self, client_key):
        if self.slow:
            await asyncio.sleep(0.86)
        return await super().find_by_client_key(client_key)

    async def observe(self):
        if self.slow:
            await asyncio.sleep(1.1)
        for key, when in tuple(self.due.items()):
            if when <= monotonic():
                self.fill(key)
                del self.due[key]
        snapshot = await super().observe()
        return replace(snapshot, fills=tuple(self._fills), fill_history_complete=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("sales,starting_exposure", [(1, 100), (20, 100), (20, 55)])
async def test_scheduled_open_resumes_funded_basket_after_worker_loss(pg, database, monkeypatch, sales, starting_exposure):
    await _scheduled_rehearsal(pg, database, monkeypatch, sales, starting_exposure)


@pytest.mark.asyncio
@pytest.mark.parametrize("starting_exposure,ending_exposure", [(55, 100), (0, 100), (0, 55)])
@pytest.mark.parametrize("venue_case", ["fractional", "whole", "mixed", "partial", "restart",
                                       "partial_restart", "cancelled_partial", "cancelled_unfilled",
                                       "ignored_cancel", "resting", "resting_partial"])
async def test_twenty_stock_exposure_increase(pg, database, monkeypatch,
                                            starting_exposure, ending_exposure, venue_case):
    await _scheduled_rehearsal(pg, database, monkeypatch, 1, starting_exposure,
                              ending_exposure=ending_exposure, venue_case=venue_case)


def _increase_subject(starting_exposure, ending_exposure):
    """Canonical twenty-stock decision, independent account valuation and sleeve."""
    from stock_strategy_shared.wealth_core.state import PortfolioState
    from sentinel.core import decision
    state, old = case(entries=0, exposure=str(D(ending_exposure)/100))
    portfolio = PortfolioState.from_dict(state.wealth_core)
    portfolio.cash = 0.0
    stocks = {f"SEC-A{i:02d}": f"A{i:02d}" for i in range(20)}
    for slot, (sid, ticker) in enumerate(stocks.items()):
        portfolio.episodes[slot] = _episode(slot, sid, ticker, 50.0)
        portfolio.slots[slot].occupied_by = sid
        state.feed['series'][sid] = dict(security_id=sid, ticker=ticker,
            issuer_id='issuer-'+sid, split_factor=1., sessions=[], session_indices=[],
            signal_closes=[], raw_closes=[], volumes=[])
    state.wealth_core = portfolio.to_dict()
    tickers = {**stocks, DEFENSIVE_SECURITY_ID: 'BIL'}
    held = {sid: D(starting_exposure)/2 for sid in stocks if starting_exposure}
    held[DEFENSIVE_SECURITY_ID] = D(100-starting_exposure)*10
    plan = decision.build_execution_plan(state, _binding(), _publication(),
        _account(equity='100000', cash='0'),
        _observation(positions=[_position(sid, tickers[sid], str(qty)) for sid, qty in held.items()]),
        {sid: D(100) for sid in tickers}, tickers, old.decision_session,
        old.effective_session, rollout_state=certificates.RolloutState(
            mode=certificates.RolloutMode.CONTROLLER, version=1, certificate_sha256='a'*64)).plan
    assert sum(held.values())*100 == D(100000)
    assert sum(qty for sid, qty in held.items() if sid != DEFENSIVE_SECURITY_ID)/1000 == D(starting_exposure)/100
    assert {sid: qty for sid, qty in plan.target_basket.items() if sid != DEFENSIVE_SECURITY_ID} == dict.fromkeys(stocks, D(ending_exposure)/2)
    return state, plan, held


class IncreaseExchange(DelayedExchange):
    supports_owned_order_fills = True

    @property
    def now(self):
        if self.__dict__.get('_sample_instant') is not None:
            return self._sample_instant
        return self._instant_anchor+timedelta(seconds=monotonic()-self._wall_anchor)

    @now.setter
    def now(self, instant):
        self._instant_anchor, self._wall_anchor = instant, monotonic()

    @contextmanager
    def _sample(self):
        # One atomic mock response has one timestamp. Time continues between
        # requests, including exact-order hints and subsequent fill receipts.
        previous = self.__dict__.get('_sample_instant')
        self._sample_instant = self.now
        try:
            yield
        finally:
            self._sample_instant = previous

    def __init__(self, deployment, cash, equity, fail_after, *, venue_case):
        super().__init__(deployment, cash, equity, fail_after)
        self.venue_case = venue_case
        self.partial_keys = set()
        self.partial_seen = False
        self.cancelled_key = None
        self.resting_key = None

    async def asset_rules(self, *, instrument):
        fractional = self.venue_case != 'whole' and (self.venue_case != 'mixed'
            or instrument.security_id == DEFENSIVE_SECURITY_ID
            or int(instrument.symbol[1:]) % 2 == 0)
        return BrokerAssetRules(instrument, self.now, fractional)

    async def submit(self, **kwargs):
        if kwargs['side'] is Side.BUY:
            assert all(order.state is CommandState.FILLED for order in self._orders.values()
                       if order.side is Side.SELL), 'purchase preceded confirmed sleeve proceeds'
        result = await super().submit(**kwargs)
        # Independent requests are acknowledged before any of these fill.
        self.due[kwargs['client_key']] = monotonic()+(.8 if kwargs['side'] is Side.SELL else 1.2)
        return result

    async def _advance(self):
        if self.venue_case in {'resting', 'resting_partial'} and self.resting_key is None:
            for key in tuple(self.due):
                order = self._by_key(key)
                if order.side is Side.BUY and order.instrument.security_id == 'SEC-A00':
                    self.resting_key = key
                    if self.venue_case == 'resting_partial':
                        self.fill(key, str(order.remaining/2))
                    self.due[key] = float('inf')
                    break
        if self.venue_case in {'cancelled_partial', 'cancelled_unfilled', 'ignored_cancel'} and self.cancelled_key is None:
            for key in tuple(self.due):
                order = self._by_key(key)
                if order.side is Side.BUY and order.instrument.security_id == 'SEC-A00':
                    if self.venue_case == 'cancelled_partial':
                        self.fill(key, str(order.remaining/2))
                    if self.venue_case == 'ignored_cancel':
                        self.schedule_cancel(FaultKind.CANCEL_ACCEPTED_BUT_IGNORED)
                    await super().cancel(order.broker_order_id)
                    if self.venue_case != 'ignored_cancel':
                        del self.due[key]
                    self.cancelled_key = key
                    break
        if self.venue_case in {'partial', 'partial_restart'}:
            for key, when in tuple(self.due.items()):
                order = self._by_key(key)
                if key not in self.partial_keys and order.remaining > 0:
                    amount = order.remaining/2
                    if key not in self.dollars:
                        amount = amount.to_integral_value(rounding=ROUND_DOWN)
                    self.fill(key, str(amount))
                    self.partial_keys.add(key)
                    self.partial_seen = True
                    self.due[key] = max(when, monotonic()+.8)
        for key, when in tuple(self.due.items()):
            if when <= monotonic():
                self.fill(key)
                del self.due[key]

    async def account_snapshot(self):
        await self._advance()
        return await super().account_snapshot()

    async def find_by_client_key(self, client_key):
        # A real venue can fill while Sentinel waits on its exact order lookup;
        # filling only in observe() deadlocks the single-sale wake hint fixture.
        await self._advance()
        return await super().find_by_client_key(client_key)

    async def owned_order_fills(self, *, orders, identity, through):
        assert identity == self.account
        requested = {(order.client_key, order.broker_order_id) for order in orders}
        return tuple(fill for fill in self._fills
                     if (fill.client_key, fill.broker_order_id) in requested and fill.filled_at <= through)

    async def opening_prices(self, **kwargs):
        with self._sample():
            return await super().opening_prices(**kwargs)

    async def observe(self):
        await self._advance()
        with self._sample():
            observed = await super().observe()
            # Alpaca's account/order snapshot is not a complete fill ledger.
            # Reconciliation obtains exact executions through owned_order_fills.
            return replace(observed, fills=(), fill_history_complete=False)


@pytest.mark.asyncio
async def test_private_venue_time_and_exact_receipts_advance_without_account_polling():
    deployment = DeploymentIdentity('venue-clock-check', 'alpaca', 'PATEST', 1)
    native = IncreaseExchange(deployment, D(1000), D(1000), None, venue_case='fractional')
    from sentinel.feed import calendar
    from datetime import date
    opened, _ = calendar.session_window(date(2026, 8, 12))
    native.now = opened+timedelta(minutes=1)
    instrument = BrokerInstrument('SEC-A00', 'A00', 'sim-asset-SEC-A00')
    result = await native.submit(client_key='private-clock-order', instrument=instrument,
                                 side=Side.BUY, quantity=None, notional=D(100))
    assert result.state is CommandState.ACKNOWLEDGED
    before = await native.observe()
    assert before.started_at <= before.observed_at and not before.fill_history_complete
    assert before.by_client_key('private-clock-order').filled_quantity == 0
    await asyncio.sleep(1.3)
    exact = await native.find_by_client_key('private-clock-order')
    assert exact.order.state is CommandState.FILLED
    assert native.now-before.observed_at >= timedelta(seconds=1.3)
    assert native.cash == 900
    assert await native.owned_order_fills(orders=(exact.order,), identity=native.account,
                                         through=before.observed_at) == ()
    receipts = await native.owned_order_fills(orders=(exact.order,), identity=native.account,
                                             through=native.now)
    assert len(receipts) == 1 and receipts[0].quantity == 1
    quote = await native.opening_prices(session=native.now.date(), instruments={instrument.security_id: instrument})
    assert quote.quoted_at[instrument.security_id] <= quote.observed_at


async def _scheduled_rehearsal(pg, database, monkeypatch, sales, starting_exposure,
                               *, ending_exposure=None, venue_case=None):
    deployment = DeploymentIdentity("parallel-opening-rehearsal", "alpaca", "PATEST", 1)
    slow = os.environ.get("SENTINEL_TEST_SLOW_OPEN") == "1"
    monkeypatch.setenv("SENTINEL_AUTOMATION_LEASE_SECONDS", "45" if slow else "10")
    monkeypatch.setenv("SENTINEL_AUTOMATION_HEARTBEAT_SECONDS", "2")
    monkeypatch.setenv("SENTINEL_AUTOMATION_RETRY_BASE_SECONDS", "1")
    cfg = automation_runtime.config_from_env()
    state, original = case(entries=2 if sales == 1 else 0, sale=True, exposure="1" if sales == 1 else "0")
    increase_held = None
    if ending_exposure is not None:
        state, original, increase_held = _increase_subject(starting_exposure, ending_exposure)
    state_before = deepcopy(state.to_dict())
    schema.ensure_schema(database)
    runtime_schema.migrate_feed_schema(database)
    binding.bind(database, deployment_id=deployment.deployment_id, broker=deployment.broker,
                 broker_account_id=deployment.broker_account_id)
    timing = schedule.for_decision_session(original.decision_session, cfg)
    document = signing.claims(not_before="2026-08-01T00:00:00Z")
    document["issued_at"] = document["not_before"]
    document["subject"].update(deployment.to_dict())
    document["bindings"]["automation_config_sha256"] = cfg.fingerprint
    payload = signing.signed(document)
    digest = hashlib.sha256(payload).hexdigest()
    certificates.install_signed_certificate(database, certificate_bytes=payload, confirm_sha256=digest,
        context=signing.context(document), now=timing.prepare_at, trust_roots=signing.ROOTS)
    certificates.activate_signed_certificate(database, certificate_sha256=digest, context=signing.context(document),
        reason="private opening rehearsal", now=timing.prepare_at, trust_roots=signing.ROOTS,
        confirm_controller_rollout=True)
    active_cert = signing.context(document, mode=certificates.RolloutMode.CONTROLLER, version=2, certificate_sha=digest)
    held = {"SEC-X": D(10)} if sales == 1 else {f"SEC-X{i:02d}": D(starting_exposure)/10 for i in range(sales)}
    if starting_exposure == 55:
        held[DEFENSIVE_SECURITY_ID] = D(90)
    initial_cash = D("9000") if sales == 1 else D(0)
    nav = initial_cash + sum(qty*D(100) for qty in held.values())
    if sales == 20:
        core_value = sum(qty*D(100) for sid, qty in held.items() if sid != DEFENSIVE_SECURITY_ID)
        assert core_value / nav == D(starting_exposure) / 100
    target = {**dict.fromkeys(held, D(0)), **(
        {"SEC-AAA": D(0), "SEC-BBB": D(0)} if sales == 1 else {DEFENSIVE_SECURITY_ID: D(200)})}
    if increase_held is not None:
        held, initial_cash, nav = increase_held, D(0), D(100000)
        target = original.target_basket
    plan = replace(original, deployment_id=deployment.deployment_id, broker=deployment.broker,
                   broker_account_id=deployment.broker_account_id, takeover_epoch=1, target_basket=target, rollout_version=2,
                   rollout_certificate_sha256=digest, account_nav=nav, account_cash=initial_cash)
    plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
    raw = target_reprojection.project_target(plan, through_session=plan.effective_session, action_multipliers={},
                                             minimum_quantity_increment=D("0.000000001"))
    projection = fractional_sizing.resolve(state, plan, raw, references(plan, raw), MarketBuyPolicy(True),
        baseline={"through_event_seq": 0, "commands": [], "holdings": {k: str(v) for k, v in held.items()}},
        retained_targets={})
    identities = {sid: BrokerInstrument(sid, "BIL" if sid == DEFENSIVE_SECURITY_ID else sid.removeprefix("SEC-"),
                                        "sim-asset-" + sid) for sid in target}
    native = DelayedExchange(deployment, initial_cash, nav, 1 if sales == 1 else 11)
    if increase_held is not None:
        native = IncreaseExchange(deployment, initial_cash, nav,
            11 if venue_case in {'restart', 'partial_restart'} else None, venue_case=venue_case)
    native.now = timing.execute_at
    if increase_held is not None:
        native.now = timing.execute_at-timedelta(seconds=45)
    for sid, qty in held.items():
        native.seed_position(identities[sid], str(qty))
        journal.save_command(database, Command(CommandIdentity(deployment, "seed", sid), identities[sid], Side.BUY,
            qty, filled_quantity=qty, filled_average_price=D(100), state=CommandState.FILLED, broker_order_id="old-"+sid))
    database.execute("UPDATE sentinel_account_binding SET established_at=%s", (timing.execution_open_at,))
    database.commit()
    authority = ControlBinding(**deployment.to_dict(), certificate_sha256=digest, rollout_mode="CONTROLLER",
                               rollout_version=2, config_sha256=cfg.fingerprint)
    store.activate(database, binding=authority, actor="private rehearsal", reason="test")
    store.release_kill(database, expected_binding=authority, actor="private rehearsal", reason="test")

    async def prepare(context):
        basis = held_targets.build_basis(database, previous=None, state=state, binding=deployment,
                                         rollout=certificates.load_rollout_state(database))
        sizing = dual_plan_authority.build_authority(plan=plan, shadow_result=SimpleNamespace(state=state,
            record_sha256="a"*64, runtime_authority_sha256="b"*64), publication=_publication(),
            account_snapshot=await native.account_snapshot(), observation=await native.observe(),
            marks={sid: D(100) for sid in identities}, tickers={sid: asset.symbol for sid, asset in identities.items()},
            held_share_targets=basis, market_buy_policy_sha256=MarketBuyPolicy(True).fingerprint())
        dual_plan_authority.record_authority(database, sizing)
        journal.save_plan(database, plan)
        target_reprojection.record_projection(database, projection)
        return dict(plan_id=plan.plan_id, data_version=str(plan.data_version), publication_fingerprint="a"*64,
                    state_fingerprint="b"*64, plan_fingerprint=plan.fingerprint())

    gateway = object.__new__(automation_recovery.ProductionAutomation)
    gateway.connect = lambda: psycopg.connect(pg.sync_dsn)
    gateway.automation_config = cfg
    async def exchange_clock():
        return SimpleNamespace(timestamp=datetime.now(timezone.utc))
    gateway._broker = lambda *_: SimpleNamespace(market_clock=exchange_clock)
    admissions, outcomes = [], []
    async def execute_owned(ctx):
        gateway._require_backup_for_new_mutation("automation new order execution")
        await gateway._require_external_execution_clock(ctx)
        with gateway.connect() as preflight:
            automation_runtime.require_execution_schemas(preflight)
            automation_runtime.require_observation_integrity(preflight)
            certificate = certificates.load_active_signed_certificate(preflight, context=active_cert,
                now=native.now, trust_roots=signing.ROOTS)
            assert certificate.certificate_sha256 == digest
        with gateway.connect() as conn, journal.writer_lock(conn):
            store.require_leader(conn, ctx.permit)
            assert journal.latest_plan(conn).fingerprint() == plan.fingerprint()
            admissions.append(monotonic())
            settled_result = [None]
            settled_account = [None]
            async def funds(rec):
                assert rec.transport_ready
                checked, account, activity, _, _ = await reconciliation_evidence._settled_account_evidence_bracket(
                    conn=conn, broker=native, binding=binding.require(conn), expected_account=deployment.broker_account_id,
                    deployment=deployment, initial_result=rec, actions=None, dual_mode=True,
                    clock=lambda: native.now, allow_restrictions=True)
                assert activity is None  # No corporate cash postings on the simulated account.
                settled_result[0] = checked
                settled_account[0] = account
                return PostingFunds(account.cash, account.buying_power, D(0), D(0))

            def reserve(commands, rec, posting_funds):
                market_reservations.reserve(conn, commands, plan=plan, projection=projection,
                    deployment=deployment, reconciliation=rec, funds=posting_funds, activity=None)

            def reserved_keys(rec):
                return market_reservations.remaining_keys(conn, basis=market_reservations.load(conn, plan),
                    plan=plan, projection=projection, deployment=deployment, reconciliation=rec)

            async def check(*, account, **kw):
                basis = market_reservations.load(conn, plan)
                if basis is None or kw['client_key'] not in basis['members']:
                    # Match the singleton path in paper.execution: consume the
                    # complete bracket from sizing and recheck account balances.
                    # Reconciliation here would consume our own unsent checkpoint.
                    assert settled_result[0] is not None
                    current = settled_result[0]
                    if (account.cash, account.buying_power) != (settled_account[0].cash, settled_account[0].buying_power):
                        raise OrderEvidenceNotReady('market BUY cash changed after complete reconciliation')
                    validation._market_buy_candidate_or_refuse(conn, plan=plan, projection=projection,
                        deployment=deployment, observation=current.observation, **kw)
                    return
                observation = await market_reservations.prove(conn, basis=basis,
                    plan=plan, projection=projection, deployment=deployment, broker=native, account=account,
                    activity=None, candidate_key=kw["client_key"])
                validation._market_buy_candidate_or_refuse(conn, plan=plan, projection=projection,
                    deployment=deployment, observation=observation,
                    cash_ceiling=D(basis["cash_limits"][kw["client_key"]]), reservation=basis, **kw)

            guarded = wrapper(native, funding=check)
            guarded._grant = automation_runtime._grant(ctx, "EXECUTE", binding=authority)
            result = await executor._execute_session_locked(conn=conn, broker=guarded,
                deployment=deployment, plan=plan, instruments=identities, today=plan.effective_session,
                target_projection=projection, min_increment=D("0.000000001"), informational_current_book=True,
                actions=None, reductions_only=bool(guarded._grant.reduction_only_reconciliation_id), buy_admission=lambda **_: SimpleNamespace(allowed=True),
                increase_reconciliation_authority=funds, reserve_market_buys=reserve,
                reserved_market_buy_keys=reserved_keys,
                market_buy_window_open=lambda: native.now < timing.execution_open_at + timedelta(minutes=10))
            assert not result.refused, result.to_dict()
            outcomes.append((result.detail, result.deferral_reasons))
            if not result.submitted and "failed" in result.detail:
                raise WorkerRefused(result.detail)
            if result.deferral_reasons:
                print(f"deferred_count={len(result.deferral_reasons)} reasons={sorted(set(result.deferral_reasons.values()))}", flush=True)
        return dict(disposition="RECONCILE")

    async def execute(ctx):
        # Production's worker owns this finite heartbeat while callbacks run.
        # The stand-alone scheduler fixture must provide the same real owner;
        # twenty independent funding checks must not outlive an unrenewed lease.
        with live_lease(pg.sync_dsn, ctx.permit, cfg):
            return await execute_owned(ctx)

    async def recover(ctx):
        with gateway.connect() as conn:
            rec = await reconcile.reconcile(broker=native, conn=conn, binding=None,
                                            deployment=deployment, informational_current_book=True)
            assert rec.transport_ready, rec.to_dict()
            in_flight = journal.in_flight_commands(conn, deployment)
            if in_flight:
                route = market_reservations.recovery_route(conn, cycle=ctx.cycle, deployment=deployment,
                    reconciliation=rec, config=cfg, now=native.now, in_flight=in_flight,
                    actionable_deltas=lambda current: automation_runtime._actionable_projection_deltas(
                        conn, plan=current, effective_session=plan.effective_session, observation=rec.observation,
                        minimum_quantity_increment=native.capabilities.minimum_quantity_increment))
                if route is not None:
                    return route.model_copy(update={"diagnostic": {**rec.to_dict(), **route.diagnostic}})
                return dict(disposition="RECONCILE", failure_code="COMMANDS_IN_FLIGHT")
            rows = journal.load_commands(conn, deployment, plan_id=plan.plan_id)
            complete = len(rows) == len(target) and all(c.state is CommandState.FILLED for c in rows)
            if increase_held is not None and ctx.cycle.plan_id is not None:
                complete = not automation_runtime._actionable_projection_deltas(conn, plan=plan,
                    effective_session=plan.effective_session, observation=rec.observation,
                    minimum_quantity_increment=native.capabilities.minimum_quantity_increment)
            return dict(disposition="SUCCEEDED" if complete or ctx.cycle.plan_id is None else "READY_TO_EXECUTE",
                        last_clean_reconciliation_id=str(rec.observation_id) if rec.clean else None,
                        transport_reconciliation_id=str(rec.observation_id))

    def driver(holder):
        return RecoveryAutomationService(config=cfg, holder_id=holder, refresh=refresh_result,
                                         prepare=prepare, recover=recover, execute=execute)

    scheduler = driver("first-worker")
    for _ in range(4):
        parked = await scheduler.tick(database, now=timing.execution_open_at - timedelta(seconds=5))
    assert parked.cycle.state is CycleState.WAITING_OPEN and native.accepted == [], parked.cycle.failure_detail
    started = monotonic()
    if increase_held is not None:
        native.now = max(native.now, timing.execute_at)
    restart = increase_held is None or venue_case in {'restart', 'partial_restart'}
    if restart:
        with pytest.raises(WorkerLost):
            initial = await scheduler.tick(database, now=timing.execute_at)
            pytest.fail(f"worker did not reach injected crash: {initial.reason}, {initial.cycle.failure_detail}")
        assert any(c.state is CommandState.SEND_PENDING for c in journal.load_commands(database, deployment,
                                                                                        plan_id=plan.plan_id))
        await asyncio.sleep(cfg.lease_seconds + 0.2)
        scheduler = driver("replacement-worker")
    previous = None
    while monotonic()-started < (180 if native.slow or increase_held is not None else 60):
        await asyncio.sleep(0.4)
        if increase_held is None:
            native.now = timing.execute_at + timedelta(seconds=monotonic()-started)
        result = await scheduler.tick(database, now=native.now)
        progress = (result.cycle.state, len(native.accepted), result.cycle.failure_detail)
        if increase_held is not None:
            progress = (len(native.accepted), sum(o.state is CommandState.FILLED for o in native._orders.values()),
                        result.cycle.state.terminal, result.cycle.failure_detail)
        if (native.slow or increase_held is not None) and previous != progress:
            print(f"elapsed={monotonic()-started:.1f} cycle={result.cycle.state.value} accepted={len(native.accepted)} "
                  f"filled={sum(o.state is CommandState.FILLED for o in native._orders.values())} "
                  f"cash={native.cash} failure={result.cycle.failure_detail}", flush=True)
        previous = progress
        if (increase_held is not None and native.resting_key is not None
                and len(native.accepted) == 21
                and all(order.state is CommandState.FILLED for order in native._orders.values()
                        if order.client_key != native.resting_key)):
            break
        if result.cycle.state.terminal:
            break
    if increase_held is not None and native.resting_key is not None:
        before_keys = tuple(native.accepted)
        for second in range(3):
            native.now = max(native.now, timing.execution_open_at+timedelta(minutes=10, seconds=1+second))
            pending = await scheduler.tick(database, now=native.now)
            assert pending.cycle.state in {CycleState.RECONCILING, CycleState.RETRY_WAIT}
        assert tuple(native.accepted) == before_keys and len(set(before_keys)) == 21
        rows = journal.load_commands(database, deployment, plan_id=plan.plan_id)
        outstanding = [c for c in rows if c.state not in {CommandState.FILLED, CommandState.CANCELLED}]
        assert len(outstanding) == 1 and outstanding[0].client_key == native.resting_key
        expected = CommandState.PARTIALLY_FILLED if venue_case == 'resting_partial' else CommandState.ACKNOWLEDGED
        assert outstanding[0].state is expected
        assert native._by_key(native.resting_key).state is expected
        assert native.cash >= 0 and state.to_dict() == state_before
        print(json.dumps(dict(scope='prepared_inputs_execution_recovery', start=starting_exposure,
            target=ending_exposure, scenario=venue_case, submitted=21, filled=20,
            outstanding_state=expected.value, cycle_state=pending.cycle.state.value,
            after_cutoff_no_new_orders=True)), flush=True)
        return
    assert result.cycle.state is CycleState.SUCCEEDED, (
        result.reason, result.cycle.failure_detail, result.cycle.state, len(native.accepted),
        [(o.instrument.security_id, o.state.value, str(o.filled)) for o in native._orders.values()],
        outcomes[-1:])
    rows = journal.load_commands(database, deployment, plan_id=plan.plan_id)
    cancelled = increase_held is not None and venue_case in {'cancelled_partial', 'cancelled_unfilled'}
    assert len(rows) == len(set(native.accepted)) == len(target)+int(cancelled)
    assert all(row.state in ({CommandState.FILLED, CommandState.CANCELLED} if cancelled else {CommandState.FILLED}) for row in rows)
    assert sum(row.side is Side.SELL for row in rows) == sales
    assert native.cash >= 0 and len(admissions) >= (2 if restart else 1)
    assert state.to_dict() == state_before, 'execution changed canonical strategy state'
    if increase_held is not None:
        assert len(rows) == 21+int(cancelled) and sum(c.side is Side.BUY for c in rows) == 20+int(cancelled)
        if venue_case == 'whole':
            assert native.peak_working_buys == 1 and native.peak == 1
        elif venue_case != 'mixed':
            assert native.peak_working_buys >= 2, 'dollar purchases waited for previous fills'
            assert 2 <= native.peak <= 4
        else:
            assert 1 <= native.peak <= 4
        positions = {sid: qty for sid, (_asset, qty) in native._positions.items()}
        assert native.cash+sum(positions.values())*100 == nav
        assert positions[DEFENSIVE_SECURITY_ID] == D(100-ending_exposure)*10
        assert all(qty >= 0 for qty in positions.values())
        for sid in identities:
            movement = sum((fill.quantity*(1 if native._by_key(fill.client_key).side is Side.BUY else -1)
                for fill in native._fills if native._by_key(fill.client_key).instrument.security_id == sid), D(0))
            assert positions.get(sid, D(0)) == held.get(sid, D(0))+movement
        buys = [row for row in rows if row.side is Side.BUY]
        assert sum(row.notional is not None for row in buys) == (
            0 if venue_case == 'whole' else 10 if venue_case == 'mixed' else 20+int(cancelled))
        assert all(row.quantity is None if row.notional is not None else row.quantity == row.quantity.to_integral_value()
                   for row in buys)
        spent = sum(fill.quantity*fill.price for fill in native._fills if native._by_key(fill.client_key).side is Side.BUY)
        assert spent <= nav*D(ending_exposure-starting_exposure)/100
        if venue_case in {'partial', 'partial_restart'}:
            assert native.partial_seen and len(native._fills) == 42
        if cancelled:
            old = next(c for c in rows if c.client_key == native.cancelled_key)
            assert old.state is CommandState.CANCELLED
            assert (old.filled_quantity > 0) is (venue_case == 'cancelled_partial')
            replacements = [c for c in buys if c.security_id == old.security_id and c.client_key != old.client_key]
            assert len(replacements) == 1 and replacements[0].identity.revision == old.identity.revision+1
            fee_reserves = 2 if venue_case == 'cancelled_partial' else 1
            assert replacements[0].notional+old.filled_quantity*100+fee_reserves == D(ending_exposure-starting_exposure)*50
        if venue_case == 'ignored_cancel':
            assert native.cancelled_key is not None
            assert next(c for c in rows if c.client_key == native.cancelled_key).state is CommandState.FILLED
        fractional_progress.require_completed(fractional_progress.evidence(database,
            projection=projection, deployment=deployment))
        print(json.dumps(dict(scope='prepared_inputs_execution_recovery', start=starting_exposure,
            target=ending_exposure, scenario=venue_case, submitted=len(rows),
            filled=sum(c.state is CommandState.FILLED for c in rows), restart=int(restart),
            peak_posts=native.peak, peak_working_buys=native.peak_working_buys,
            cash_residual=str(native.cash),
            achieved_core_exposure=str(sum(qty for sid, qty in positions.items()
                if sid != DEFENSIVE_SECURITY_ID)*100/nav))), flush=True)
        return
    elif sales == 1:
        assert native.peak_working_buys == 2, "the second purchase waited for the first to fill"
    else:
        assert native.peak >= 2, "the disposal basket submitted its sales serially"
    print(f"scope=dispatch_restart_fixture strategy=prepared buy_admission=fixture venue=simulated "
          f"sales={sales} purchases={len(rows)-sales} starting_equity_exposure={starting_exposure if increase_held is not None or sales != 1 else 100*(nav-initial_cash)/nav} "
          f"ending_equity_exposure={ending_exposure} eligibility={venue_case} cash_residual={native.cash} "
          f"restart={int(restart)} peak_posts={native.peak} peak_working_buys={native.peak_working_buys} first_post_seconds={native.first_acceptance-started:.2f} "
          f"opening_to_confirmed_seconds={monotonic()-started:.2f}")

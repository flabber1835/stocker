"""Dispatch and restart regression with prepared strategy inputs and fixture buy admission.

The scheduler, journal, recovery, fractional execution and cash reservations
run here. Elapsed times describe this private fixture with a delayed venue.
"""
import asyncio
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
import os
import shutil
import tempfile
from time import monotonic, sleep
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import authority as certificates
from sentinel import automation_recovery, automation_runtime, backup_runtime_authority as backup, binding, dual_plan_authority, schema
from sentinel.automation import schedule, store
from sentinel.automation.model import ControlBinding, CycleState
from sentinel.automation_resilience import RecoveryAutomationService
from sentinel.core.decision import DEFENSIVE_SECURITY_ID
from sentinel.execution import executor, fractional_sizing, held_targets, journal, reconcile, target_reprojection
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerAccountIdentity, BrokerInstrument, Side
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
from tests.sentinel.test_production_decision import _publication
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
    deployment = DeploymentIdentity("parallel-opening-rehearsal", "alpaca", "PATEST", 1)
    slow = os.environ.get("SENTINEL_TEST_SLOW_OPEN") == "1"
    monkeypatch.setenv("SENTINEL_AUTOMATION_LEASE_SECONDS", "45" if slow else "10")
    monkeypatch.setenv("SENTINEL_AUTOMATION_HEARTBEAT_SECONDS", "2")
    monkeypatch.setenv("SENTINEL_AUTOMATION_RETRY_BASE_SECONDS", "1")
    cfg = automation_runtime.config_from_env()
    state, original = case(entries=2 if sales == 1 else 0, sale=True, exposure="1" if sales == 1 else "0")
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
    native.now = timing.execute_at
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
    async def execute(ctx):
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
            async def funds(rec):
                assert rec.transport_ready
                _, account, activity, _, _ = await reconciliation_evidence._settled_account_evidence_bracket(
                    conn=conn, broker=native, binding=binding.require(conn), expected_account=deployment.broker_account_id,
                    deployment=deployment, initial_result=rec, actions=None, dual_mode=True,
                    clock=lambda: native.now, allow_restrictions=True)
                assert activity is None  # No corporate cash postings on the simulated account.
                return PostingFunds(account.cash, account.buying_power, D(0), D(0))

            def reserve(commands, rec, posting_funds):
                market_reservations.reserve(conn, commands, plan=plan, projection=projection,
                    deployment=deployment, reconciliation=rec, funds=posting_funds, activity=None)

            async def check(*, account, **kw):
                basis = market_reservations.load(conn, plan)
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
                market_buy_window_open=lambda: native.now < timing.execution_open_at + timedelta(minutes=10))
            assert not result.refused, result.to_dict()
            outcomes.append((result.detail, result.deferral_reasons))
            if not result.submitted and "failed" in result.detail:
                raise WorkerRefused(result.detail)
            if result.deferral_reasons:
                print(f"deferred={result.deferral_reasons}", flush=True)
        return dict(disposition="RECONCILE")

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
    with pytest.raises(WorkerLost):
        initial = await scheduler.tick(database, now=timing.execute_at)
        pytest.fail(f"worker did not reach injected crash: {initial.reason}, {initial.cycle.failure_detail}")
    assert any(c.state is CommandState.SEND_PENDING for c in journal.load_commands(database, deployment,
                                                                                    plan_id=plan.plan_id))
    await asyncio.sleep(cfg.lease_seconds + 0.2)
    scheduler = driver("replacement-worker")
    previous = None
    while monotonic()-started < (180 if native.slow else 60):
        await asyncio.sleep(0.4)
        native.now = timing.execute_at + timedelta(seconds=monotonic()-started)
        result = await scheduler.tick(database, now=native.now)
        progress = (result.cycle.state, len(native.accepted), result.cycle.failure_detail)
        if native.slow and previous != progress:
            print(f"elapsed={monotonic()-started:.1f} cycle={result.cycle.state.value} accepted={len(native.accepted)} "
                  f"failure={result.cycle.failure_detail}", flush=True)
        previous = progress
        if result.cycle.state.terminal:
            break
    assert result.cycle.state is CycleState.SUCCEEDED, (
        result.reason, result.cycle.failure_detail, result.cycle.state, len(native.accepted), outcomes[-1:])
    rows = journal.load_commands(database, deployment, plan_id=plan.plan_id)
    assert len(rows) == len(set(native.accepted)) == len(target)
    assert all(row.state is CommandState.FILLED for row in rows)
    assert sum(row.side is Side.SELL for row in rows) == sales
    assert native.cash >= 0 and len(admissions) >= 2
    if sales == 1:
        assert native.peak_working_buys == 2, "the second purchase waited for the first to fill"
    else:
        assert native.peak >= 2, "the disposal basket submitted its sales serially"
    print(f"scope=dispatch_restart_fixture strategy=prepared buy_admission=fixture venue=simulated "
          f"sales={sales} purchases={len(rows)-sales} starting_equity_exposure={100*(nav-initial_cash)/nav if sales==1 else starting_exposure} "
          f"restart=1 peak_posts={native.peak} peak_working_buys={native.peak_working_buys} first_post_seconds={native.first_acceptance-started:.2f} "
          f"opening_to_confirmed_seconds={monotonic()-started:.2f}")

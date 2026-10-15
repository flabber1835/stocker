"""The guarded broker is a complete, freshly checked execution membrane."""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import fields, replace
from datetime import date
from decimal import Decimal

import pytest

from sentinel import schema
from sentinel.automation.model import CancellationAuthority
from sentinel.execution import journal, recovery
from sentinel.execution.certification import (
    AdapterNotCertified, require_certified_adapter)
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, ExecutionBroker, Side
from sentinel.execution.guarded import (
    AttendedPaperExecutionGrant,
    AutomationExecutionGrant,
    BrokerAuthorityRefused,
    BrokerOperation,
    ExecutionBrokerGuard,
    GuardedExecutionBroker,
    ManualExecutionGrant,
    PaperPreparationGrant,
    PreTransportAuthorityRefused,
)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.simulator import FaultKind, SimulatedBroker
from sentinel.execution.states import CommandState
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres


INSTRUMENT = BrokerInstrument(
    security_id="SEC-AAA", symbol="AAA", broker_id="asset-aaa")
DEPLOYMENT = DeploymentIdentity(
    deployment_id="sentinel-test", broker="sim",
    broker_account_id="SIM-ACCOUNT", takeover_epoch=1)


def test_attended_grant_never_receives_production_certification():
    from datetime import datetime,timezone,timedelta
    from sentinel.execution.certification import certify_wrapper
    now=datetime(2026,10,15,17,30,tzinfo=timezone.utc)
    grant=AttendedPaperExecutionGrant('test','paper','plan',now.date(),now,now+timedelta(minutes=5))
    inner=SimulatedBroker()
    wrapped=Recorder().wrap(inner,grant)
    assert wrapped.certified_adapter_identity is None
    with pytest.raises(AdapterNotCertified):require_certified_adapter(wrapped)
    with pytest.raises(AdapterNotCertified,match='attended'):
        certify_wrapper(wrapped,inner,wrapper_kind='generation-fenced-execution')
    # Falsify the restriction against a genuinely issued inner identity:
    # without this check, a test window could obtain a wrapper certificate.
    from sentinel.execution import certification as certification_module
    import textwrap
    certification_module.certify_adapter(inner,name='simulator',mode='SIMULATION')
    source=textwrap.dedent(inspect.getsource(certification_module.certify_wrapper))
    changed=source.replace("if isinstance(getattr(wrapper, 'grant', None), AttendedPaperExecutionGrant):",'if False:')
    assert changed!=source
    namespace=dict(vars(certification_module));exec(changed,namespace)
    unsafe=namespace['certify_wrapper'](wrapped,inner,wrapper_kind='generation-fenced-execution')
    assert unsafe.wrapper_kind=='generation-fenced-execution'


@pytest.mark.parametrize('damage',['long','closed','naive','reversed'])
def test_attended_grant_requires_a_short_actual_session_window(damage):
    from datetime import datetime,timezone,timedelta
    now=datetime(2026,10,15,17,30,tzinfo=timezone.utc)
    start,end=now,now+timedelta(minutes=5)
    if damage=='long':end=now+timedelta(minutes=31)
    if damage=='closed':start,end=now+timedelta(hours=4),now+timedelta(hours=4,minutes=5)
    if damage=='naive':start=start.replace(tzinfo=None)
    if damage=='reversed':start,end=end,start
    with pytest.raises(ValueError):
        AttendedPaperExecutionGrant('test','paper','plan',now.date(),start,end)


@pytest.mark.parametrize('attended,expired',[(False,False),(True,False),(True,True)])
def test_intraday_window_is_explicit_and_cannot_extend_production(attended,expired):
    from datetime import datetime,timezone,timedelta
    from types import SimpleNamespace
    from sentinel.execution.contract import BrokerCapabilities,CommandOutcome
    now=datetime(2026,10,15,17,30,tzinfo=timezone.utc)
    submitted=[]
    async def clock():return SimpleNamespace(timestamp=now,is_open=True)
    async def submit(**kwargs):
        submitted.append(kwargs)
        return CommandOutcome(CommandState.ACKNOWLEDGED,'test-order')
    class ClockBroker:
        capabilities=BrokerCapabilities()
        async def market_clock(self):return await clock()
        def _now(self):return now
        async def submit(self,**kwargs):return await submit(**kwargs)
    inner=ClockBroker()
    if attended:
        grant=AttendedPaperExecutionGrant('test','paper','plan',now.date(),
            now-timedelta(minutes=5),now+(timedelta(0) if expired else timedelta(minutes=5)))
    else:grant=manual_grant()
    wrapped=Recorder().wrap(inner,grant)
    async def attempt():return await wrapped.submit(client_key='key',instrument=INSTRUMENT,side=Side.BUY,quantity=Decimal(1))
    if attended and not expired:
        assert asyncio.run(attempt()).state is CommandState.ACKNOWLEDGED
        assert len(submitted)==1
    else:
        with pytest.raises(PreTransportAuthorityRefused):asyncio.run(attempt())
        assert not submitted


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    connection.commit()
    schema.ensure_schema(connection)
    yield connection
    connection.close()


def run(awaitable):
    return asyncio.run(awaitable)


def manual_grant() -> ManualExecutionGrant:
    return ManualExecutionGrant(
        confirm_paper_account="SIM-ACCOUNT",
        confirm_plan_id="sentinel-plan",
        confirm_effective_session=date(2026, 8, 13),
        confirm_submit_paper_orders=True)


def automation_grant(*, cancellation_check=None) -> AutomationExecutionGrant:
    return AutomationExecutionGrant(
        operation_scope="EXECUTE", cycle_id="cycle-2026-08-13",
        control_generation=3,
        holder_id="appliance-a", fence_token=19,
        broker_account_id="SIM-ACCOUNT", takeover_epoch=1,
        rollout_mode="PINNED_1_00", rollout_version=2,
        certificate_sha256="a" * 64,
        cancellation_check=cancellation_check)


def preparation_grant() -> PaperPreparationGrant:
    return PaperPreparationGrant(
        expected_account="SIM-ACCOUNT",
        decision_session=date(2026, 8, 12))


class Recorder:
    def __init__(self) -> None:
        self.before_reads = []
        self.after_reads = []
        self.before_mutations = []
        self.authorized = True

    async def before_read(self, grant, operation) -> None:
        if not self.authorized:
            raise PreTransportAuthorityRefused("read authority revoked")
        self.before_reads.append((grant, operation))

    async def after_read(self, grant, operation, result) -> None:
        if not self.authorized:
            raise PreTransportAuthorityRefused("read authority revoked")
        self.after_reads.append((grant, operation, result))

    async def before_mutation(self, grant, operation) -> None:
        if not self.authorized:
            raise PreTransportAuthorityRefused("mutation authority revoked")
        self.before_mutations.append((grant, operation))

    def wrap(self, inner, grant=None) -> GuardedExecutionBroker:
        guard = ExecutionBrokerGuard(
            before_read=self.before_read, after_read=self.after_read,
            before_mutation=self.before_mutation)
        return GuardedExecutionBroker(
            inner=inner, grant=grant or manual_grant(),
            guard=guard)


def command(state=CommandState.PLANNED) -> Command:
    return Command(
        identity=CommandIdentity(
            deployment=DEPLOYMENT, plan_id="sentinel-plan",
            security_id=INSTRUMENT.security_id),
        instrument=INSTRUMENT, side=Side.BUY, quantity=Decimal("1"),
        state=state)


def test_protocol_introspection_forces_every_broker_method_through_guard():
    """Adding any protocol coroutine without a wrapper/operation breaks CI."""
    protocol_methods = {
        name for name, value in ExecutionBroker.__dict__.items()
        if not name.startswith("_") and inspect.iscoroutinefunction(value)
    }
    guarded_methods = {
        name for name, value in GuardedExecutionBroker.__dict__.items()
        if not name.startswith("_") and inspect.iscoroutinefunction(value)
    }
    operation_names = {operation.value for operation in BrokerOperation}

    assert protocol_methods == guarded_methods == operation_names


def test_grants_are_typed_identity_only_and_cannot_carry_plan_economics():
    manual = manual_grant()
    automated = automation_grant()
    preparation = preparation_grant()
    forbidden = {
        "target_basket", "weights", "quantity", "price", "marks",
        "account_nav", "account_cash", "target_exposure",
    }

    assert forbidden.isdisjoint(field.name for field in fields(manual))
    assert forbidden.isdisjoint(field.name for field in fields(automated))
    assert forbidden.isdisjoint(field.name for field in fields(preparation))
    with pytest.raises(ValueError, match="explicit paper-submit"):
        ManualExecutionGrant(
            confirm_paper_account="SIM-ACCOUNT", confirm_plan_id="plan",
            confirm_effective_session=date(2026, 8, 13),
            confirm_submit_paper_orders=False)
    with pytest.raises(ValueError, match="lowercase hexadecimal"):
        AutomationExecutionGrant(
            operation_scope="EXECUTE", cycle_id="cycle",
            control_generation=1, holder_id="holder",
            fence_token=1, broker_account_id="SIM-ACCOUNT", takeover_epoch=1,
            rollout_mode="PINNED_1_00", rollout_version=1,
            certificate_sha256="not-a-digest")


def test_prepare_scoped_automation_grant_is_structurally_read_only():
    inner = SimulatedBroker()
    recorder = Recorder()
    grant = automation_grant().__class__(**{
        **automation_grant().__dict__, "operation_scope": "PREPARE"})
    broker = recorder.wrap(inner, grant)

    run(broker.observe())
    with pytest.raises(PreTransportAuthorityRefused, match="read-only.*submit"):
        run(broker.submit(
            client_key="must-not-submit", instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal("1")))
    with pytest.raises(PreTransportAuthorityRefused, match="read-only.*cancel"):
        run(broker.cancel("must-not-cancel"))

    assert recorder.before_mutations == []
    assert not any(call.startswith(("submit:", "cancel:"))
                   for call in inner.calls)


def test_recovery_scope_refuses_submit_but_retains_guarded_cancellation():
    inner = SimulatedBroker()
    recorder = Recorder()
    grant = automation_grant().__class__(**{
        **automation_grant().__dict__, "operation_scope": "RECOVER"})
    broker = recorder.wrap(inner, grant)

    with pytest.raises(PreTransportAuthorityRefused, match="read-only.*submit"):
        run(broker.submit(
            client_key="must-not-submit", instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal("1")))
    run(broker.cancel("safe-cancel"))

    assert recorder.before_mutations == [
        (grant, BrokerOperation.CANCEL)]
    assert not any(call.startswith("submit:") for call in inner.calls)
    assert "cancel:safe-cancel" in inner.calls


def test_paper_preparation_grant_allows_reads_but_never_mutations():
    inner = SimulatedBroker()
    recorder = Recorder()
    grant = preparation_grant()
    broker = recorder.wrap(inner, grant)

    account = run(broker.identify_account())
    observation = run(broker.observe())

    assert account.account_id == "SIM-ACCOUNT"
    assert observation is not None
    assert [operation for _grant, operation in recorder.before_reads] == [
        BrokerOperation.IDENTIFY_ACCOUNT, BrokerOperation.OBSERVE]

    with pytest.raises(PreTransportAuthorityRefused, match="read-only.*submit"):
        run(broker.submit(
            client_key="must-not-submit", instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal("1")))
    with pytest.raises(PreTransportAuthorityRefused, match="read-only.*cancel"):
        run(broker.cancel("must-not-cancel"))

    assert recorder.before_mutations == []
    assert not any(call.startswith(("submit:", "cancel:"))
                   for call in inner.calls)


def test_every_read_and_mutation_gets_its_own_fresh_guard_callback():
    inner = SimulatedBroker()
    recorder = Recorder()
    grant = automation_grant()
    broker = recorder.wrap(inner, grant)

    async def exercise():
        await broker.identify_account()
        await broker.account_snapshot()
        await broker.resolve_instrument(security_id="SEC-AAA", symbol="AAA")
        await broker.observe()
        await broker.observe_with_terminal_recovery(
            submitted_after=inner.now, processed_through=inner.now)
        await broker.find_by_client_key("absent")
        await broker.recent_fills(inner.now)
        outcome = await broker.submit(
            client_key="guarded-key", instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal("1"))
        await broker.cancel(outcome.broker_order_id)

    run(exercise())

    read_operations = [operation for _grant, operation in recorder.before_reads]
    after_operations = [
        operation for _grant, operation, _result in recorder.after_reads]
    mutation_operations = [
        operation for _grant, operation in recorder.before_mutations]
    assert read_operations == [
        BrokerOperation.IDENTIFY_ACCOUNT,
        BrokerOperation.ACCOUNT_SNAPSHOT,
        BrokerOperation.RESOLVE_INSTRUMENT,
        BrokerOperation.OBSERVE,
        BrokerOperation.OBSERVE_WITH_TERMINAL_RECOVERY,
        BrokerOperation.FIND_BY_CLIENT_KEY,
        BrokerOperation.RECENT_FILLS,
    ]
    assert after_operations == read_operations
    assert mutation_operations == [
        BrokerOperation.SUBMIT, BrokerOperation.CANCEL]
    assert all(seen is grant for seen, _operation in recorder.before_reads)
    assert all(seen is grant for seen, _operation in recorder.before_mutations)
    assert broker.grant is grant
    assert isinstance(broker.guard, ExecutionBrokerGuard)
    assert broker.capabilities is inner.capabilities


@pytest.mark.parametrize("operation", [BrokerOperation.SUBMIT,
                                       BrokerOperation.CANCEL])
def test_revocation_between_read_and_mutation_causes_zero_inner_mutations(
        operation):
    inner = SimulatedBroker()
    recorder = Recorder()
    broker = recorder.wrap(inner)

    async def exercise():
        await broker.observe()
        recorder.authorized = False  # kill/revoke after the fresh read
        if operation is BrokerOperation.SUBMIT:
            await broker.submit(
                client_key="must-not-land", instrument=INSTRUMENT,
                side=Side.BUY, quantity=Decimal("1"))
        else:
            await broker.cancel("must-not-cancel")

    with pytest.raises(PreTransportAuthorityRefused,
                       match="mutation authority revoked"):
        run(exercise())
    assert not any(call.startswith(("submit:", "cancel:"))
                   for call in inner.calls)


def test_cancelled_callback_authority_refuses_late_broker_mutation():
    authority = CancellationAuthority()
    inner = SimulatedBroker()
    broker = Recorder().wrap(
        inner, automation_grant(cancellation_check=authority.require_active))
    authority.cancel("callback deadline expired")

    with pytest.raises(PreTransportAuthorityRefused, match="StaleLeaderRefused"):
        run(broker.submit(
            client_key="late-submit", instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal("1")))
    assert not any(call.startswith("submit:") for call in inner.calls)


def test_dispatch_reraises_pretransport_refusal_instead_of_inventing_unknown():
    inner = SimulatedBroker()
    recorder = Recorder()
    recorder.authorized = False
    broker = recorder.wrap(inner)
    pending = recovery.prepare_send(command())

    with pytest.raises(PreTransportAuthorityRefused):
        run(recovery.dispatch(broker, pending))

    assert pending.state is CommandState.SEND_PENDING
    assert not any(call.startswith("submit:") for call in inner.calls)


def test_unavailable_guard_backend_is_also_known_pretransport_refusal():
    inner = SimulatedBroker()

    async def allowed_read(_grant, _operation):
        return None

    async def allowed_after(_grant, _operation, _result):
        return None

    async def database_down(_grant, _operation):
        raise OSError("authority database unavailable")

    broker = GuardedExecutionBroker(
        inner=inner, grant=manual_grant(),
        guard=ExecutionBrokerGuard(
            before_read=allowed_read, after_read=allowed_after,
            before_mutation=database_down))

    with pytest.raises(
            PreTransportAuthorityRefused,
            match="authority check failed before transport: OSError"):
        run(recovery.dispatch(broker, recovery.prepare_send(command())))
    assert not any(call.startswith("submit:") for call in inner.calls)


def test_true_transport_exception_remains_unknown_under_the_guard():
    inner = SimulatedBroker().schedule_submit(FaultKind.OUTAGE)
    recorder = Recorder()
    broker = recorder.wrap(inner)

    sent = run(recovery.dispatch(broker, recovery.prepare_send(command())))

    assert sent.state is CommandState.UNKNOWN
    assert "BrokerUnavailable" in sent.detail
    assert recorder.before_mutations == [
        (broker.grant, BrokerOperation.SUBMIT)]


def test_alternate_adapter_cannot_borrow_canonical_wrapper_certification():
    class AlternateBroker(SimulatedBroker):
        certification_name = "alternate-test"

    inner = AlternateBroker()
    inner.capabilities = replace(
        inner.capabilities, pre_submit_instrument_revalidation=True)
    broker = Recorder().wrap(inner)
    with pytest.raises(AdapterNotCertified, match="composition-issued"):
        require_certified_adapter(broker)


@pytest.mark.parametrize("phase", ["before", "after"])
def test_read_guard_failure_is_typed_but_inner_transport_is_not(phase):
    inner = SimulatedBroker()

    async def before(_grant, _operation):
        if phase == "before":
            raise RuntimeError("certificate revoked")

    async def after(_grant, _operation, _result):
        if phase == "after":
            raise RuntimeError("fence changed")

    async def mutate(_grant, _operation):
        return None

    broker = GuardedExecutionBroker(
        inner=inner, grant=automation_grant(),
        guard=ExecutionBrokerGuard(
            before_read=before, after_read=after,
            before_mutation=mutate))

    with pytest.raises(BrokerAuthorityRefused, match="authority check failed"):
        run(broker.observe())
    expected_inner_reads = 0 if phase == "before" else 1
    assert inner.calls.count("list_orders") == expected_inner_reads * 2


def test_inner_read_transport_failure_remains_retryable_transport_error():
    inner = SimulatedBroker().schedule_observe(FaultKind.OUTAGE)
    broker = Recorder().wrap(inner, automation_grant())

    with pytest.raises(Exception, match="simulated transport failure") as caught:
        run(broker.observe())

    assert not isinstance(caught.value, BrokerAuthorityRefused)


def test_send_pending_refused_before_transport_remains_durable_and_recoverable(
        conn):
    inner = SimulatedBroker()
    recorder = Recorder()
    broker = recorder.wrap(inner)
    planned = command()
    pending = recovery.prepare_send(planned)
    journal.save_command(conn, planned)
    journal.save_command(conn, pending, previous=planned.state)

    recorder.authorized = False
    with pytest.raises(PreTransportAuthorityRefused):
        run(recovery.dispatch(broker, pending))

    durable = journal.load_commands(conn, DEPLOYMENT)[0]
    assert durable.state is CommandState.SEND_PENDING
    assert durable.client_key == pending.client_key

    # Restart/recovery does not need to invent a new command identity.  Once
    # authority is available it promotes the persisted crash-window state,
    # exact-looks up the same key, and retains uncertainty after absent reads.
    recorder.authorized = True
    unknown = recovery.promote_to_unknown(durable)
    journal.save_command(conn, unknown, previous=durable.state)
    observation = run(broker.observe())
    resolved = run(recovery.resolve_unknown(broker, unknown, observation))
    journal.save_command(conn, resolved, previous=unknown.state)

    assert resolved.state is CommandState.UNKNOWN
    retained = journal.load_commands(conn, DEPLOYMENT)[0]
    assert retained.state is CommandState.UNKNOWN
    assert retained.client_key == pending.client_key
    assert recovery.blocked_securities([retained]) == {pending.security_id}
    assert not any(call.startswith("submit:") for call in inner.calls)

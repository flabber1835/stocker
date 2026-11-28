"""Real adapter GETs refresh display evidence without financial authority."""
import asyncio
from copy import deepcopy
import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import httpx
import pytest

from sentinel import binding, local_paper
from sentinel.config import SentinelConfig
from sentinel.execution import account_status as module, journal
from sentinel.execution.alpaca import AlpacaExecutionBroker
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, OrderTerms, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState as S
from sentinel.panel import sources, model, overview, overview_data
from tests.sentinel.test_operator_monitoring import db, issue369_pg

NATIVE = "11111111-1111-4111-8111-111111111111"


def fixture(db, monkeypatch):
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, "PAfixture")
    binding.bind(db, deployment_id="account-display", broker="alpaca",
                 broker_account_id="PAfixture")
    account = dict(id=NATIVE, account_number="PAfixture", currency="USD",
        equity="50000", cash="10000", buying_power="8959.27", multiplier="1",
        status="ACTIVE", trading_blocked=False, account_blocked=False,
        trade_suspended_by_user=False)
    calls = []
    change = []
    orders = []
    positions = []
    account_calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET"
        assert db.info.transaction_status.name == "IDLE"
        if request.url.path == "/v2/orders":
            assert request.url.params["status"] == "open"
            return httpx.Response(200, json=deepcopy(orders))
        if request.url.path == '/v2/positions':
            return httpx.Response(200, json=deepcopy(positions))
        assert request.url.path == "/v2/account"
        account_calls.append(True)
        payload = deepcopy(account)
        if len(account_calls) % 2 == 0 and change:
            payload.update(change[0])
        return httpx.Response(200, json=payload)
    provider = SimpleNamespace(AsyncClient=lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), **kw))
    reader = AlpacaExecutionBroker(api_key="fixture", secret_key="fixture",
        base_url="https://paper-api.alpaca.markets", http_provider=lambda: provider)
    config = SentinelConfig.from_env({})
    return SimpleNamespace(account=account, calls=calls, change=change,
                           orders=orders, positions=positions, reader=reader, config=config)


def collect(db, f):
    return asyncio.run(module.collect(db, config=f.config, reader=f.reader))


def test_real_gets_refresh_only_append_only_panel_evidence(db, monkeypatch):
    f = fixture(db, monkeypatch)
    assert collect(db, f) is True
    first = sources._latest_account_evidence(db)
    assert first["account_id"] == "PAfixture" and first["cash"] == 10000
    assert first["buying_power"].as_tuple().exponent == -2
    db.rollback()
    assert collect(db, f) is True
    last = sources._latest_account_evidence(db)
    assert last["observed_at"] > first["observed_at"]
    assert db.execute("SELECT count(*) FROM sentinel_broker_account_evidence").fetchone()[0] == 2
    for table in ("sentinel_commands", "sentinel_fills", "sentinel_observations", "sentinel_execution_plans"):
        assert db.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
    assert len(f.calls) == 4


def test_account_insert_waits_across_transactions_without_redating_native_read(db, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import sleep
    import psycopg
    from sentinel import account_lock_observation

    f = fixture(db, monkeypatch)
    db.execute("SET statement_timeout='2s'")
    db.commit()
    attempted = Event()
    probe_attempted = Event()
    attempts = []
    original = module.operational_evidence.record_account_snapshot

    def record(conn, account, **kwargs):
        attempts.append((conn.execute('SELECT txid_current()').fetchone()[0], kwargs['collector_observed_at']))
        attempted.set()
        original(conn, account, **kwargs)

    def unavailable_probe(*args, **kwargs):
        probe_attempted.set()
        raise RuntimeError('optional probe unavailable')

    monkeypatch.setattr(account_lock_observation, 'start', unavailable_probe)
    monkeypatch.setattr(module.operational_evidence, 'record_account_snapshot', record)
    with psycopg.connect(db.info.dsn) as holder, ThreadPoolExecutor(1) as pool:
        holder.execute("SELECT revision FROM sentinel_operational_read_revisions WHERE scope='PAPER' FOR UPDATE")
        pending = pool.submit(asyncio.run, module.collect(db, config=f.config, reader=f.reader,
                                                          report_reservation_recheck=True))
        try:
            assert attempted.wait(5)
            sleep(2.3)  # longer than the installed statement timeout
        finally:
            holder.rollback()
        assert pending.result(timeout=6) is True
    assert len({tx for tx, _ in attempts}) >= 2
    assert probe_attempted.is_set()
    assert len(f.calls) == 2
    assert db.execute('SELECT observed_at FROM sentinel_broker_account_evidence').fetchall() == [(attempts[0][1],)]
    assert {stamp for _, stamp in attempts} == {attempts[0][1]}
    assert db.execute('SELECT count(*) FROM sentinel_commands').fetchone() == (0,)


def test_account_failure_occurrences_require_successful_periodic_publication(db, issue369_pg, monkeypatch):
    import psycopg
    from sentinel import account_collection_incidents as incidents, execution_collector as collector
    f = fixture(db, monkeypatch)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'collector-test-key-only-'*3)
    monkeypatch.setattr(module, 'PUBLICATION_SECONDS', .3)
    db.commit()

    def poll():
        return collector.collect_once('ACCOUNT', reader=f.reader, config=f.config,
            connection_factory=lambda *a, **k: psycopg.connect(db.info.dsn, options='-c statement_timeout=2000'))

    with psycopg.connect(db.info.dsn) as holder:
        holder.execute("SELECT 1 FROM sentinel_operational_read_revisions WHERE scope='PAPER' FOR UPDATE /*private_canary*/")
        monkeypatch.setattr(module, 'PUBLICATION_SECONDS', 3)
        assert poll() == 'REFUSED'
        monkeypatch.setattr(module, 'PUBLICATION_SECONDS', .3)
        assert poll() == 'REFUSED'
        holder.rollback()
        assert poll() == 'COLLECTED'
        f.account['cash'] = f.account['buying_power'] = '9999.99'
        holder.execute("SELECT 1 FROM sentinel_operational_read_revisions WHERE scope='PAPER' FOR UPDATE")
        assert poll() == poll() == 'REFUSED'
        holder.rollback()
    rows = db.execute("SELECT payload FROM sentinel_alert_outbox WHERE event_type='ACCOUNT_STATUS_COLLECTION_FAILED'"
                      " ORDER BY created_at").fetchall()
    assert len(rows) == 2 and rows[0][0]['occurrence'] != rows[1][0]['occurrence']
    assert all(row[0]['stage'] == 'PERSIST_ACCOUNT' and row[0]['sqlstate'] == '55P03'
               and row[0]['reason'] == 'ACCOUNT_EVIDENCE_LOCK_TIMEOUT' for row in rows)
    assert db.execute('SELECT cash FROM sentinel_broker_account_evidence').fetchall() == [(D('10000'),)]
    episodes = incidents.read_history(db)
    assert [e.occurrences for e in episodes] == [2, 2]
    assert episodes[0].recovered_at is not None and episodes[1].recovered_at is None
    assert all(e.dependency == 'PAPER_REVISION' and e.lock_timeouts >= 2 for e in episodes)
    blocker = episodes[0].blocker
    assert blocker and blocker.blocker_count == 1 and blocker.waiter == 'ACCOUNT_EVIDENCE_INSERT'
    assert blocker.blocker_state == 'IDLE_IN_TRANSACTION' and blocker.blocker_last_statement == 'REVISION_ROW_LOCK'
    assert 'private_canary' not in episodes[0].model_dump_json()
    assert episodes[1].blocker is None  # No second in-flight sample existed to observe.
    assert db.execute("SELECT count(*) FROM sentinel_operational_verification_receipts WHERE scope NOT LIKE 'COLLECTOR:ACCOUNT:%'").fetchone() == (0,)
    db.rollback()
    from tests.support.postgres import paused_physical_restore
    with paused_physical_restore(issue369_pg, db.info.dbname) as restored:
        assert incidents.read_history(restored) == episodes
        assert restored.execute('SELECT count(*) FROM sentinel_commands').fetchone() == (0,)
    db.execute("UPDATE sentinel_operational_verification_receipts SET signature='changed' WHERE scope LIKE 'COLLECTOR:ACCOUNT:%'")
    with pytest.raises(ValueError, match='authentication'):
        incidents.read_history(db)
    db.rollback()


def test_rebound_during_account_publication_rolls_back_evidence_and_revision(db, monkeypatch):
    f = fixture(db, monkeypatch)
    original = module.operational_evidence.record_account_snapshot
    before = db.execute("SELECT revision FROM sentinel_operational_read_revisions WHERE scope='PAPER'").fetchone()
    db.commit()

    def insert_then_rebind(conn, account, **kwargs):
        original(conn, account, **kwargs)
        monkeypatch.setattr(module, '_bound', lambda conn: None)

    monkeypatch.setattr(module.operational_evidence, 'record_account_snapshot', insert_then_rebind)
    with pytest.raises(module.AccountStatusRefused, match='DURABLE_BINDING_CHANGED'):
        collect(db, f)
    assert db.execute('SELECT count(*) FROM sentinel_broker_account_evidence').fetchone() == (0,)
    assert db.execute("SELECT revision FROM sentinel_operational_read_revisions WHERE scope='PAPER'").fetchone() == before


def test_late_periodic_publication_cannot_overtake_newer_account_evidence(db, monkeypatch):
    from dataclasses import replace
    import psycopg
    f = fixture(db, monkeypatch)
    original = module.operational_evidence.record_account_snapshot

    def publish_newer_first(conn, account, **kwargs):
        with psycopg.connect(db.info.dsn) as other:
            original(other, replace(account, account_blocked=True))
        original(conn, account, **kwargs)

    monkeypatch.setattr(module.operational_evidence, 'record_account_snapshot', publish_newer_first)
    assert collect(db, f) is False
    assert db.execute('SELECT flags FROM sentinel_broker_account_evidence ORDER BY seq').fetchall() == [(
        {'trading_blocked':False,'account_blocked':True,'trade_suspended_by_user':False},)]
    assert sources._latest_account_evidence(db)['flags']['account_blocked'] is True


def test_unavailable_recovery_diagnostics_cannot_reverse_successful_publication(db, monkeypatch):
    from sentinel import account_collection_incidents
    f = fixture(db, monkeypatch)

    def broken(conn, **kwargs):
        assert conn.info.transaction_status.name == 'IDLE'
        conn.execute('SELECT 1/0')

    monkeypatch.setattr(account_collection_incidents, 'recover', broken)
    assert asyncio.run(module.collect(db,config=f.config,reader=f.reader,report_reservation_recheck=True)) is True
    assert db.execute('SELECT count(*) FROM sentinel_broker_account_evidence').fetchone() == (1,)


@pytest.mark.parametrize('receipt', ['none', 'locked', 'tampered'])
def test_unavailable_optional_incident_history_never_retries_the_account(db, monkeypatch, receipt):
    import psycopg
    from sentinel import account_collection_incidents as incidents, supervisor_io

    f = fixture(db, monkeypatch)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'collector-test-key-only-'*3)
    warnings = []
    monkeypatch.setattr(supervisor_io, '_pipe_report', warnings.append)
    if receipt != 'none':
        incidents.record_failure(db, stage='PERSIST_ACCOUNT', reason='fixture')
    if receipt == 'tampered':
        db.execute("UPDATE sentinel_operational_verification_receipts SET signature='broken' WHERE scope LIKE 'COLLECTOR:ACCOUNT:%'")
    db.commit()
    with psycopg.connect(db.info.dsn) as holder:
        if receipt == 'locked':
            holder.execute("SELECT 1 FROM sentinel_operational_verification_receipts WHERE scope LIKE 'COLLECTOR:ACCOUNT:%' FOR UPDATE")
        elif receipt == 'none':
            holder.execute('SELECT pg_advisory_xact_lock(%s,%s)', incidents._LOCK)
        assert asyncio.run(module.collect(db, config=f.config, reader=f.reader, report_reservation_recheck=True)) is True
    assert len(f.calls) == 2
    assert db.execute('SELECT count(*) FROM sentinel_broker_account_evidence').fetchone() == (1,)
    assert bool(warnings) == (receipt != 'none')


def test_failed_account_collection_retains_its_original_warning_when_diagnostics_are_unavailable(db, monkeypatch):
    import psycopg
    from sentinel import execution_collector as collector, supervisor_io

    f = fixture(db, monkeypatch)
    db.commit()
    monkeypatch.delenv('SENTINEL_PUBLICATION_RECEIPT_KEY', raising=False)
    diagnostics = []
    monkeypatch.setattr(supervisor_io, '_pipe_report', diagnostics.append)

    class OriginalAccountFailure(Exception):
        pass

    async def unavailable():
        raise OriginalAccountFailure('private_canary')

    monkeypatch.setattr(f.reader, 'account_snapshot', unavailable)
    for _ in range(2):
        assert collector.collect_once('ACCOUNT', reader=f.reader, config=f.config,
            connection_factory=lambda *a, **k: psycopg.connect(db.info.dsn)) == 'REFUSED'
    assert db.execute("SELECT idempotency_key,payload FROM sentinel_alert_outbox").fetchall() == [
        ('account-status-collection:OriginalAccountFailure', {'reason':'OriginalAccountFailure'})]
    assert db.execute('SELECT count(*) FROM sentinel_broker_account_evidence').fetchone() == (0,)
    assert len(diagnostics) == 2 and 'private_canary' not in str(diagnostics)


@pytest.mark.parametrize("field,value", [
    ("account_number", "PAforeign"), ("id", "not-a-uuid"),
    ("currency", "EUR"), ("currency", None), ("cash", "NaN"),
    ("equity", None), ("status", ""), ("trading_blocked", "false"),
])
def test_invalid_or_foreign_account_does_not_refresh_evidence(db, monkeypatch, field, value):
    f = fixture(db, monkeypatch)
    assert collect(db, f)
    retained = db.execute("SELECT seq,observed_at FROM sentinel_broker_account_evidence").fetchall()
    db.rollback()
    f.account[field] = value
    with pytest.raises((ValueError, RuntimeError)):
        collect(db, f)
    db.rollback()
    assert db.execute("SELECT seq,observed_at FROM sentinel_broker_account_evidence").fetchall() == retained


@pytest.mark.parametrize("change", [
    {"account_number": "PAforeign"}, {"id": "22222222-2222-4222-8222-222222222222"},
    {"currency": "EUR"},
])
def test_native_account_must_match_across_reads(db, monkeypatch, change):
    f = fixture(db, monkeypatch)
    f.change.append(change)
    with pytest.raises((ValueError, RuntimeError)):
        collect(db, f)
    db.rollback()
    assert db.execute("SELECT count(*) FROM sentinel_broker_account_evidence").fetchone()[0] == 0


def test_binding_rechecked_after_network_reads(db, monkeypatch):
    f = fixture(db, monkeypatch)
    original = module._bound
    count = 0
    def changed(conn):
        nonlocal count
        count += 1
        result = original(conn)
        return result if count == 1 else (*result[:3], result[3]+1)
    monkeypatch.setattr(module, "_bound", changed)
    with pytest.raises(module.AccountStatusRefused, match="DURABLE_BINDING_CHANGED"):
        collect(db, f)
    db.rollback()
    assert db.execute("SELECT count(*) FROM sentinel_broker_account_evidence").fetchone()[0] == 0


def test_disabled_local_paper_and_live_url_with_paper_binding_never_poll(db, monkeypatch):
    f = fixture(db, monkeypatch)
    monkeypatch.delenv(local_paper.MODE_ENV)
    assert collect(db, f) is False and not f.calls
    from dataclasses import replace
    f.config = replace(f.config, base_url="https://api.alpaca.markets")
    from sentinel.execution.trading_readonly import MonitoringReadRefused
    with pytest.raises(MonitoringReadRefused, match="alpaca-live binding"):
        collect(db, f)
    assert not f.calls


def test_blocked_and_negative_cash_are_visible_facts_not_permission(db, monkeypatch):
    f = fixture(db, monkeypatch)
    f.account.update(cash="-1", trading_blocked=True)
    assert collect(db, f)
    actual = sources._latest_account_evidence(db)
    assert actual["cash"] == -1 and actual["flags"]["trading_blocked"] is True


def test_network_deadline_is_bounded_and_leaves_no_new_evidence(db, monkeypatch):
    f = fixture(db, monkeypatch)
    async def hanging():
        await asyncio.sleep(30)
    monkeypatch.setattr(f.reader, "account_snapshot", hanging)
    monkeypatch.setattr(module, "DEADLINE_SECONDS", .02)
    with pytest.raises(TimeoutError):
        collect(db, f)
    assert db.info.transaction_status.name == "IDLE"
    assert db.execute("SELECT count(*) FROM sentinel_broker_account_evidence").fetchone()[0] == 0


def test_account_identity_guard_falsifier_is_detected(db, monkeypatch):
    source = inspect.getsource(module._observation)
    needle = "    _inspection_account_or_refuse(snapshot, bound[2])"
    last = "    _inspection_account_or_refuse(last, bound[2])"
    assert source.count(needle) == source.count(last) == 1
    namespace = {}
    exec(compile(source.replace(needle, "    pass").replace(last, "    pass"), "<removed-account-identity-guard>", "exec"),
         module._observation.__globals__, namespace)
    monkeypatch.setattr(module, "_observation", namespace["_observation"])
    with pytest.raises(pytest.fail.Exception):
        test_invalid_or_foreign_account_does_not_refresh_evidence(
            db, monkeypatch, "account_number", "PAforeign")


NOW = datetime(2026, 10, 22, 18, 30, tzinfo=timezone.utc)
ASSET = "33333333-3333-4333-8333-333333333333"
ORDER = "22222222-2222-4222-8222-222222222222"


def resting(db, f, *, order_terms=None, filled=0, symbol="PANW", asset=ASSET, native_id=ORDER,
            side=Side.BUY, quantity=D(3), security_id=None, notional=None):
    terms = order_terms or OrderTerms("limit", "day", D("346.91"))
    owner = binding.require(db)
    security_id = security_id or "SEC-" + symbol
    command = Command(CommandIdentity(owner.identity, "plan", security_id),
        BrokerInstrument(security_id, symbol, asset), side, quantity,
        order_terms=terms, notional=notional)
    journal.save_command(db, command)
    sent = command.transition(S.SEND_PENDING)
    journal.save_command(db, sent, previous=S.PLANNED)
    ack = sent.transition(S.ACKNOWLEDGED, broker_order_id=native_id)
    journal.save_command(db, ack, previous=S.SEND_PENDING)
    if filled:
        ack = ack.transition(S.PARTIALLY_FILLED, filled_quantity=D(filled),
                             filled_average_price=D("346.88"))
        journal.save_command(db, ack, previous=S.ACKNOWLEDGED)
    db.commit()
    f.orders.append(dict(id=native_id, client_order_id=command.client_key, asset_id=asset,
        symbol=symbol, side=side.value.lower(), qty=None if quantity is None else str(quantity),
        notional=None if notional is None else str(notional), filled_qty=str(filled),
        status="partially_filled" if filled else "new",
        filled_avg_price="346.88" if filled else None,
        submitted_at=NOW.isoformat(), type=terms.order_type, time_in_force="day",
        limit_price=str(terms.limit_price) if terms.limit_price is not None else None,
        order_class="simple", extended_hours=False))
    return ack


def observed(db):
    actual = sources._latest_account_evidence(db)
    actual["observed_at"] = NOW
    return actual


def account_row(account, proof):
    return model.alpaca_account_row(available=True, expected_account_id="PAfixture",
        matched_operator_reservation=(proof or {}).get("reserved_cash"), **account)


def test_exact_native_resting_hold_explains_cash_for_display_only(db, monkeypatch):
    f = fixture(db, monkeypatch)
    command = resting(db, f)
    assert collect(db, f)
    account = observed(db)
    proof = module.recorded_reservation(db, account=account, now=NOW)
    assert proof["reserved_cash"] == "1040.73"
    row = account_row(account, proof)
    assert row.effective_status(NOW) == model.OK
    assert "freshly matched native LIMIT/DAY buys" in row.detail
    assert row.effective_status(NOW+timedelta(minutes=11)) == model.FAIL
    assert account_row(account, None).effective_status(NOW) == model.FAIL
    retained = journal.load_commands(db, binding.require(db).identity)[0]
    assert module._fact(retained) == module._fact(command)
    assert db.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM sentinel_observations").fetchone()[0] == 0
    monkeypatch.delenv(local_paper.MODE_ENV)
    assert module.recorded_reservation(db, account=account, now=NOW) is None


@pytest.mark.parametrize("field,value", [
    ("id", NATIVE), ("client_order_id", "other"), ("asset_id", NATIVE),
    ("side", "sell"), ("qty", "4"), ("filled_qty", "1"),
    ("status", "canceled"), ("limit_price", "347"), ("time_in_force", "gtc"),
    ("replaces", NATIVE), ("legs", [{"id": "hidden-order"}]),
])
def test_changed_native_order_never_explains_cash(db, monkeypatch, field, value):
    f = fixture(db, monkeypatch)
    resting(db, f)
    f.orders[0][field] = value
    if field == "filled_qty":
        f.orders[0].update(filled_avg_price="346", status="partially_filled")
    collect(db, f)
    account = observed(db)
    assert module.recorded_reservation(db, account=account, now=NOW) is None
    assert account_row(account, None).effective_status(NOW) == model.FAIL


def test_foreign_orders_account_change_and_journal_changes_remove_display_proof(db, monkeypatch):
    f = fixture(db, monkeypatch)
    resting(db, f)
    f.orders.append(dict(f.orders[0], id=NATIVE, client_order_id="foreign"))
    assert collect(db, f)
    assert module.RESERVATION_FLAG not in observed(db)["flags"]
    db.rollback()
    f.orders.pop()
    f.change.append({"cash": "10001"})
    assert collect(db, f)
    assert module.RESERVATION_FLAG not in observed(db)["flags"]
    db.rollback()
    f.change.clear()
    assert collect(db, f)
    account = observed(db)
    assert module.recorded_reservation(db, account=account, now=NOW)
    db.execute("UPDATE sentinel_commands SET state='UNKNOWN'")
    assert module.recorded_reservation(db, account=account, now=NOW) is None


def test_display_match_cannot_hide_invalid_account_economics_or_escape_session(db, monkeypatch):
    f = fixture(db, monkeypatch)
    resting(db, f)
    assert collect(db, f)
    account = observed(db)
    proof = module.recorded_reservation(db, account=account, now=NOW)
    for changes in ({"cash": -1}, {"multiplier": 2}, {"buying_power": -1},
            {"equity": 0}, {"status": "REJECTED"}, {"flags": {"trading_blocked": True}}):
        assert account_row({**account, **changes}, proof).effective_status(NOW) == model.FAIL
    for when in (NOW-timedelta(seconds=1), NOW.replace(hour=21), NOW+timedelta(days=1)):
        assert module.recorded_reservation(db, account=account, now=when) is None
    account["flags"][module.RESERVATION_FLAG]["binding"][-1] += 1
    assert module.recorded_reservation(db, account=account, now=NOW) is None


def test_native_identity_guard_falsifier_is_detected(db, monkeypatch):
    source = inspect.getsource(module._native_orders)
    needle = "return commands if native == expected else None"
    assert source.count(needle) == 1
    namespace = {}
    # Mutant substitutes journal intent for native proof even after a mismatch.
    exec(compile(source.replace(needle, "return commands"), "<removed-native-order-match>", "exec"),
         module._native_orders.__globals__, namespace)
    monkeypatch.setattr(module, "_native_orders", namespace["_native_orders"])
    with pytest.raises(AssertionError):
        test_changed_native_order_never_explains_cash(db, monkeypatch, "id", NATIVE)


def test_second_coherent_read_resolves_reservation_before_publication(db, monkeypatch):
    f = fixture(db, monkeypatch)
    resting(db, f)
    f.account['buying_power'] = '9500'
    read = f.reader.account_snapshot
    snapshots = []

    async def settling_account():
        snapshots.append(True)
        if len(snapshots) == 3:
            f.account['buying_power'] = '8959.27'
        return await read()

    monkeypatch.setattr(f.reader, 'account_snapshot', settling_account)
    assert collect(db, f) is True
    assert len(snapshots) == 4
    account = observed(db)
    assert module.recorded_reservation(db, account=account, now=NOW)['reserved_cash'] == '1040.73'
    assert db.execute('SELECT count(*) FROM sentinel_broker_account_evidence').fetchone() == (1,)


def test_blocked_account_bypasses_reservation_recheck(db, monkeypatch):
    f = fixture(db, monkeypatch)
    resting(db, f)
    f.account.update(buying_power='9500', trading_blocked=True)
    assert collect(db, f) is True
    assert [path for _, path in f.calls].count('/v2/account') == 2
    account = observed(db)
    assert module.recorded_reservation(db, account=account, now=NOW) is None
    assert account_row(account, None).effective_status(NOW) == model.FAIL


def market_order_fixture(db, monkeypatch, *, filled):
    f = fixture(db, monkeypatch)
    monkeypatch.setenv(local_paper.BACKUP_POLICY_ENV, local_paper.BACKUP_POLICY)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", "MARKET_DAY_V1")
    monkeypatch.delenv("SENTINEL_PAPER_BUY_CAP_BPS", raising=False)
    monkeypatch.delenv("SENTINEL_PAPER_DEBUG_WINDOW", raising=False)
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    command = resting(db, f, order_terms=OrderTerms(), filled=filled)
    f.account["buying_power"] = "8930.04"
    return f, command


@pytest.mark.parametrize("filled", [0, 1])
def test_market_order_displays_native_buying_power_without_limit_reservation(db, monkeypatch, filled):
    from dataclasses import replace
    f, command = market_order_fixture(db, monkeypatch, filled=filled)
    assert collect(db, f)
    account = observed(db)
    assert account["flags"][module.RESERVATION_FLAG]["schema"] == module.MARKET_WORKING_SCHEMA
    proof = module.recorded_market_working(db, account=account, now=NOW, plan_id="plan")
    assert proof["orders"] == [module._fact(command)]
    assert "reserved_cash" not in proof
    assert module.recorded_reservation(db, account=account, now=NOW) is None
    assert module.recorded_market_working(db, account=account, now=NOW, plan_id="foreign") is None
    for stamp in (NOW - timedelta(seconds=1), NOW + timedelta(days=1)):
        assert module.recorded_market_working(db, account=account, now=stamp, plan_id="plan") is None

    deadline = NOW + timedelta(seconds=25)
    wait = model.RecoveryEvidence(phase=model.MARKET_BUY_OBSERVATION, automatic=True, deadline=deadline)
    row = model.alpaca_account_row(available=True, expected_account_id="PAfixture",
                                   market_working=wait, **account)
    row = replace(row, paper_account=overview_data.account_overview(account, expected_account_id="PAfixture"))
    assert row.effective_status(NOW) == model.WARN
    assert row.can_show_paper_account(NOW)
    assert "buying power $8,930.04" in row.detail and "reserved" not in row.detail
    assert "Broker buying power</span><strong>$8,930.04" in overview._account_html(
        model.Panel(now=NOW, rows=[row]))
    expired = deadline + timedelta(microseconds=1)
    assert row.effective_status(expired) == model.FAIL
    assert not row.can_show_paper_account(expired)
    for changed in ({"cash": D("-1")}, {"buying_power": D("11000")}, {"multiplier": D("2")},
                    {"flags": {"account_blocked": True}}):
        failed = model.alpaca_account_row(available=True, expected_account_id="PAfixture",
                                         market_working=wait, **{**account, **changed})
        assert failed.effective_status(NOW) == model.FAIL


@pytest.mark.parametrize("fault", ["foreign", "fill_price", "account_moved", "balance_changed",
                                   "unknown", "other_policy"])
def test_market_buy_evidence_requires_exact_owned_native_fills_and_stable_account(db, monkeypatch, fault):
    f, _ = market_order_fixture(db, monkeypatch, filled=1)
    if fault == "foreign":
        f.orders.append(dict(f.orders[0], id=NATIVE, client_order_id="foreign"))
    elif fault == "fill_price":
        f.orders[0]["filled_avg_price"] = "346.89"
    elif fault == "account_moved":
        f.change.append({"buying_power": "8929"})
    assert collect(db, f)
    account = observed(db)
    if fault == "unknown":
        db.execute("UPDATE sentinel_commands SET state='UNKNOWN'")
    elif fault == "balance_changed":
        account["buying_power"] = D("8500")
    elif fault == "other_policy":
        monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY")
    assert module.recorded_market_working(db, account=account, now=NOW, plan_id="plan") is None
    assert account_row(account, None).effective_status(NOW) == model.FAIL


def test_two_native_market_buys_require_a_complete_exact_match(db, monkeypatch):
    f, first = market_order_fixture(db, monkeypatch, filled=1)
    second = resting(db, f, order_terms=OrderTerms(), symbol="VIA",
                     asset="44444444-4444-4444-8444-444444444444",
                     native_id="55555555-5555-4555-8555-555555555555")
    assert collect(db, f)
    proof = module.recorded_market_working(db, account=observed(db), now=NOW, plan_id="plan")
    assert proof["orders"] == sorted(map(module._fact, (first, second)), key=lambda f: f["client_key"])
    f.orders.pop()
    assert collect(db, f)
    assert module.recorded_market_working(db, account=observed(db), now=NOW, plan_id="plan") is None


@pytest.mark.parametrize("fault", [None, "missing_sale", "different_quantity", "different_side", "different_symbol"])
def test_fractional_sales_match_every_native_order_before_explaining_working_exit(db, monkeypatch, fault):
    f = fixture(db, monkeypatch)
    f.account["buying_power"] = f.account["cash"]
    one = resting(db, f, order_terms=OrderTerms(), side=Side.SELL, quantity=D("3.125"), filled=D("0.5"))
    two = resting(db, f, order_terms=OrderTerms(), side=Side.SELL, symbol="VIA",
                  asset="44444444-4444-4444-8444-444444444444", native_id="55555555-5555-4555-8555-555555555555")
    if fault == "missing_sale":
        f.orders.pop()
    elif fault:
        k,v = {"different_quantity": ("qty", "3"), "different_side": ("side", "buy"),
               "different_symbol": ("symbol", "ALIEN")}[fault]
        f.orders[0][k] = v
    assert collect(db, f)
    account = observed(db)
    proof = module.recorded_market_working(db, account=account, now=NOW, plan_id="plan")
    if fault:
        assert proof is None
    else:
        assert proof["orders"] == sorted([{**module._fact(c), "security_id": c.security_id} for c in (one,two)],
                                         key=lambda item: item["client_key"])
    assert module.recorded_reservation(db, account=account, now=NOW) is None


@pytest.mark.parametrize("fault", [None, "missing_basis", "wrong_bil_amount", "unrelated_sale", "excess_hold"])
def test_staged_bil_and_working_sale_require_exact_reservation_and_buying_power(db, monkeypatch, fault):
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID
    from sentinel.execution import market_buy_policy, market_reservation_record
    from sentinel.paper.market_reservations import member
    f = fixture(db, monkeypatch)
    monkeypatch.setenv(local_paper.BACKUP_POLICY_ENV, local_paper.BACKUP_POLICY)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", market_buy_policy.FRACTIONAL_MODE)
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    f.account["buying_power"] = "9950" if fault == "excess_hold" else "9980"
    sale = resting(db, f, order_terms=OrderTerms(), side=Side.SELL, quantity=D("3.125"), filled=D("0.5"))
    bil = resting(db, f, order_terms=OrderTerms(), security_id=DEFENSIVE_SECURITY_ID, symbol="BIL",
                  asset="44444444-4444-4444-8444-444444444444", native_id="55555555-5555-4555-8555-555555555555",
                  quantity=None, notional=D("20"))
    if fault != "missing_basis":
        enrollment = member(bil)
        if fault == "wrong_bil_amount":
            enrollment["notional"] = "21"
        key = "unrelated" if fault == "unrelated_sale" else sale.client_key
        plan = SimpleNamespace(plan_id="plan", effective_session=NOW.date())
        body = {"plan_id": plan.plan_id, "session": NOW.date().isoformat(), "deployment": sale.identity.deployment.to_dict(),
                "members": {bil.client_key: enrollment}, "sales": {key: {"quantity": "0.5", "cash": "173.44"}}}
        market_reservation_record.store(db, plan=plan, body=body)
        db.commit()
    assert collect(db, f)
    account = observed(db)
    proof = module.recorded_market_working(db, account=account, now=NOW, plan_id="plan")
    if fault:
        assert proof is None
    else:
        assert {o["client_key"] for o in proof["orders"]} == {sale.client_key, bil.client_key}
    assert module.recorded_reservation(db, account=account, now=NOW) is None


def test_market_fill_average_match_falsifier(db, monkeypatch):
    source = inspect.getsource(module._fact)
    guard = 'if order.order_terms.order_type == "market":'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, "if False:"), "<ignore-market-fill-price>", "exec"),
         module._fact.__globals__, namespace)
    monkeypatch.setattr(module, "_fact", namespace["_fact"])
    with pytest.raises(AssertionError):
        test_market_buy_evidence_requires_exact_owned_native_fills_and_stable_account(
            db, monkeypatch, "fill_price")

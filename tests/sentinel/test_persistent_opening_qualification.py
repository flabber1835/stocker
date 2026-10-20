"""Falsify the additional asynchronous qualification's clocks and cash evidence."""
from copy import deepcopy
from contextlib import ExitStack, contextmanager
import asyncio
import multiprocessing
import inspect
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from tools import opening_async_provider as provider
from tools import opening_gateway_qualification as gateway
from tools.opening_latency_qualification import QualificationRefused
from tools import opening_persistent_qualification as persistent
from tools.opening_persistent_qualification import assert_async_result


POST = "https://paper-api.alpaca.markets/v2/orders"
ACCOUNT = "https://paper-api.alpaca.markets/v2/account"


@pytest.fixture
def clocked(monkeypatch):
    instant = [datetime(2026, 10, 20, 13, 31, tzinfo=timezone.utc)]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant[0] if tz is not None else instant[0].replace(tzinfo=None)
    monkeypatch.setattr(provider, "datetime", Clock)
    monkeypatch.setattr(gateway, "datetime", Clock)
    monkeypatch.setattr(provider.time, "monotonic", lambda: 1000 + (instant[0] - datetime(
        2026, 10, 20, 13, 31, tzinfo=timezone.utc)).total_seconds())
    assets = {"AAA": {"id": "asset-AAA", "symbol": "AAA", "security_id": "SEC-AAA", "price": D(100)}}
    http = provider.DelayedAlpaca(account="private", cash="10000", assets=assets,
        opened=instant[0]-timedelta(seconds=60), closed=instant[0]+timedelta(hours=6), delay_seconds=40)
    return http, instant


def order(key):
    return {"symbol": "asset-AAA", "qty": "4", "side": "buy", "type": "limit",
        "time_in_force": "day", "client_order_id": key, "order_class": "simple",
        "extended_hours": False, "limit_price": "101"}


def test_zero_ack_cash_order_and_activity_have_independent_visibility(clocked):
    http, instant = clocked
    receipt = http.post(POST, order("one")).json()
    assert receipt["status"] == "new" and receipt["filled_qty"] == "0"
    instant[0] += timedelta(seconds=1)
    snapshot = http.get(ACCOUNT, {}).json()
    assert D(snapshot["cash"]) == 9596 and D(snapshot["buying_power"]) == 9596
    assert http.positions == {} and http.events == []
    rows = http.get(POST, {"status": "all"}).json()
    assert rows[0]["status"] == "partially_filled" and rows[0]["filled_qty"] == "2"
    assert receipt["filled_qty"] == "0", "a returned ACK must not mutate into a later fill"
    instant[0] += timedelta(seconds=20)
    assert http.snapshot()["positions"] == {"asset-AAA": "2"}
    assert len(http.events) == 1
    instant[0] += timedelta(seconds=20)
    snapshot = http.snapshot()
    assert snapshot["positions"] == {"asset-AAA": "4"} and len(http.events) == 2
    assert snapshot["orders"][0]["status"] == "filled" and not snapshot["pending_visibility"]


def test_two_day_orders_rest_and_native_buying_power_is_not_debited_twice(clocked):
    http, instant = clocked
    for key in ("one", "two", "three", "four"):
        http.post(POST, order(key))
    instant[0] += timedelta(seconds=41)
    snapshot = http.snapshot()
    assert snapshot["resting_client_keys"] == ["two", "three"]
    assert D(snapshot["cash"]) == 9192
    assert D(snapshot["reserved_cash"]) == 808 and D(snapshot["buying_power"]) == 8384
    assert snapshot["zero_fill_acknowledgements"] == 4
    assert len(snapshot["positions"]) == 1 and snapshot["positions"]["asset-AAA"] == "8"


def test_post_cutoff_or_duplicate_is_retained_as_failure(clocked):
    http, instant = clocked
    http.post(POST, order("one"))
    with pytest.raises(QualificationRefused, match="DUPLICATE"):
        http.post(POST, order("one"))
    assert http.snapshot()["duplicate_posts"] == 1
    instant[0] = http.cutoff
    with pytest.raises(QualificationRefused, match="LATE_POST"):
        http.post(POST, order("late"))
    assert len(http.orders) == 1 and http.snapshot()["late_posts"] == 1


def successful_snapshot():
    def row(key, filled):
        return {"client_order_id": key, "status": "filled" if filled else "new", "qty": "2",
                "filled_qty": "2" if filled else "0", "filled_avg_price": "100" if filled else None,
                "limit_price": "100"}
    return {"orders": [row("a", True), row("b", False), row("c", False)],
        "duplicate_posts": 0, "late_posts": 0, "zero_fill_acknowledgements": 3,
        "first_order_seconds": 100, "last_post_seconds": 530,
        "resting_client_keys": ["b", "c"], "pending_visibility": 0,
        "initial_cash": "1000", "cash": "800", "buying_power": "400", "reserved_cash": "400",
        "cash_ahead_observations": 1, "partial_order_observations": 1}


def test_async_acceptance_uses_original_cutoff_and_does_not_claim_all_filled():
    assert_async_result(successful_snapshot(), expected_count=3, cutoff_seconds=540)
    with pytest.raises(QualificationRefused, match="CLOCK"):
        assert_async_result(successful_snapshot(), expected_count=3, cutoff_seconds=300)


def test_each_native_shaped_response_has_the_selected_latency_floor(monkeypatch):
    delays, calls = [], []
    async def sleep(seconds):
        delays.append(seconds)
    monkeypatch.setattr(provider.asyncio, "sleep", sleep)
    class Proxy:
        def get(self, url, params):
            calls.append(("GET", url, params))
            return gateway.Response({})
        def post(self, url, body):
            calls.append(("POST", url, body))
            return gateway.Response({})
    shared = provider.SharedProvider(Proxy())
    async def exchange():
        async with shared.AsyncClient() as client:
            await client.get(ACCOUNT)
            await client.post(POST, json={})
    asyncio.run(exchange())
    assert delays == [0.5, 0.5] and [row[0] for row in calls] == ["GET", "POST"]


@pytest.mark.parametrize("value", [0, 0.49, -1, float("inf"), float("nan"), True])
def test_response_latency_floor_cannot_be_disabled(value):
    with pytest.raises(QualificationRefused, match="LATENCY_FLOOR"):
        provider.SharedProvider(None, latency_seconds=value)


@pytest.mark.skipif(sys.platform == "win32", reason="production callback ownership is Linux fork")
def test_independent_callback_processes_share_one_provider_without_roundtrip_resets():
    now = datetime.now(timezone.utc)
    shared, manager = provider.SharedProvider.start(account="private", cash="10000",
        assets={"AAA": {"id": "asset-AAA", "symbol": "AAA", "security_id": "SEC-AAA", "price": D(100)}},
        opened=now-timedelta(seconds=60), closed=now+timedelta(hours=6))
    context = multiprocessing.get_context("fork")
    def submit():
        async def exchange():
            async with shared.AsyncClient() as client:
                result = await client.post(POST, json=order("from-child"))
                assert result.json()["filled_qty"] == "0"
        asyncio.run(exchange())
    def observe():
        async def exchange():
            async with shared.AsyncClient() as client:
                result = await client.get(ACCOUNT)
                assert D(result.json()["cash"]) == D(9596)
        asyncio.run(exchange())
    try:
        for target in (submit, observe):
            child = context.Process(target=target)
            child.start()
            child.join(timeout=10)
            if child.is_alive():
                child.kill()
                child.join(timeout=5)
                pytest.fail("private provider callback child exceeded its test bound")
            assert child.exitcode == 0
        snapshot = shared.proxy.snapshot()
        assert len(snapshot["orders"]) == 1 and snapshot["zero_fill_acknowledgements"] == 1
        assert snapshot["cash_ahead_observations"] == 1
    finally:
        manager.shutdown()


def test_positive_pending_health_only_uses_stable_current_evidence():
    from sentinel.panel import model
    observation = {"stable_evidence": True, "cycle": {"failure_code": None, "failure_detail": None,
        "retry_phase": "EXECUTE", "continuation_reason": {"code": "PROTECTED_COHORT_READY"}},
        "rows": [{"key": "alpaca_account", "status": model.OK},
                 {"key": "automation_cycle", "status": model.WARN},
                 {"key": "automation_step_transport", "status": model.WARN}]}
    assert persistent.require_positive_pending_health(observation)
    observation["rows"][0]["status"] = model.FAIL
    with pytest.raises(QualificationRefused, match="DISPLAYED_FAILED"):
        persistent.require_positive_pending_health(observation)
    observation["stable_evidence"] = False
    assert not persistent.require_positive_pending_health(observation)
    observation["stable_evidence"] = True
    observation["cycle"]["failure_code"] = "TransientInfrastructureFailure"
    assert not persistent.require_positive_pending_health(observation)


@pytest.mark.parametrize("damage", ["unknown", "missing", "duplicate", "unrecognized"])
def test_positive_health_cannot_hide_red_unknown_or_absent_rows(damage):
    from sentinel.panel import model
    value = {"stable_evidence": True, "cycle": {"failure_code": None, "retry_phase": "EXECUTE",
        "continuation_reason": {"code": "PROTECTED_COHORT_READY"}},
        "rows": [{"key": "alpaca_account", "status": model.OK},
                 {"key": "automation_cycle", "status": model.WARN},
                 {"key": "automation_step_transport", "status": model.WARN}]}
    if damage == "unknown": value["rows"][1]["status"] = model.UNKNOWN
    elif damage == "missing": value["rows"].pop()
    elif damage == "duplicate": value["rows"].append(dict(value["rows"][0]))
    else: value["rows"][1]["status"] = "invalid"
    with pytest.raises(QualificationRefused):
        persistent.require_positive_pending_health(value)


def test_monitor_projects_effective_required_current_status():
    from sentinel.panel import model
    now = datetime(2026, 10, 20, 14, tzinfo=timezone.utc)
    row = model.Row("automation_cycle", "cycle", "RETRY_WAIT", model.WARN,
                    as_of=now-timedelta(seconds=5), required_current=True)
    projected = persistent.monitor_row(row, now)
    assert projected["raw_status"] == model.WARN and projected["status"] == model.FAIL
    bounded = model.RecoveryEvidence(phase="PROTECTED_DAY_ORDER_OBSERVATION", automatic=True,
                                    deadline=now+timedelta(seconds=10))
    row = model.Row("automation_cycle", "cycle", "RETRY_WAIT", model.WARN,
                    as_of=now-timedelta(seconds=5), required_current=True, recovery=bounded)
    assert persistent.monitor_row(row, now)["status"] == model.WARN
    assert persistent.monitor_row(row, now+timedelta(seconds=11))["status"] == model.FAIL


def test_raw_status_falsifier_is_detected(monkeypatch):
    source = inspect.getsource(persistent.monitor_row)
    original = "row.effective_status(observed_at)"
    assert source.count(original) == 1
    namespace = {}
    exec(compile(source.replace(original, "row.status"), "<removed-effective-projection>", "exec"),
         vars(persistent), namespace)
    monkeypatch.setattr(persistent, "monitor_row", namespace["monitor_row"])
    with pytest.raises(AssertionError):
        test_monitor_projects_effective_required_current_status()


def test_positive_ready_marker_falsifier_is_detected(monkeypatch):
    source = inspect.getsource(persistent.require_positive_pending_health)
    original = 'cycle.get("continuation_reason")'
    assert source.count(original) == 1
    namespace = {}
    exec(compile(source.replace(original, 'cycle.get("removed_ready_marker")'), "<removed-ready-marker>", "exec"),
         vars(persistent), namespace)
    monkeypatch.setattr(persistent, "require_positive_pending_health", namespace["require_positive_pending_health"])
    with pytest.raises(AssertionError):
        test_positive_pending_health_only_uses_stable_current_evidence()


def test_shared_window_metadata_is_exact_and_never_overwritten(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", "a"*40)
    args = SimpleNamespace(expected_database="opening_latency_private", expected_system_id="12345",
        runtime_image_digest="sha256:"+"b"*64, execution_window_evidence=None,
        monitor_evidence=tmp_path/"private-monitor.json")
    opened = datetime(2026, 10, 20, 14, tzinfo=timezone.utc)
    value = persistent.write_window_evidence(args, session=opened.date(),
                                            window=(opened, opened+timedelta(hours=1)))
    assert persistent.validate_window_evidence(args, value) == (opened, opened+timedelta(hours=1))
    with pytest.raises(FileExistsError):
        persistent.write_window_evidence(args, session=opened.date(),
                                         window=(opened, opened+timedelta(hours=1)))
    for field in ("database", "system_id", "runtime_image_digest", "source_revision"):
        changed = dict(value, **{field: "changed"})
        with pytest.raises(QualificationRefused, match="IDENTITY_MISMATCH"):
            persistent.validate_window_evidence(args, changed)


def test_private_context_has_one_fixed_thirty_minute_budget_and_reuses_admission(monkeypatch):
    from types import SimpleNamespace
    import os
    from sentinel import retained_go, rolling_checkpoint, shadow_budget
    instant = [datetime(2026, 10, 20, 14, tzinfo=timezone.utc)]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return instant[0]
    monkeypatch.setattr(persistent, "datetime", Clock)
    context = {"runtime": {"validated_source_identity_sha256": "a"*64,
                           "validated_shadow_config_sha256": "b"*64}}
    calls = []
    @contextmanager
    def reviewed(conn, args):
        calls.append((conn, args))
        yield context
    monkeypatch.setattr(persistent, "reviewed_runtime", reviewed)
    monkeypatch.setattr(rolling_checkpoint, "read", lambda _conn: SimpleNamespace(
        runtime_identity={"validated_data_publication_sha256": "c"*64}))
    with persistent.persistent_reviewed_runtime("connection", "args") as value:
        assert value is context and calls == [("connection", "args")]
        first = os.environ[shadow_budget.DEADLINE_ENV]
        assert datetime.fromisoformat(first) == instant[0] + timedelta(minutes=30)
        instant[0] += timedelta(minutes=23)
        assert os.environ[shadow_budget.DEADLINE_ENV] == first


@pytest.mark.parametrize("field", ["cycle_id", "updated_at", "account"])
def test_monitor_must_reobserve_both_cycle_and_account_identity(field):
    before = ({"cycle_id": "a", "updated_at": "t"}, {"account": "p"})
    after = deepcopy(before)
    after[1 if field == "account" else 0][field] = "changed"
    assert not persistent.observation_stable(before, after)
    assert persistent.observation_stable(before, deepcopy(before))


@pytest.mark.parametrize("broken_guard", [False, True])
def test_infrastructure_injection_delegates_the_real_guard_and_cannot_fake_refusal(monkeypatch, broken_guard):
    from types import SimpleNamespace
    from sentinel.execution import journal
    held, claims, entered = [False], [], []
    @contextmanager
    def original(connection, **kwargs):
        entered.append(held[0])
        if held[0] and not broken_guard:
            raise journal.WriterLockUnavailable("private test collision")
        yield
    @contextmanager
    def holder(*_args, **_kwargs):
        yield object()
    @contextmanager
    def ownership(*_args, **_kwargs):
        held[0] = True
        try:
            yield
        finally:
            held[0] = False
    def claim(count):
        claims.append(count)
        return len(claims) == 1
    monkeypatch.setattr(journal, "writer_lock", original)
    monkeypatch.setattr(persistent, "connect", holder)
    monkeypatch.setattr(persistent, "read_only_writer", ownership)
    with ExitStack() as stack:
        persistent.contention_fixture(stack, args=object(),
            provider=SimpleNamespace(proxy=SimpleNamespace(claim_contention=claim)), expected_count=15)
        namespace = {"__name__": "sentinel.paper.recovery", "journal": journal}
        exec("def callback():\n with journal.writer_lock(object(),recovery_only=True):\n  pass", namespace)
        expected = QualificationRefused if broken_guard else journal.WriterLockUnavailable
        with pytest.raises(expected):
            namespace["callback"]()
        namespace["callback"]()
    assert entered == [True, False] and claims == [15, 15] and not held[0]


@pytest.mark.parametrize("damage", ["late", "late_attempt", "first", "duplicate", "cash", "reservation", "visibility",
                                   "no_cash_lag", "no_partial", "missing", "fake_filled"])
def test_missing_or_contradictory_composed_evidence_never_passes(damage):
    value = deepcopy(successful_snapshot())
    if damage == "late": value["last_post_seconds"] = 541
    elif damage == "late_attempt": value["late_posts"] = 1
    elif damage == "first": value["first_order_seconds"] = 121
    elif damage == "duplicate": value["orders"][1]["client_order_id"] = "a"
    elif damage == "cash": value["cash"] = "801"
    elif damage == "reservation": value["reserved_cash"] = "200"
    elif damage == "visibility": value["pending_visibility"] = 1
    elif damage == "no_cash_lag": value["cash_ahead_observations"] = 0
    elif damage == "no_partial": value["partial_order_observations"] = 0
    elif damage == "missing": value["orders"].pop()
    elif damage == "fake_filled": value["orders"][1]["status"] = "filled"
    with pytest.raises(QualificationRefused):
        assert_async_result(value, expected_count=3, cutoff_seconds=540)

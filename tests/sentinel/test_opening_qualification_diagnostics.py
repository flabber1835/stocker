"""Failure-only private evidence cannot weaken or mask canonical supervision."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from tools import opening_gateway_qualification as gateway
from tools import opening_latency_qualification as latency


SECRET = "postgresql://secret-user:secret-password@secret-host/private?token=secret-token"


class SecretFailure(RuntimeError):
    sqlstate = "55P03"

    def __str__(self):
        raise AssertionError("diagnostics read a raw exception message")


def test_safe_failure_never_reads_messages_arguments_or_driver_details():
    error = SecretFailure(SECRET)
    error.diag = SimpleNamespace(message_primary=SECRET, statement=SECRET)
    result = latency.safe_failure(error)
    assert result == {"type": "SecretFailure", "module": "external",
                      "sqlstate": "55P03", "domain": "DATABASE_LOCK_UNAVAILABLE"}
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("state", [SECRET, "55P03 secret", "55p03", "", 55, None])
def test_invalid_sqlstates_never_enter_evidence(state):
    error = RuntimeError(SECRET)
    error.sqlstate = state
    assert latency.safe_failure(error)["sqlstate"] is None
    assert SECRET not in json.dumps(latency.safe_failure(error))


def test_broken_driver_properties_do_not_replace_failure_classification():
    class BrokenState(RuntimeError):
        @property
        def sqlstate(self):
            raise SecretFailure(SECRET)

        @property
        def pgcode(self):
            raise SecretFailure(SECRET)

    assert latency.safe_failure(BrokenState(SECRET))["sqlstate"] is None


def test_heartbeat_observers_call_once_return_exact_objects_and_keep_only_four():
    observations = gateway.HeartbeatObservations()
    connection = SimpleNamespace(info=SimpleNamespace(backend_pid=123))
    result = SimpleNamespace(expires_at=datetime.now(timezone.utc))
    calls = []

    def factory(*args, **kwargs):
        calls.append(("factory", args, kwargs))
        return connection

    def renew(*args, **kwargs):
        calls.append(("renew", args, kwargs))
        return result

    factory, renew = observations.factory(factory), observations.renewal(renew)
    for number in range(6):
        assert factory(number, flag=True) is connection
        assert renew(connection, permit=number, callback=True) is result
    assert len(calls) == 12
    assert calls[-2:] == [("factory", (5,), {"flag": True}),
                         ("renew", (connection,), {"permit": 5, "callback": True})]
    rows = observations.rows()
    assert len(rows) == 4
    assert [row["boundary"] for row in rows] == ["HEARTBEAT_CONNECTION", "HEARTBEAT_RENEWAL"] * 2
    assert all(row["result"] == "PASS" and row["backend_pid"] == 123 for row in rows)
    rows[0]["result"] = "changed detached copy"
    assert observations.rows()[0]["result"] == "PASS"


@pytest.mark.parametrize("boundary", ["factory", "renewal"])
def test_heartbeat_failure_is_exact_original_without_retry_or_secret(boundary):
    observations = gateway.HeartbeatObservations()
    original = SecretFailure(SECRET)
    calls = []

    def fail(*args, **kwargs):
        calls.append((args, kwargs))
        raise original

    wrapped = getattr(observations, boundary)(fail)
    with pytest.raises(SecretFailure) as caught:
        wrapped("unchanged", flag=True)
    assert caught.value is original
    assert calls == [(("unchanged",), {"flag": True})]
    assert observations.rows()[-1]["failure"]["sqlstate"] == "55P03"
    assert SECRET not in json.dumps(observations.rows())


def test_observer_failure_cannot_change_original_success_or_failure(monkeypatch):
    observations = gateway.HeartbeatObservations()
    original = RuntimeError(SECRET)
    value = object()

    def broken_record(*args, **kwargs):
        raise SecretFailure(SECRET)

    def fail():
        raise original

    monkeypatch.setattr(observations, "_record", broken_record)
    assert observations.factory(lambda: value)() is value
    with pytest.raises(RuntimeError) as caught:
        observations.factory(fail)()
    assert caught.value is original


def stub_supervision(monkeypatch, *, failure=None):
    from sentinel.automation import store
    from sentinel.automation.model import ExecuteResult, ExecuteDisposition
    from sentinel.automation.service import AutomationService
    returned = ExecuteResult(disposition=ExecuteDisposition.SUCCEEDED,
                             last_clean_reconciliation_id="private-unit-observation")
    calls = []

    async def invoke(self, *_args, **_kwargs):
        calls.append("invoke")
        if failure is not None:
            raise failure
        return {"result": returned.model_dump(mode="json"), "provider": {}, "counts": {}}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    def connection(_args, *, read_only, heartbeat):
        calls.append(("connect", read_only, heartbeat))
        return Connection()

    monkeypatch.setattr(AutomationService, "_invoke", invoke)
    monkeypatch.setattr(gateway, "connect", connection)
    monkeypatch.setattr(store, "register_instance", lambda *_args, **_kwargs: calls.append("idle"))
    context = SimpleNamespace(permit=SimpleNamespace(holder_id="private-test"))
    http = SimpleNamespace(restore=lambda value: calls.append(("restore", value)))
    return context, http, calls


def test_success_adds_no_snapshot_query_or_failure_report(monkeypatch, capsys):
    from sentinel.automation.model import AutomationConfig
    context, http, calls = stub_supervision(monkeypatch)

    def forbidden(*_args, **_kwargs):
        pytest.fail("passing callback attempted failure-only diagnostics")

    monkeypatch.setattr(gateway, "callback_failure_snapshot", forbidden)
    result = gateway.supervised_callback(None, AutomationConfig(), context, "RECOVER", None, http, Counter())
    assert result.disposition.value == "SUCCEEDED"
    assert calls == ["invoke", ("restore", {}), ("connect", False, True), "idle"]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("secondary", ["snapshot", "collector", "cleanup", "snapshot_and_cleanup"])
def test_failed_collector_or_cleanup_preserves_exact_primary(monkeypatch, capsys, secondary):
    from sentinel.automation import store
    from sentinel.automation.model import AutomationConfig
    original = SecretFailure(SECRET)
    context, http, calls = stub_supervision(monkeypatch, failure=original)

    def fail(*_args, **_kwargs):
        raise RuntimeError(SECRET)

    if secondary == "collector":
        monkeypatch.setattr(gateway, "report_callback_failure", fail)
    elif "snapshot" in secondary:
        monkeypatch.setattr(gateway, "callback_failure_snapshot", fail)
    else:
        monkeypatch.setattr(gateway, "callback_failure_snapshot", lambda *_args: {"private": True})
    if "cleanup" in secondary:
        monkeypatch.setattr(store, "register_instance", fail)
    with pytest.raises(SecretFailure) as caught:
        gateway.supervised_callback(None, AutomationConfig(), context, "RECOVER", None, http, Counter())
    assert caught.value is original
    assert calls[0] == "invoke"
    assert SECRET not in capsys.readouterr().out


def test_cleanup_failure_after_success_still_refuses(monkeypatch):
    from sentinel.automation import store
    from sentinel.automation.model import AutomationConfig
    context, http, _calls = stub_supervision(monkeypatch)
    original = RuntimeError(SECRET)

    def fail(*_args, **_kwargs):
        raise original

    monkeypatch.setattr(store, "register_instance", fail)
    with pytest.raises(RuntimeError) as caught:
        gateway.supervised_callback(None, AutomationConfig(), context, "RECOVER", None, http, Counter())
    assert caught.value is original


def test_failure_snapshot_is_private_read_only_bounded_and_omits_query_text(monkeypatch):
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, statement, parameters):
            calls.append((statement, parameters))
            return SimpleNamespace(fetchone=lambda: ({"database_clock": "actual"},))

    args = object()

    def connection(actual, **kwargs):
        assert actual is args
        calls.append(kwargs)
        return Connection()

    monkeypatch.setattr(gateway, "connect", connection)
    context = SimpleNamespace(permit=SimpleNamespace(holder_id=SECRET))
    assert gateway.callback_failure_snapshot(args, context) == {"database_clock": "actual"}
    assert calls[0] == {"read_only": True, "heartbeat": True}
    statement, parameters = calls[1]
    assert statement.startswith("SELECT ") and len(calls) == 2
    assert "LIMIT 8" in statement and "blocker_pids" in statement
    assert "application_name" not in statement and "query," not in statement
    assert SECRET not in statement and parameters == (SECRET, SECRET)


def test_snapshot_connection_keeps_existing_private_identity_and_timeout_bounds(monkeypatch):
    import psycopg
    calls = []
    args = SimpleNamespace(private_rehearsal=True, expected_database="opening_latency_diagnostics_unit",
        expected_system_id="12345678901", production_system_id="98765432101",
        runtime_image_digest="sha256:" + "a" * 64, repetitions=3,
        database="dbname=opening_latency_diagnostics_unit")
    conn = SimpleNamespace(execute=lambda *_args: SimpleNamespace(fetchone=lambda: (
        args.expected_database, args.expected_system_id, "on")))

    def connect(dsn, **kwargs):
        calls.append((dsn, kwargs))
        return conn

    monkeypatch.setattr(psycopg, "connect", connect)
    assert latency.connect(args, read_only=True, heartbeat=True) is conn
    assert calls == [(args.database, {"connect_timeout": 3, "options":
        "-c default_transaction_read_only=on -c statement_timeout=3000 "
        "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=3000"})]


def test_reporting_keeps_primary_and_observed_renewal_classification(monkeypatch, capsys):
    observations = gateway.HeartbeatObservations()
    renewal_error = SecretFailure(SECRET)

    def fail(_conn):
        raise renewal_error

    with pytest.raises(SecretFailure):
        observations.renewal(fail)(None)
    monkeypatch.setattr(gateway, "callback_failure_snapshot", lambda *_args: {"private": True})
    gateway.report_callback_failure(None, None, "PREPARE", RuntimeError(SECRET), observations)
    report = json.loads(capsys.readouterr().out)
    assert report["failure"]["type"] == "RuntimeError"
    assert report["heartbeat_observations"][-1]["failure"]["sqlstate"] == "55P03"
    assert SECRET not in json.dumps(report)


def test_original_exception_falsifier_detects_removed_cleanup_guard(monkeypatch, capsys):
    import inspect
    import textwrap
    from sentinel.automation import store
    from sentinel.automation.model import AutomationConfig
    original = SecretFailure(SECRET)
    secondary = RuntimeError("exact secondary cleanup failure")
    context, http, calls = stub_supervision(monkeypatch, failure=original)

    def snapshot_failure(*_args):
        raise ValueError(SECRET)

    def cleanup_failure(*_args, **_kwargs):
        raise secondary

    monkeypatch.setattr(gateway, "callback_failure_snapshot", snapshot_failure)
    monkeypatch.setattr(store, "register_instance", cleanup_failure)
    source = textwrap.dedent(inspect.getsource(gateway.supervised_callback))
    marker = "if primary is None:"
    assert source.count(marker) == 1
    # Compile only after the real fixture seams are installed: the mutant must
    # use this invocation's connection rather than a stale copied global.
    namespace = dict(gateway.__dict__)
    exec(compile(source.replace(marker, "if True:"), "cleanup-guard-falsifier", "exec"), namespace)
    with pytest.raises(RuntimeError) as caught:
        namespace["supervised_callback"](None, AutomationConfig(), context, "RECOVER", None, http, Counter())
    assert caught.value is secondary
    assert caught.value.__context__ is original
    assert calls == ["invoke", ("connect", False, True)]
    assert SECRET not in capsys.readouterr().out


def test_snapshot_read_only_guard_has_a_falsifier(monkeypatch):
    from contextlib import nullcontext
    import inspect
    import textwrap
    args, calls = object(), []
    expected = AssertionError("snapshot lost its read-only connection")
    reader = SimpleNamespace(execute=lambda *_args: SimpleNamespace(fetchone=lambda: ({"private": True},)))

    def connection(actual, *, read_only, heartbeat):
        assert actual is args
        calls.append((read_only, heartbeat))
        if not read_only:
            raise expected
        return nullcontext(reader)

    monkeypatch.setattr(gateway, "connect", connection)
    source = textwrap.dedent(inspect.getsource(gateway.callback_failure_snapshot))
    marker = "connect(args, read_only=True, heartbeat=True)"
    assert source.count(marker) == 1
    namespace = dict(gateway.__dict__)
    exec(compile(source.replace(marker, "connect(args, read_only=False, heartbeat=True)"),
                 "snapshot-readonly-falsifier", "exec"), namespace)
    context = SimpleNamespace(permit=SimpleNamespace(holder_id="private-test"))
    with pytest.raises(AssertionError) as caught:
        namespace["callback_failure_snapshot"](args, context)
    assert caught.value is expected
    assert calls == [(False, True)]


def test_observation_bound_has_a_falsifier(monkeypatch):
    import inspect
    import textwrap
    source = textwrap.dedent(inspect.getsource(gateway.HeartbeatObservations))
    assert source.count("deque(maxlen=4)") == 1
    namespace = dict(gateway.__dict__)
    exec(compile(source.replace("deque(maxlen=4)", "deque()"),
                 "observation-bound-falsifier", "exec"), namespace)
    monkeypatch.setattr(gateway, "HeartbeatObservations", namespace["HeartbeatObservations"])
    with pytest.raises(AssertionError):
        test_heartbeat_observers_call_once_return_exact_objects_and_keep_only_four()


def test_sqlstate_filter_has_a_secret_nonleak_falsifier(monkeypatch):
    import inspect
    import textwrap
    source = textwrap.dedent(inspect.getsource(latency.safe_failure))
    marker = 'if type(value) is str and re.fullmatch(r"[0-9A-Z]{5}", value):'
    assert source.count(marker) == 1
    namespace = dict(latency.__dict__)
    exec(compile(source.replace(marker, "if type(value) is str:"),
                 "sqlstate-filter-falsifier", "exec"), namespace)
    monkeypatch.setattr(latency, "safe_failure", namespace["safe_failure"])
    with pytest.raises(AssertionError):
        test_invalid_sqlstates_never_enter_evidence(SECRET)


def test_canonical_supervisor_refuses_real_heartbeat_row_lock_and_reaps_child(monkeypatch, capfd):
    import ctypes
    import os
    import psycopg
    from sentinel import schema
    from sentinel.automation import service, store
    from sentinel.automation.model import (
        AutomationConfig, CancellationAuthority, ControlBinding, StaleLeaderRefused,
    )
    from tests.support.postgres import _EphemeralPostgres
    server = _EphemeralPostgres()
    server.start()
    try:
        config = AutomationConfig(lease_seconds=3, heartbeat_seconds=1, callback_deadline_seconds=8)

        def connection(_args, *, read_only, heartbeat):
            assert heartbeat
            return psycopg.connect(server.sync_dsn, connect_timeout=3,
                options="-c statement_timeout=3000 -c lock_timeout=1000 "
                        "-c default_transaction_read_only=" + ("on" if read_only else "off"))

        monkeypatch.setattr(gateway, "connect", connection)
        reaped = []
        original_kill = service._kill_callback_process

        def observed_kill(process, **kwargs):
            result = original_kill(process, **kwargs)
            if process is not None:
                reaped.append((process.pid, process.is_alive(), process.exitcode))
            return result

        monkeypatch.setattr(service, "_kill_callback_process", observed_kill)
        with psycopg.connect(server.sync_dsn) as conn:
            schema.ensure_schema(conn)
            binding = ControlBinding(deployment_id="private-diagnostics", broker="alpaca-paper",
                broker_account_id="local-only", takeover_epoch=1, certificate_sha256="c" * 64,
                rollout_mode="PINNED_1_00", rollout_version=1, config_sha256=config.fingerprint)
            store.activate(conn, binding=binding, actor="test", reason="local-only")
            store.release_kill(conn, expected_binding=binding, actor="test", reason="local-only")
            permit = store.acquire_lease(conn, holder_id="private-heartbeat-diagnostics", lease_seconds=3)
            cancellation = CancellationAuthority()
            context = SimpleNamespace(permit=permit, cancellation=cancellation,
                                      require_active=cancellation.require_active)
            now = datetime.now(timezone.utc)
            http = gateway.LocalAlpaca(account="local-only", cash="100", assets={},
                window=lambda: (now, now + timedelta(hours=1)))

            async def body(_context):
                with psycopg.connect(server.sync_dsn) as locker:
                    row = locker.execute("SELECT instance_id FROM sentinel_automation_service_instances "
                        "WHERE instance_id=%s FOR UPDATE", (permit.holder_id,)).fetchone()
                    assert row == (permit.holder_id,)
                    ctypes.PyDLL(None).sleep(5)  # Real row ownership outlives the 1s lock bound.
                    pytest.fail("lost heartbeat must kill the callback before it resumes")

            with pytest.raises(StaleLeaderRefused):
                gateway.supervised_callback(None, config, context, "PREPARE", body, http, Counter())
            output = capfd.readouterr().out
            reports = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
            report = next(row for row in reports if row.get("stage") == "CALLBACK_FAILURE_DIAGNOSTICS")
            assert report["failure"]["type"] == "StaleLeaderRefused"
            failures = [row for row in report["heartbeat_observations"] if row["result"] == "REFUSED"]
            assert failures[-1]["boundary"] == "HEARTBEAT_RENEWAL"
            assert failures[-1]["failure"]["sqlstate"] == "55P03"
            assert report["snapshot_result"] == "PASS"
            assert report["snapshot"]["instance"]["state"] == "PREPARE_CALLBACK"
            assert reaped and all(not alive for _pid, alive, _exit in reaped)
            assert any(exitcode == -9 for _pid, _alive, exitcode in reaped)
            assert conn.execute("SELECT state FROM sentinel_automation_service_instances "
                "WHERE instance_id=%s", (permit.holder_id,)).fetchone() == ("IDLE",)
            assert os.getpid() == report["parent_pid"]
    finally:
        server.stop()

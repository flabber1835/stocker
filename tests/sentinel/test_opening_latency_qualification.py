"""The profiler must refuse production access before verifier execution."""
from argparse import Namespace
from contextlib import nullcontext
import json
from types import SimpleNamespace

import pytest

from tools import opening_latency_qualification as tool


def target(**values):
    return Namespace(**({"private_rehearsal": True, "expected_database": "rehearsal",
        "expected_system_id": "12345678901", "production_system_id": "98765432101",
        "runtime_image_digest": "sha256:" + "a" * 64, "repetitions": 3} | values))


@pytest.mark.parametrize("change", [
    {"private_rehearsal": False}, {"expected_database": "sentinel"},
    {"expected_database": "postgres"}, {"expected_database": "rehearsal;UPDATE x"},
    {"expected_system_id": "98765432101"}, {"expected_system_id": ""},
    {"production_system_id": ""}, {"runtime_image_digest": "sentinel:latest"},
    {"repetitions": 0}, {"repetitions": 11},
    {"minimum_bars": 1},
])
def test_target_requires_distinct_named_private_physical_cluster(change):
    with pytest.raises(tool.QualificationRefused):
        tool.require_target(target(**change))


@pytest.mark.parametrize("name", ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "OPENFIGI_API_KEY",
                                    "SHARADAR_API_KEY", "NDL_API_KEY", "REHEARSAL_PRODUCTION_DATABASE_URL"])
def test_credentials_or_production_connection_environment_refuses(name):
    with pytest.raises(tool.QualificationRefused, match="ENVIRONMENT_PRESENT"):
        tool.require_environment({name: "secret", "SENTINEL_IMAGE_SOURCE_REVISION": "a" * 40},
                                 "/app/sentinel/__init__.py")


@pytest.mark.parametrize("path,revision", [("/candidate/sentinel/__init__.py", "a" * 40),
                                           ("/app/sentinel/__init__.py", "unknown")])
def test_overlay_or_unknown_image_revision_refuses(path, revision):
    with pytest.raises(tool.QualificationRefused):
        tool.require_environment({"SENTINEL_IMAGE_SOURCE_REVISION": revision}, path)


def test_empty_provider_environment_and_exact_image_are_admitted():
    tool.require_environment({"ALPACA_API_KEY": "", "SENTINEL_IMAGE_SOURCE_REVISION": "a" * 40},
                             "/app/sentinel/__init__.py")
    tool.require_target(target())


@pytest.mark.parametrize("row", [("sentinel", "12345678901", "on"),
                                 ("rehearsal", "98765432101", "on"),
                                 ("rehearsal", "12345678901", "off")])
def test_actual_database_and_read_only_state_must_match(row):
    conn = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: row))
    with pytest.raises(tool.QualificationRefused, match="IDENTITY_MISMATCH"):
        tool.require_database(conn, target())


def test_connect_forces_read_only_and_closes_wrong_cluster(monkeypatch):
    import psycopg
    seen = {}
    closed = []
    conn = SimpleNamespace(close=lambda: closed.append(True), execute=lambda *_:
        SimpleNamespace(fetchone=lambda: ("sentinel", "98765432101", "on")))
    def connect(dsn, **kwargs):
        seen.update(dsn=dsn, **kwargs)
        return conn
    monkeypatch.setattr(psycopg, "connect", connect)
    args = target(database="dbname=rehearsal options='-c default_transaction_read_only=off'")
    with pytest.raises(tool.QualificationRefused):
        tool.connect(args)
    assert "default_transaction_read_only=on" in seen["options"]
    assert closed == [True]


def test_production_connection_string_refuses_before_connect(monkeypatch):
    import psycopg
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: pytest.fail("connected to primary"))
    with pytest.raises(tool.QualificationRefused, match="PRIVATE_DATABASE_CONNECTION_REQUIRED"):
        tool.connect(target(database="dbname=sentinel"))


def test_writes_require_explicit_mutation_flag_and_dedicated_namespace(monkeypatch):
    import psycopg
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: pytest.fail("opened writable connection"))
    with pytest.raises(tool.QualificationRefused, match="PRIVATE_MUTATION_NAMESPACE"):
        tool.connect(target(database="dbname=rehearsal", mutate_private_rehearsal=True), read_only=False)
    with pytest.raises(tool.QualificationRefused, match="PRIVATE_MUTATION_NAMESPACE"):
        tool.connect(target(database="dbname=opening_latency_foo", expected_database="opening_latency_foo",
                            mutate_private_rehearsal=False), read_only=False)


@pytest.mark.parametrize("fail", [False, True])
def test_writer_scope_uses_real_nonblocking_key_and_releases_after_failure(fail):
    calls = []
    def execute(sql, params):
        calls.append((sql, params))
        return SimpleNamespace(fetchone=lambda: (True,))
    conn = SimpleNamespace(execute=execute, rollback=lambda: calls.append("rollback"))
    with pytest.raises(RuntimeError) if fail else nullcontext():
        with tool.read_only_writer(conn, 1234):
            calls.append("body")
            if fail:
                raise RuntimeError("cancelled")
    assert calls == [("SELECT pg_try_advisory_lock(%s)", (1234,)), "body", "rollback",
                     ("SELECT pg_advisory_unlock(%s)", (1234,)), "rollback"]


def test_busy_writer_refuses_before_body():
    conn = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: (False,)))
    with pytest.raises(tool.QualificationRefused, match="LOCK_BUSY"):
        with tool.read_only_writer(conn, 1234):
            pytest.fail("busy writer was entered")


def test_stages_record_real_failure_without_promoting_pass():
    times = iter([10.0, 11.0, 12.0, 14.0])
    stages = tool.Stages(clock=lambda: next(times))
    assert stages.run("one", lambda: "value") == "value"
    with pytest.raises(ValueError):
        stages.run("two", lambda: (_ for _ in ()).throw(ValueError("secret")))
    assert stages.rows == [{"stage": "one", "result": "PASS", "seconds": 1.0},
        {"stage": "two", "result": "REFUSED", "seconds": 2.0, "error_type": "ValueError"}]


def test_failure_report_retains_no_dsn_or_exception_message(monkeypatch, tmp_path, capsys):
    def refused(*_):
        raise RuntimeError("postgresql://user:secret@production/sentinel")
    monkeypatch.setattr(tool, "benchmark", refused)
    output = tmp_path / "profile.json"
    argv = ["--database", "dbname=private", "--expected-database", "rehearsal",
        "--expected-system-id", "12345678901", "--production-system-id", "98765432101",
        "--runtime-image-digest", "sha256:" + "a" * 64, "--private-rehearsal", "--output", str(output)]
    assert tool.main(argv) == 1
    report = json.loads(output.read_text())
    assert report["result"] == "REFUSED" and report["error_type"] == "RuntimeError"
    assert "secret" not in output.read_text() + capsys.readouterr().out
    with pytest.raises(FileExistsError):
        tool.main(argv)


def test_local_provider_refuses_unimplemented_or_foreign_routes():
    from tools.opening_gateway_qualification import LocalAlpaca
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    provider = LocalAlpaca(account="private", cash="1000", assets={},
                           window=lambda: (now, now + timedelta(hours=1)))
    with pytest.raises(tool.QualificationRefused, match="UNKNOWN_ENDPOINT"):
        provider.get("https://example.org/v2/account", {})
    with pytest.raises(tool.QualificationRefused, match="UNIMPLEMENTED_READ"):
        provider.get("https://paper-api.alpaca.markets/unexpected", {})
    with pytest.raises(tool.QualificationRefused, match="UNEXPECTED_MUTATION"):
        provider.post("https://paper-api.alpaca.markets/v2/orders", {})


def test_local_provider_drives_actual_sealed_asset_adapter_and_rejects_duplicate_post():
    import asyncio
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    import time
    from pathlib import Path
    from sentinel.config import DEFAULT_BASE_URL, SentinelConfig, build_execution_broker
    from sentinel.execution.contract import Side
    from sentinel.execution.feed_inputs import BrokerSecurityResolver
    from tools.opening_gateway_qualification import LocalAlpaca
    now = datetime.now(timezone.utc)
    provider = LocalAlpaca(account="private", cash="1000", assets={"PBR.A": {
        "id": "asset-class", "symbol": "PBR.A", "security_id": "SEC-CLASS", "price": Decimal("10")}},
        window=lambda: (now - timedelta(seconds=60), now + timedelta(hours=1)))
    resolver = BrokerSecurityResolver("ALPACA_OPENFIGI", lambda symbol, *_: "SEC-CLASS",
                                     {"SEC-CLASS": "asset-class"})
    broker = build_execution_broker(SentinelConfig(alpaca_key="fixture", alpaca_secret="fixture",
        base_url=DEFAULT_BASE_URL, state_dir=Path("/tmp/fixture"), max_cycles=1, poll_seconds=0),
                                   resolve_security_id=resolver)
    broker._http_provider = lambda: provider
    instrument = asyncio.run(broker.resolve_instrument(security_id="SEC-CLASS", symbol="PBR.A"))
    provider.started = time.monotonic()
    outcome = asyncio.run(broker.submit(client_key="fixture-key", instrument=instrument,
                                       side=Side.BUY, quantity=Decimal(2)))
    assert outcome.state.value == "ACKNOWLEDGED"
    assert provider.cash == Decimal("980") and provider.positions == {"asset-class": Decimal(2)}
    assert next(iter(provider.orders.values()))["symbol"] == "PBR.A"
    assert len(provider.events) == 1 and provider.first_order_seconds is not None
    with pytest.raises(tool.QualificationRefused, match="DUPLICATE_POST"):
        provider.post("https://paper-api.alpaca.markets/v2/orders", {
            "symbol": "asset-class", "qty": "2", "side": "buy", "client_order_id": "fixture-key"})


@pytest.mark.parametrize("function,guard,invoke", [
    ("require_target", "if args.expected_system_id == args.production_system_id:",
     lambda broken: broken(target(expected_system_id="98765432101"))),
    ("require_environment", 'if Path(sentinel_file).resolve().parent != Path("/app/sentinel"):',
     lambda broken: broken({"SENTINEL_IMAGE_SOURCE_REVISION": "a" * 40}, "/candidate/sentinel/__init__.py")),
    ("require_database", 'if actual != (args.expected_database, args.expected_system_id, "on" if read_only else "off"):',
     lambda broken: broken(SimpleNamespace(execute=lambda *_:
         SimpleNamespace(fetchone=lambda: ("sentinel", "98765432101", "on"))), target())),
])
def test_falsifier_detects_removed_private_target_runtime_and_read_only_guards(function, guard, invoke):
    import inspect
    import textwrap
    source = textwrap.dedent(inspect.getsource(getattr(tool, function)))
    broken = source.replace(guard, "if False:")
    assert broken != source
    namespace = {}
    exec(compile(broken, "removed-private-qualification-guard", "exec"), vars(tool), namespace)
    with pytest.raises(pytest.fail.Exception):
        with pytest.raises(tool.QualificationRefused):
            invoke(namespace[function])

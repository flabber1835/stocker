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


def fixture_resolver(identities, provider_ids, provider="ALPACA_OPENFIGI"):
    from sentinel.execution.feed_inputs import BrokerSecurityResolver
    return BrokerSecurityResolver(provider, lambda symbol, *_: identities.get(symbol), provider_ids)


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


def test_heartbeat_connections_have_bounds_below_deployed_lease(monkeypatch):
    import psycopg
    seen = {}
    conn = SimpleNamespace(close=lambda: None, execute=lambda *_:
        SimpleNamespace(fetchone=lambda: ("opening_latency_test", "12345678901", "off")))
    def connect(dsn, **kwargs):
        seen.update(kwargs)
        return conn
    monkeypatch.setattr(psycopg, "connect", connect)
    tool.connect(target(database="dbname=opening_latency_test", expected_database="opening_latency_test",
                        mutate_private_rehearsal=True), read_only=False, heartbeat=True)
    assert seen["connect_timeout"] == 3
    assert "statement_timeout=3000" in seen["options"] and "lock_timeout=1000" in seen["options"]


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


def test_fixture_asset_inventory_uses_real_needed_deltas_and_ignores_zero_unheld_legs():
    from decimal import Decimal
    from tools.opening_gateway_qualification import fixture_assets
    plan = SimpleNamespace(target_basket={"stock": Decimal(2), "defensive": Decimal(0)},
                           target_exposure=Decimal(1), opening_intents=())
    proof = {"marks": {"stock": "10", "defensive": "50"},
             "tickers": {"stock": "CLASS.A", "defensive": "DEFENSIVE"}}
    assert fixture_assets(plan, proof, fixture_resolver({"CLASS.A": "stock"}, {"stock": "bound-provider-id"})) == {
        "CLASS.A": {"id": "bound-provider-id", "symbol": "CLASS.A",
                    "security_id": "stock", "price": Decimal(10), "identity_origin": "authenticated-source"}}


@pytest.mark.parametrize("opening_intent", [False, True])
def test_fixture_missing_needed_positive_or_opening_intent_identity_refuses(opening_intent):
    from decimal import Decimal
    from tools.opening_gateway_qualification import fixture_assets
    plan = SimpleNamespace(target_basket={"needed": Decimal(0 if opening_intent else 2)},
        target_exposure=Decimal(1), opening_intents=(SimpleNamespace(security_id="needed"),) if opening_intent else ())
    proof = {"marks": {"needed": "10"}, "tickers": {"needed": "NEEDED"}}
    with pytest.raises(tool.QualificationRefused, match="MISSING_NEEDED_AUTHENTICATED"):
        fixture_assets(plan, proof, fixture_resolver({"NEEDED": "needed"}, {}),
                       {"needed": {"id": "unbound", "symbol": "NEEDED"}})


def test_defensive_asset_uses_explicit_provider_metadata_and_retained_price():
    from decimal import Decimal
    from tools.opening_gateway_qualification import fixture_assets
    plan = SimpleNamespace(target_basket={"SENTINEL:BIL": Decimal(2)},
                           target_exposure=Decimal(1), opening_intents=())
    proof = {"marks": {"SENTINEL:BIL": "91.12"}, "tickers": {"SENTINEL:BIL": "BIL"}}
    resolver = fixture_resolver({"BIL": "SENTINEL:BIL"}, {})
    metadata = {"SENTINEL:BIL": {"id": "d46254d7-ab54-4715-ac7a-4a7bfd640416", "symbol": "BIL"}}
    with pytest.raises(tool.QualificationRefused, match="MISSING_NEEDED_PROVIDER_METADATA"):
        fixture_assets(plan, proof, resolver)
    asset = fixture_assets(plan, proof, resolver, metadata)["BIL"]
    assert asset["price"] == Decimal("91.12") and asset["id"] == metadata["SENTINEL:BIL"]["id"]
    assert asset["identity_origin"] == "GET-only-provider-metadata"
    with pytest.raises(tool.QualificationRefused, match="MISSING_NEEDED_AUTHENTICATED"):
        fixture_assets(plan, {**proof, "marks": {}}, resolver, metadata)


def test_sharadar_metadata_still_requires_canonical_symbol_resolution():
    from decimal import Decimal
    from tools.opening_gateway_qualification import fixture_assets
    plan = SimpleNamespace(target_basket={"canonical": Decimal(2)},
                           target_exposure=Decimal(1), opening_intents=())
    proof = {"marks": {"canonical": "10"}, "tickers": {"canonical": "AAA"}}
    metadata = {"canonical": {"id": "fixture-broker-id", "symbol": "AAA"}}
    resolver = fixture_resolver({"AAA": "canonical"}, {}, provider="SHARADAR")
    assert fixture_assets(plan, proof, resolver, metadata)["AAA"]["id"] == "fixture-broker-id"
    with pytest.raises(tool.QualificationRefused, match="SOURCE_IDENTITY_MISMATCH"):
        fixture_assets(plan, proof, fixture_resolver({"AAA": "other"}, {}, provider="SHARADAR"), metadata)


def test_metadata_cannot_override_source_bound_stock_id():
    from decimal import Decimal
    from tools.opening_gateway_qualification import fixture_assets
    plan = SimpleNamespace(target_basket={"stock": Decimal(2)}, target_exposure=Decimal(1), opening_intents=())
    proof = {"marks": {"stock": "10"}, "tickers": {"stock": "AAA"}}
    asset = fixture_assets(plan, proof, fixture_resolver({"AAA": "stock"}, {"stock": "bound"}),
                           {"stock": {"id": "incorrect", "symbol": "AAA"}})["AAA"]
    assert asset["id"] == "bound" and asset["identity_origin"] == "authenticated-source"


def test_provider_metadata_loader_rejects_invalid_native_asset_metadata(tmp_path):
    from tools.opening_gateway_qualification import provider_metadata
    value = {"schema": "sentinel.local-provider-asset-metadata/1", "method": "GET",
        "endpoint": "https://paper-api.alpaca.markets/v2/assets/BIL", "captured_at": "2026-10-19T14:47:00+00:00",
        "assets": [{"security_id": "SENTINEL:BIL", "id": "d46254d7-ab54-4715-ac7a-4a7bfd640416",
                    "symbol": "BIL", "status": "active", "tradable": True}]}
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(value))
    rows, digest = provider_metadata(path)
    assert rows["SENTINEL:BIL"]["symbol"] == "BIL" and len(digest) == 64
    value["assets"][0]["tradable"] = False
    path.write_text(json.dumps(value))
    with pytest.raises(tool.QualificationRefused, match="INVALID_PROVIDER_METADATA"):
        provider_metadata(path)


def test_local_clock_preserves_immutable_future_open():
    from datetime import datetime, timedelta, timezone
    from tools.opening_gateway_qualification import LocalAlpaca
    opened = datetime.now(timezone.utc) + timedelta(minutes=5)
    provider = LocalAlpaca(account="private", cash="1000", assets={},
                           window=lambda: (opened, opened + timedelta(hours=1)))
    clock = provider.get("https://paper-api.alpaca.markets/v2/clock", {}).json()
    assert clock["is_open"] is False and clock["next_open"] == opened.isoformat()


def test_execution_window_proxy_preserves_real_shadow_and_preopen_witness_calendars():
    from contextlib import ExitStack
    from datetime import date, timedelta, timezone
    from sentinel import shadow_observation
    from sentinel.automation import schedule
    from sentinel.automation.model import AutomationConfig
    from sentinel.feed import calendar
    from sentinel.paper import targets, validation
    from tools.opening_gateway_qualification import execution_window_fixture
    effective = date(2026, 10, 19)
    original = calendar.session_window(effective)
    friday = calendar.session_window("2026-10-16")
    window = (original[1] + timedelta(hours=1), original[1] + timedelta(hours=2))
    raw = {"schema": "sentinel.shadow-activation-timing/1", "decision_session": "2026-10-16",
        "execution_session": effective.isoformat(), "observed_at": "2026-10-16T21:00:00Z",
        "candidate_committed_at": "2026-10-16T21:00:01Z",
        "execution_open_at": original[0].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": shadow_observation.BEFORE_NEXT_OPEN}
    with ExitStack() as stack:
        proxy = execution_window_fixture(stack, effective, window)
        assert calendar.session_window(effective) == original
        assert proxy.session_window(effective) == original  # unknown immediate caller
        assert shadow_observation._timing_proof(raw, decision_session="2026-10-16", committed=True,
                                              where="shadow activation timing") == raw
        assert targets._official_preopen_cutoff(SimpleNamespace(effective_session=effective)) == original[0]
        spec = schedule.for_decision_session("2026-10-16", AutomationConfig())
        assert spec.execution_open_at == window[0] and spec.execution_close_at == window[1]
        assert spec.decision_close_at == friday[1]
        validation._execution_window_or_refuse(effective, window[0] + timedelta(minutes=1))
    assert schedule.calendar is calendar and calendar.session_window("2026-10-16") == friday


def test_canonical_supervisor_renews_registered_callback_and_roundtrips_only_provider_state(monkeypatch):
    import ctypes
    import os
    from collections import Counter
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    import psycopg
    from sentinel import schema
    from sentinel.automation import store
    from sentinel.automation.model import (AutomationConfig, CancellationAuthority, ControlBinding,
        ExecuteDisposition, ExecuteResult, StaleLeaderRefused)
    from tests.support.postgres import _EphemeralPostgres
    from tools import opening_gateway_qualification as gateway
    server = _EphemeralPostgres()
    server.start()
    try:
        config = AutomationConfig(lease_seconds=3, heartbeat_seconds=1, callback_deadline_seconds=8)
        def connection(_args, *, read_only, heartbeat):
            assert not read_only and heartbeat
            return psycopg.connect(server.sync_dsn, connect_timeout=3,
                                  options="-c statement_timeout=3000 -c lock_timeout=1000")
        monkeypatch.setattr(gateway, "connect", connection)
        with psycopg.connect(server.sync_dsn) as conn:
            schema.ensure_schema(conn)
            binding = ControlBinding(deployment_id="private-fixture", broker="alpaca-paper",
                broker_account_id="local-only", takeover_epoch=1, certificate_sha256="c" * 64,
                rollout_mode="PINNED_1_00", rollout_version=1, config_sha256=config.fingerprint)
            store.activate(conn, binding=binding, actor="test", reason="local-only")
            store.release_kill(conn, expected_binding=binding, actor="test", reason="local-only")
            permit = store.acquire_lease(conn, holder_id="private-callback-test", lease_seconds=config.lease_seconds)
            now = datetime.now(timezone.utc)
            http = gateway.LocalAlpaca(account="local-only", cash="100", assets={},
                                       window=lambda: (now, now + timedelta(hours=1)))
            counts = Counter()
            def context():
                cancellation = CancellationAuthority()
                return SimpleNamespace(permit=permit, cancellation=cancellation,
                                       require_active=cancellation.require_active)
            async def body(_context):
                # PyDLL deliberately retains the child's GIL beyond the initial
                # lease; the canonical parent heartbeat must remain independent.
                ctypes.PyDLL(None).sleep(4)
                with psycopg.connect(server.sync_dsn) as child_conn:
                    assert store.require_leader(child_conn, permit).expires_at > permit.expires_at
                    row = child_conn.execute("SELECT state,callback_started_at IS NOT NULL,callback_deadline_at IS NOT NULL "
                        "FROM sentinel_automation_service_instances WHERE instance_id=%s", (permit.holder_id,)).fetchone()
                    assert row == ("RECOVER_CALLBACK", True, True)
                http.cash -= Decimal("2.50")
                http.positions["local-asset"] = Decimal(1)
                http.requests["local-request"] += 1
                counts["local-invocation"] += 1
                return ExecuteResult(disposition=ExecuteDisposition.RECONCILE, diagnostic={"child_pid": os.getpid()})
            result = gateway.supervised_callback(None, config, context(), "RECOVER", body, http, counts)
            assert result.diagnostic["child_pid"] != os.getpid()
            assert http.cash == Decimal("97.50") and http.positions == {"local-asset": Decimal(1)}
            assert http.requests == {"local-request": 1} and counts == {"local-invocation": 1}
            assert conn.execute("SELECT state,callback_started_at,callback_deadline_at "
                "FROM sentinel_automation_service_instances WHERE instance_id=%s",
                (permit.holder_id,)).fetchone() == ("IDLE", None, None)
            conn.rollback()
            with monkeypatch.context() as broken:
                broken.setattr(store, "register_instance", lambda *_a, **_kw: None)
                with pytest.raises(StaleLeaderRefused, match="callback instance is missing"):
                    gateway.supervised_callback(None, config, context(), "RECOVER", body, http, counts)
    finally:
        server.stop()


def test_local_provider_drives_actual_sealed_asset_adapter_and_rejects_duplicate_post():
    import asyncio
    from contextlib import ExitStack
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    import time
    from pathlib import Path
    from sentinel.config import DEFAULT_BASE_URL, SentinelConfig, build_execution_broker
    from sentinel.execution.contract import Side
    from sentinel.execution.feed_inputs import BrokerSecurityResolver
    from tools.opening_gateway_qualification import LocalAlpaca, execution_window_fixture
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
    session = now.date()
    with ExitStack() as stack:
        execution_window_fixture(stack, session, provider.window())
        quotes = asyncio.run(broker.opening_prices(session=session, instruments={"SEC-CLASS": instrument}))
        assert quotes.opening_at == provider.window()[0] and quotes.prices == {"SEC-CLASS": Decimal("10")}
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

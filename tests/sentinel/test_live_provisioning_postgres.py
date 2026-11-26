"""Real private Postgres verifies the attended binding/control transaction edge."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sentinel import automation_runtime, binding
from sentinel.authority.canonical import canonical_json_bytes
from sentinel.authority import live_provisioning as provisioning
from sentinel.automation import store
from sentinel.automation.health import read_health
from sentinel.config import SentinelConfig
from sentinel.execution import journal
from tests.sentinel.test_binding_and_handover import conn, pg  # noqa: F401
from tests.sentinel.test_live_provisioning import bind, setup
from tests.sentinel.test_live_runtime_authority import runtime_fixture


def _fixture(conn, monkeypatch):
    # Reuse only the in-memory signing/HTTP fixture; restore every fake store
    # before exercising the actual database, writer lock and ownership journal.
    with monkeypatch.context() as isolated:
        fixture = setup(isolated)
    fixture.conn = conn
    # Backup qualification has its own real-provider acceptance tests. This
    # explicitly supplies that port; no production media or backup is touched.
    monkeypatch.setattr(journal.backup_runtime_authority, 'require', lambda *_, **__: None)
    return fixture


@pytest.mark.asyncio
async def test_empty_live_binding_and_ownership_are_one_real_transaction(conn, monkeypatch):
    fixture = _fixture(conn, monkeypatch)
    try:
        actual = await bind(fixture)
        assert actual.broker == 'alpaca-live' and actual == binding.require(conn)
        events = conn.execute('SELECT state,detail FROM sentinel_ownership_events').fetchall()
        assert len(events) == 1
        assert events[0][1]['provisioning_certificate_sha256']
        assert events[0][1]['environment'] == 'ALPACA_LIVE'
        control = store.load_control(conn)
        assert not control.enabled and control.kill_switch_engaged and control.binding is None
        before = list(fixture.trace)
        with pytest.raises(provisioning.AuthorityRefused, match='existing account binding'):
            await bind(fixture)
        assert fixture.trace == before
    finally:
        await fixture.http.aclose()


@pytest.mark.asyncio
async def test_failure_between_ownership_and_binding_loses_both_real_rows(conn, monkeypatch):
    fixture = _fixture(conn, monkeypatch)
    def refused(*_, **__):
        assert conn.execute('SELECT count(*) FROM sentinel_ownership_events').fetchone()[0] == 1
        raise RuntimeError('injected binding failure')
    monkeypatch.setattr(provisioning.binding, 'bind', refused)
    try:
        with pytest.raises(RuntimeError, match='injected binding failure'):
            await bind(fixture)
        assert binding.load(conn) is None
        assert conn.execute('SELECT count(*) FROM sentinel_ownership_events').fetchone()[0] == 0
    finally:
        await fixture.http.aclose()


@pytest.mark.asyncio
async def test_real_control_requires_two_separate_confirmed_transitions(conn, monkeypatch):
    fixture = _fixture(conn, monkeypatch)
    try:
        await bind(fixture)
        monkeypatch.setattr(provisioning, 'require_current_live_authority',
                            lambda *_, **__: SimpleNamespace(sha256='a' * 64))
        context = dict(base_url=fixture.subject.base_url, runtime_identity={}, strategy_identity={},
            automation_config_sha256='b' * 64, confirm_live_account=fixture.subject.account_id,
            confirm_deployment=fixture.subject.deployment_id, confirm_real_money=True,
            actor='offline-owner', reason='offline qualified authority interface')
        activated = provisioning.activate_live_automation(conn, **context)
        assert activated.enabled and activated.kill_switch_engaged
        assert activated.binding.broker == 'alpaca-live'
        with pytest.raises(provisioning.AuthorityRefused, match='real-money'):
            provisioning.release_live_kill(conn, **{**context, 'confirm_real_money': False})
        assert store.load_control(conn).kill_switch_engaged
        released = provisioning.release_live_kill(conn, **context)
        assert released.enabled and not released.kill_switch_engaged
        assert released.generation > activated.generation
    finally:
        await fixture.http.aclose()


@pytest.mark.asyncio
async def test_first_live_idle_wake_records_pass_and_revocation_fences_current_control(
        pg, conn, monkeypatch, tmp_path):
    enrollment = _fixture(conn, monkeypatch)
    try:
        await bind(enrollment)
    finally:
        await enrollment.http.aclose()
    monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY", raising=False)
    monkeypatch.delenv("SENTINEL_PAPER_BUY_CAP_BPS", raising=False)
    monkeypatch.delenv("SENTINEL_PAPER_DEBUG_WINDOW", raising=False)
    monkeypatch.setenv("ALPACA_BASE_URL", enrollment.subject.base_url)
    with monkeypatch.context() as isolated:
        signed = runtime_fixture(tmp_path, isolated)
    assert signed.subject == enrollment.subject
    for name, value in signed.env.items():
        monkeypatch.setenv(name, value)
    automation_config = automation_runtime.config_from_env()
    sentinel_config = replace(SentinelConfig.from_env({}), database_url=pg.sync_dsn,
                              base_url=signed.subject.base_url)
    activation = dict(base_url=signed.subject.base_url, runtime_identity=signed.runtime,
                      strategy_identity=signed.strategy, automation_config_sha256=automation_config.fingerprint,
                      confirm_live_account=signed.subject.account_id, confirm_deployment=signed.subject.deployment_id,
                      confirm_real_money=True, actor="offline-owner", reason="signed offline lifecycle")
    provisioning.activate_live_automation(conn, **activation)
    control = provisioning.release_live_kill(conn, **activation)
    permit = store.acquire_lease(conn, holder_id="live-worker", lease_seconds=30)
    store.register_instance(conn, instance_id=permit.holder_id, state="WAITING", next_wake_at=None)
    initial = read_health(conn)
    assert initial.authority_lifecycle_current and not initial.operational_ready
    assert initial.policy_state == "AUTHORITY_UNVERIFIED"

    monkeypatch.setattr(automation_runtime.system_identity, "rehearsal_identity", lambda: signed.runtime)
    monkeypatch.setattr(automation_runtime, "production_strategy", lambda: (None, signed.strategy))
    monkeypatch.setattr(automation_runtime.feed_inputs, "require_current", lambda _: SimpleNamespace(version=7))
    monkeypatch.setattr(automation_runtime.feed_inputs, "coherent", lambda _: None)
    worker_type = automation_runtime.ProductionAutomation
    monkeypatch.setattr(worker_type, "_idle_publication_head", lambda *_, **__: {"version": 7})
    worker = worker_type(sentinel_config=sentinel_config, automation_config=automation_config,
                         holder_id=permit.holder_id)
    notices = []

    async def notify(_conn, result):
        notices.append(result.action)

    class InlineObserver:
        # Run the real child proof on its separate read-only Postgres connection.
        # Only its process transport and the input/identity fixtures are local.
        progress = [0, 0]

        def submit(self, flight, observer_permit):
            flight.value = automation_runtime._observe_idle_control_authority(
                sentinel_config, automation_config, permit.holder_id, observer_permit, self.progress)
            flight.finished.set()

    worker.notify = notify
    worker._idle_authority_observer = InlineObserver()
    await worker.control_wake(conn)
    ready = read_health(conn)
    assert ready.policy_state == "LEADER_ACTIVE" and ready.operational_ready
    assert ready.authority_mode == "ALPACA_LIVE"
    assert ready.authority_verdict == "PASS" and ready.authority_expires_at
    assert ready.control_generation == control.generation and not notices

    signed.enrollment["revoked_certificate_sha256"] = [control.certificate_sha256]
    signed.roots_path.write_bytes(canonical_json_bytes(signed.enrollment))
    invalid = read_health(conn)
    assert invalid.policy_state == "AUTHORITY_INVALID" and not invalid.operational_ready
    await worker.control_wake(conn)
    fenced = store.load_control(conn)
    assert fenced.kill_switch_engaged and fenced.generation > control.generation
    assert read_health(conn).policy_state == "KILLED"
    assert notices == ["BLOCKED"]

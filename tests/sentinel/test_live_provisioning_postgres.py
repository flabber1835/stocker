"""Real private Postgres verifies the attended binding/control transaction edge."""
from types import SimpleNamespace

import pytest

from sentinel import binding
from sentinel.authority import live_provisioning as provisioning
from sentinel.automation import store
from sentinel.execution import journal
from tests.sentinel.test_binding_and_handover import conn, pg  # noqa: F401
from tests.sentinel.test_live_provisioning import bind, setup


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

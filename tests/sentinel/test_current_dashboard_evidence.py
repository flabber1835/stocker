"""Counterexamples from the activated deployment; no broker or alternate book."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sentinel.panel import sources, model
from test_panel import TestRuntimeRowsAreDurableFacts as RuntimeFixture
from test_automation_store import conn, pg, enable

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


class Rows:
    def __init__(self, rows):
        self.rows = rows
        self.sql = []
    def cursor(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def execute(self, sql, params=None):
        self.sql.append((sql, params))
    def fetchall(self):
        return self.rows


def test_account_reader_uses_canonical_ownership_without_broker_access():
    from sentinel.binding import SENTINEL_OWNED
    conn = Rows([('fixture-account',)])
    assert sources._bound_account_id(conn) == 'fixture-account'
    assert conn.sql[0][1] == (SENTINEL_OWNED,)
    assert "ownership_state=%s" in conn.sql[0][0]
    assert sources._bound_account_id(Rows([])) is None
    with pytest.raises(ValueError, match='not unique'):
        sources._bound_account_id(Rows([('one',), ('two',)]))


@pytest.mark.parametrize('mode', ['PAPER_OBSERVATION_ONLY', 'historical'])
def test_actual_certificate_claim_shape_projects_reviewed_identity(mode):
    claims = {'authorization_mode': mode}
    key = 'bindings' if mode == 'PAPER_OBSERVATION_ONLY' else 'deployment_artifacts'
    claims[key] = {'git_commit': 'a'*40, 'runtime_image_digest': 'sha256:'+'b'*64}
    conn = Rows([(11, 'c'*64, NOW, NOW, 'ACTIVE', claims, False, False, True)])
    row = sources._authority_lifecycle(conn)
    assert row['reviewed_git_commit'] == 'a'*40
    assert row['reviewed_image_digest'] == 'sha256:'+'b'*64


@pytest.mark.parametrize('bindings', [None, [], 'unreadable'])
def test_standing_claims_cannot_borrow_a_historical_identity(bindings):
    claims = {'authorization_mode': 'PAPER_OBSERVATION_ONLY', 'bindings': bindings,
              'deployment_artifacts': {'git_commit': 'a'*40}}
    conn = Rows([(11, 'c'*64, NOW, NOW, 'ACTIVE', claims, False, False, True)])
    with pytest.raises(ValueError, match='unreadable'):
        sources._authority_lifecycle(conn)


def test_contradictory_signed_runtime_claims_are_refused():
    claims = {'authorization_mode': 'PAPER_OBSERVATION_ONLY',
              'bindings': {'git_commit': 'a'*40},
              'deployment_artifacts': {'git_commit': 'b'*40}}
    conn = Rows([(11, 'c'*64, NOW, NOW, 'ACTIVE', claims, False, False, True)])
    with pytest.raises(ValueError, match='disagree'):
        sources._authority_lifecycle(conn)


def test_ignoring_contradictory_signed_identity_is_detected(monkeypatch):
    import inspect, textwrap
    body = textwrap.dedent(inspect.getsource(sources._authority_lifecycle))
    broken = body.replace('raise ValueError("signed runtime identity claims disagree")', 'pass')
    assert broken != body
    namespace = {}
    exec(compile(broken, 'contradictory-identity-falsifier', 'exec'), sources.__dict__, namespace)
    monkeypatch.setattr(sources, '_authority_lifecycle', namespace['_authority_lifecycle'])
    with pytest.raises(pytest.fail.Exception):
        test_contradictory_signed_runtime_claims_are_refused()


@pytest.mark.parametrize('defect', [None, 'session', 'exposure', 'rollout', 'unverified', 'version'])
def test_verified_shadow_book_is_sole_current_book_and_plan_must_agree(monkeypatch, defect):
    from sentinel.core.session import ENVELOPE_VERSION
    state = RuntimeFixture._state()
    state['version'] = ENVELOPE_VERSION if defect != 'version' else ENVELOPE_VERSION+1
    result = SimpleNamespace(session='2026-08-12', state=SimpleNamespace(to_dict=lambda: state))
    plan = dict(decision_session='2026-08-12', effective_session='2026-08-13',
                target_exposure=.55, rollout_mode='CONTROLLER', rollout_version=2,
                rollout_certificate_sha256='fixture-controller', created_at=NOW,
                unpriced_securities=[])
    rollout = dict(mode='CONTROLLER', version=2, certificate_sha256='fixture-controller')
    if defect == 'session':
        plan['decision_session'] = '2026-08-11'
    elif defect == 'exposure':
        plan['target_exposure'] = .56
    elif defect == 'rollout':
        plan['rollout_version'] = 3
    monkeypatch.setattr(sources, '_current_plan', lambda conn: plan)
    monkeypatch.setattr(sources, '_rollout_state', lambda conn: rollout)
    monkeypatch.setattr(sources, '_canonical_state', lambda conn: pytest.fail('legacy book consulted'))
    rows, errors = sources._verified_shadow_book_rows(object(), result,
        verified=defect != 'unverified', now=NOW)
    by_key = {row.key: row for row in rows}
    if defect is None:
        assert not errors
        assert by_key['book'].value.startswith('1/2 slots · NAV $1,000')
        assert by_key['exposure'].value == '0.55'
        assert by_key['terminals'].value == 'CLEAR'
    else:
        assert all(row.status == model.UNKNOWN for row in rows)


def test_dual_runtime_broker_reader_does_not_consult_legacy_book(monkeypatch):
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual')
    helper = RuntimeFixture()
    helper._install_sources(monkeypatch, observation={'observed_at': NOW,
        'completeness': 'COMPLETE', 'positions': {}, 'orders': [], 'runtime_state': 'RUNNING'},
        commands={'counts': {}, 'updated_at': NOW})
    for name in ('_canonical_state', '_current_plan', '_rollout_state'):
        monkeypatch.setattr(sources, name, lambda conn: pytest.fail('alternate book queried'))
    rows, errors = sources._runtime_rows('fixture')
    assert not errors and [row.key for row in rows] == ['broker']


def test_real_sql_identity_changes_on_book_or_control_but_not_heartbeats(conn, pg):
    from sentinel.feed.schema import DDL
    from sentinel.panel.authority_reader import _evidence
    from sentinel.automation import store
    from sentinel.automation.model import AutomationConfig
    for statement in DDL:
        conn.execute(statement)
    conn.commit()
    before = _evidence(pg.sync_dsn, True)
    enable(conn, AutomationConfig())
    enabled = _evidence(pg.sync_dsn, True)
    assert before != enabled
    permit = store.acquire_lease(conn, holder_id='fixture', lease_seconds=30)
    store.register_instance(conn, instance_id='fixture', state='WAITING', next_wake_at=None)
    store.heartbeat_lease(conn, permit=permit, lease_seconds=30)
    assert _evidence(pg.sync_dsn, True) == enabled
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                 "VALUES ('fixture-book','2026-10-09','{}'::jsonb)")
    conn.commit()
    book = _evidence(pg.sync_dsn, True)
    assert book != enabled
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb "
                 "WHERE cursor_name='fixture-book'", ('{"changed":true}',))
    conn.commit()
    assert _evidence(pg.sync_dsn, True) != book
    store.engage_kill(conn, actor='test', reason='test evidence invalidation')
    assert _evidence(pg.sync_dsn, True) != book


def test_removing_row_version_invalidation_is_detected(conn, pg, monkeypatch):
    import inspect
    import textwrap
    from sentinel.panel import authority_reader
    body = textwrap.dedent(inspect.getsource(authority_reader._evidence))
    broken = body.replace('cursor_name,session,xmin::text,ctid::text', 'cursor_name,session')
    assert broken != body
    namespace = {}
    exec(compile(broken, 'missing-row-version-falsifier', 'exec'), authority_reader.__dict__, namespace)
    monkeypatch.setattr(authority_reader, '_evidence', namespace['_evidence'])
    with pytest.raises(AssertionError):
        test_real_sql_identity_changes_on_book_or_control_but_not_heartbeats(conn, pg)

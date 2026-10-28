"""Counterexamples from the activated deployment; no broker or alternate book."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sentinel.panel import sources, model
from test_panel import TestRuntimeRowsAreDurableFacts as RuntimeFixture
from test_automation_store import enable
from test_operational_catalog_integration import conn, cluster

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


@pytest.mark.parametrize('defect', [None, 'session', 'future_session', 'exposure', 'rollout', 'unverified', 'version'])
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
        plan['unpriced_securities'] = ['UNRELATED-OLDER-PLAN']
    elif defect == 'future_session':
        plan['decision_session'] = '2026-08-13'
        plan['unpriced_securities'] = ['UNRELATED-FUTURE-PLAN']
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
    elif defect in {'session', 'future_session'}:
        assert not errors
        assert by_key['book'].value.startswith('1/2 slots · NAV $1,000')
        assert by_key['book'].status == model.OK
        assert 'UNPRICED' not in by_key['book'].detail
        assert by_key['exposure'].value == '0.55 NOT ADOPTED'
        assert by_key['exposure'].status == model.WARN
        assert by_key['terminals'].value == 'CLEAR'
    else:
        assert all(row.status == model.UNKNOWN for row in rows)


def test_unrelated_plan_session_filter_has_a_removed_guard_falsifier(monkeypatch):
    import inspect
    body = inspect.getsource(sources._verified_shadow_book_rows)
    guard = 'plan["decision_session"] != view["session"]'
    assert body.count(guard) == 1
    namespace = {}
    exec(compile(body.replace(guard, 'False'), '<unrelated-plan-session-falsifier>', 'exec'),
         sources.__dict__, namespace)
    monkeypatch.setattr(sources, '_verified_shadow_book_rows', namespace['_verified_shadow_book_rows'])
    with pytest.raises(AssertionError):
        test_verified_shadow_book_is_sole_current_book_and_plan_must_agree(monkeypatch, 'session')


@pytest.mark.parametrize('mode', ['shadow', 'dual'])
def test_dual_runtime_broker_reader_does_not_consult_legacy_book(monkeypatch, mode):
    from sentinel import paper_plan_preview

    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', mode)
    helper = RuntimeFixture()
    _sources, connection = helper._install_sources(monkeypatch, observation={'observed_at': NOW,
        'completeness': 'COMPLETE', 'positions': {}, 'orders': [], 'runtime_state': 'RUNNING'},
        commands={'counts': {}, 'updated_at': NOW})
    preview_reads = []
    def read_preview(conn):
        assert conn is connection
        preview_reads.append(conn)
        return None
    monkeypatch.setattr(paper_plan_preview, 'read', read_preview)
    for name in ('_canonical_state', '_current_plan', '_rollout_state'):
        monkeypatch.setattr(sources, name, lambda conn: pytest.fail('alternate book queried'))
    rows, errors = sources._runtime_rows('dbname=fixture')
    assert not errors
    assert [row.key for row in rows] == (['broker', 'paper_plan'] if mode == 'dual' else ['broker'])
    assert len(preview_reads) == (1 if mode == 'dual' else 0)
    if mode == 'dual':
        assert rows[1].value == 'NOT PREPARED'
        assert rows[1].status == model.PENDING


def test_real_sql_identity_changes_on_book_or_control_but_not_heartbeats(conn):
    from sentinel import operational_schema
    from sentinel.panel.authority_reader import _evidence
    from sentinel.automation import store
    from sentinel.automation.model import AutomationConfig
    operational_schema.install_quiescent(conn)
    database_url = conn.info.dsn
    before = _evidence(database_url, True)
    enable(conn, AutomationConfig())
    enabled = _evidence(database_url, True)
    assert before != enabled
    permit = store.acquire_lease(conn, holder_id='fixture', lease_seconds=30)
    store.register_instance(conn, instance_id='fixture', state='WAITING', next_wake_at=None)
    store.heartbeat_lease(conn, permit=permit, lease_seconds=30)
    assert _evidence(database_url, True) == enabled
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                 "VALUES ('fixture-book','2026-10-09','{}'::jsonb)")
    conn.commit()
    book = _evidence(database_url, True)
    assert book != enabled
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb "
                 "WHERE cursor_name='fixture-book'", ('{"changed":true}',))
    conn.commit()
    updated = _evidence(database_url, True)
    assert updated != book
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name='fixture-book'")
    conn.commit()
    deleted = _evidence(database_url, True)
    assert deleted != updated and deleted != enabled
    store.engage_kill(conn, actor='test', reason='test evidence invalidation')
    assert _evidence(database_url, True) != deleted


def test_removing_row_version_invalidation_is_detected(conn, monkeypatch):
    import inspect
    import textwrap
    from sentinel.panel import read_projection
    body = textwrap.dedent(inspect.getsource(read_projection._subject))
    # Keep the installation's stable incarnation while removing the actual
    # revision and row-version inputs, which now own constant-size invalidation.
    guard = 'list(row),list(physical)'
    assert body.count(guard) == 1
    broken = body.replace(guard, '[row[0]],list(physical)', 1)
    namespace = {}
    exec(compile(broken, 'missing-row-version-falsifier', 'exec'), read_projection.__dict__, namespace)
    monkeypatch.setattr(read_projection, '_subject', namespace['_subject'])
    with pytest.raises(AssertionError):
        test_real_sql_identity_changes_on_book_or_control_but_not_heartbeats(conn)

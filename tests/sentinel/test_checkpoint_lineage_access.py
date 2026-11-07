"""Authenticated access-path installation preserves the complete lineage guard."""
from contextlib import closing
from types import SimpleNamespace

import pytest

from sentinel import checkpoint_lineage_access as access, operational_schema, schema
from sentinel.feed import store
from tests.sentinel.test_operational_catalog_integration import cluster, conn  # noqa: F401


PARAMS = dict(allowed_names=['rolling-cold-start:v1', 'rolling-daily-checkpoint:v1',
                            'shadow-observation:v1:primary:genesis'],
              session_pattern='shadow-observation:v1:primary:session:%',
              input_pattern='rolling-daily-input:v1:primary:%',
              authority_pattern='shadow-rolling-runtime:v1:primary:%')


@pytest.fixture
def predecessor(conn, monkeypatch):
    # Reproduce the actual installed predecessor without manufacturing a new
    # version of its immutable marker or contracts map.
    with monkeypatch.context() as prior:
        prior.setattr(operational_schema, 'ACCESS_PATH_COMPONENTS', ())
        original = operational_schema.install_quiescent(conn)
    assert access.require_schema(conn, allow_absent=True) is False
    conn.rollback()
    return original


def put(conn, name, raw='{}'):
    conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) '
                 "VALUES (%s,'2026-11-05',%s::jsonb)", (name, raw))


def test_daily_loader_keeps_the_guard_at_its_existing_admission_boundary(monkeypatch):
    from sentinel import rolling_daily_checkpoint as daily, runtime_admission
    context = dict(strategy={'strategy': 'unchanged'}, runtime={'runtime': 'unchanged'},
                   observation_id='primary', starting_cash='50000')
    initial = SimpleNamespace(model_dump=lambda **_kw: {'original': 'checkpoint'},
                              genesis_sha256='a'*64, warmup_input_identity={})
    checkpoint = SimpleNamespace(origin_sha256=daily.digest(initial.model_dump()),
        genesis_sha256=initial.genesis_sha256, warmup_input_identity={},
        observation_id='primary', starting_cash='50000', strategy_identity=context['strategy'],
        runtime_identity=context['runtime'], session='2026-11-05')
    selected = []
    monkeypatch.setattr(runtime_admission, 'bind_context', lambda *_args: None)
    monkeypatch.setattr(daily.origin, 'read', lambda *_args: initial)
    monkeypatch.setattr(daily, 'read', lambda *_args: checkpoint)
    monkeypatch.setattr(daily.shadow, 'PostgresShadowObservationStore', lambda *_args, **_kw:
                        SimpleNamespace(_genesis_name=PARAMS['allowed_names'][2],
                                        prefix='shadow-observation:v1:primary:'))
    def foreign(_conn, **parameters):
        selected.append(parameters)
        return ('unfamiliar-paper:v1',)
    monkeypatch.setattr(access, 'find_foreign', foreign)
    monkeypatch.setattr(daily, 'require_input', lambda *_args: pytest.fail('foreign guard was bypassed'))
    def refuse():
        with pytest.raises(daily.Refused, match='DAILY_CHECKPOINT_FOREIGN_LINEAGE'):
            daily.load(object(), context)
    refuse()
    assert selected == [PARAMS]
    monkeypatch.setattr(access, 'find_foreign', lambda *_args, **_kw: None)
    with pytest.raises(pytest.fail.Exception, match='foreign guard was bypassed'):
        refuse()


def test_clean_predecessor_read_does_not_install_or_hide_foreign_lineage(conn, predecessor):
    put(conn, 'unfamiliar-paper-namespace:v1', '{"wealth_core":null}')
    assert access.find_foreign(conn, **PARAMS) == ('unfamiliar-paper-namespace:v1',)
    assert access.require_schema(conn, allow_absent=True) is False
    assert conn.execute('SELECT 1 FROM sentinel_processed_sessions WHERE cursor_name=%s',
                        (access.CURSOR,)).fetchone() is None
    assert operational_schema.installation(conn) == predecessor
    conn.rollback()
    schema.require_runtime_schema(conn)


def test_additive_install_preserves_original_marker_and_all_canonical_rows(conn, predecessor):
    put(conn, PARAMS['allowed_names'][2], '{"wealth_core":false}')
    put(conn, 'shadow-observation:v1:primary:session:2026-11-05', '{"strategy_identity":null}')
    conn.commit()
    before = conn.execute('SELECT cursor_name,session,state,updated_at FROM '
                          'sentinel_processed_sessions ORDER BY cursor_name').fetchall()
    conn.rollback()
    assert operational_schema.install_quiescent(conn) == predecessor
    assert access.require_schema(conn)
    assert access.installation(conn, required=True)['authority_effect'] == 'NONE'
    assert conn.execute('SELECT cursor_name,session,state,updated_at FROM '
                        'sentinel_processed_sessions WHERE cursor_name<>%s ORDER BY cursor_name',
                        (access.CURSOR,)).fetchall() == before
    assert operational_schema.installation(conn) == predecessor
    assert operational_schema.contracts() == predecessor['contracts']
    assert access.find_foreign(conn, **PARAMS) is None
    conn.rollback()
    assert operational_schema.install_quiescent(conn) == predecessor
    schema.require_runtime_schema(conn)


def test_installation_records_the_original_database_instant_in_utc(conn, predecessor):
    from datetime import datetime, timedelta
    conn.execute("SET TimeZone='America/Los_Angeles'")
    before = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    conn.commit()
    operational_schema.install_quiescent(conn)
    marker = access.installation(conn, required=True)
    after = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    at = datetime.fromisoformat(marker['at'])
    assert before <= at <= after and at.utcoffset() == timedelta(0)


def test_final_readonly_installer_check_requires_the_access_path(conn, predecessor, monkeypatch, capsys):
    import json
    from scripts.sentinel_local_delivery import checks
    monkeypatch.setenv('SENTINEL_DATABASE_URL', conn.info.dsn)
    def refuse(program):
        with pytest.raises(access.AccessPathRefused, match='ACCESS_ABSENT'):
            exec(program, {})
    refuse(checks.READ_OPERATIONAL_SCHEMA)
    guard = ('    for component in operational_schema.access_path_components():\n'
             '        assert component.require_schema(c)\n')
    assert checks.READ_OPERATIONAL_SCHEMA.count(guard) == 1
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        refuse(checks.READ_OPERATIONAL_SCHEMA.replace(guard, ''))
    capsys.readouterr()
    operational_schema.install_quiescent(conn)
    exec(checks.READ_OPERATIONAL_SCHEMA, {})
    assert json.loads(capsys.readouterr().out) == {'installation': predecessor, 'complete': True}


@pytest.mark.parametrize('statement', [
    "DELETE FROM sentinel_processed_sessions WHERE cursor_name='checkpoint-lineage-access:v1'",
    "UPDATE sentinel_processed_sessions SET state='{}' WHERE cursor_name='checkpoint-lineage-access:v1'",
    "UPDATE sentinel_processed_sessions SET cursor_name='checkpoint-lineage-access:v1' "
    "WHERE cursor_name='operational-schema:v1'",
    'TRUNCATE sentinel_processed_sessions',
])
def test_access_installation_marker_is_immutable(conn, predecessor, statement):
    operational_schema.install_quiescent(conn)
    with pytest.raises(Exception, match='installation authority'):
        conn.execute(statement)
    conn.rollback()
    assert access.require_schema(conn)


def test_marker_authentication_has_an_executed_falsifier(conn, predecessor, monkeypatch):
    operational_schema.install_quiescent(conn)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'different-private-qualification-key-'*4)
    def refuse():
        with pytest.raises(access.AccessPathRefused, match='AUTHENTICATION'):
            access.installation(conn, required=True)
    refuse()
    original = access._require
    monkeypatch.setattr(access, '_require', lambda value, reason: None
                        if reason == 'CHECKPOINT_LINEAGE_ACCESS_AUTHENTICATION_FAILED'
                        else original(value, reason))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        refuse()


@pytest.mark.parametrize('damage', ['index', 'marker'])
def test_lost_installed_component_never_becomes_a_clean_predecessor(conn, predecessor, damage):
    operational_schema.install_quiescent(conn)
    if damage == 'index':
        conn.execute(f'DROP INDEX {access.INDEX}')
    else:
        conn.execute(f'ALTER TABLE sentinel_processed_sessions DISABLE TRIGGER {access.ROW_TRIGGER}')
        conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s', (access.CURSOR,))
        conn.execute(f'ALTER TABLE sentinel_processed_sessions ENABLE TRIGGER {access.ROW_TRIGGER}')
    conn.commit()
    for operation in (lambda:access.require_schema(conn, allow_absent=True),
                      lambda:access.find_foreign(conn, **PARAMS),
                      lambda:operational_schema.install_quiescent(conn)):
        conn.rollback()
        with pytest.raises(Exception, match='CATALOG|MARKER_LOST|ORPHANED'):
            operation()


def test_missing_index_refusal_has_an_executed_reader_falsifier(conn, predecessor, monkeypatch):
    operational_schema.install_quiescent(conn)
    conn.execute(f'DROP INDEX {access.INDEX}')
    conn.commit()
    def refuse():
        with pytest.raises(Exception, match='CATALOG'):
            access.find_foreign(conn, **PARAMS)
    refuse()
    monkeypatch.setattr(access, 'require_schema', lambda *_args, **_kwargs: False)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        refuse()


def test_transaction_failure_rolls_back_new_access_path_and_marker(conn, predecessor, monkeypatch):
    original = operational_schema._install_access_paths
    def fail_after_install(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('private simulated transaction failure')
    monkeypatch.setattr(operational_schema, '_install_access_paths', fail_after_install)
    with pytest.raises(RuntimeError, match='simulated transaction failure'):
        operational_schema.install_quiescent(conn)
    assert access.require_schema(conn, allow_absent=True) is False
    assert operational_schema.installation(conn) == predecessor


def test_other_financial_writer_prevents_concrete_index_installation(conn, predecessor):
    from sentinel.execution.journal import WRITER_LOCK_KEY
    with closing(store.connect(conn.info.dsn)) as other:
        other.execute('SELECT pg_advisory_xact_lock(%s)', (WRITER_LOCK_KEY,))
        with pytest.raises(operational_schema.OperationalSchemaRefused, match='WRITER_BUSY'):
            operational_schema.install_quiescent(conn)
    assert access.require_schema(conn, allow_absent=True) is False


@pytest.mark.parametrize('installed', [False, True])
@pytest.mark.parametrize('name,raw,foreign', [
    ('unknown:v1', '{"wealth_core":null}', True),
    ('unfamiliar-paper:v1', '{"strategy_identity":false}', True),
    ('unknown:v1', '["wealth_core"]', True),
    ('unknown:v1', '"strategy_identity"', True),
    ('shadow-foreign:v1', None, True),
    ('rolling-foreign:v1', 'false', True),
    ('catchup', '{}', True),
    ('ordinary:v1', '{"nested":{"wealth_core":true}}', False),
    ('ordinary:v1', None, False),
    ('rolling-cold-start:v1', '{"wealth_core":null}', False),
    ('shadow-observation:v1:primary:genesis', '{"wealth_core":null}', False),
    ('shadow-observation:v1:primary:session:2026-11-05', '{"wealth_core":null}', False),
    ('rolling-daily-input:v1:primary:2026-11-05', '{"strategy_identity":null}', False),
    ('shadow-rolling-runtime:v1:primary:2026-11-05', '{"strategy_identity":false}', False),
])
def test_real_reader_preserves_original_exclusions_and_json_presence(conn, predecessor,
                                                                   installed, name, raw, foreign):
    if installed:
        operational_schema.install_quiescent(conn)
    put(conn, name, raw)
    assert access.find_foreign(conn, **PARAMS) == ((name,) if foreign else None)

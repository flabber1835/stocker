"""Real PostgreSQL retained origin, upgrade admission, proof and continuation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest
from sentinel import rolling_initialization as initial, rolling_runtime as runtime
from sentinel import rolling_checkpoint as origin, rolling_daily_checkpoint as daily
from sentinel import runtime_admission as admission, retained_go, retained_parity, shadow_runtime
from sentinel.feed import rolling_go_inputs as inputs
from sentinel.feed.rolling_contract import digest, canonical_json
from tests.sentinel.test_current_window_production import ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_daily import refresh, OBS


@pytest.fixture
def executable(ready, monkeypatch):
    """Runtime attestation I/O is controlled; canonical book/DB/HMAC stay real."""
    root = Path(admission.__file__).parent
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob('*.py') if '__pycache__' not in p.parts}
    old = {key: value for key, value in actual.items() if key not in admission.ADDITIONS}
    old['shadow_supervisor.py'] = hashlib.sha256(b'prior reviewed supervisor').hexdigest()
    env = {'compatible': True, 'sentinel_source': {'path': str(root), 'files': len(actual), 'hash': admission.source_closure(actual)},
           'wealth_core_source': {'hash': '2'*64}, 'dependencies': 'fixed'}
    old_env = deepcopy(env)
    old_env['sentinel_source'].update(files=len(old), hash=admission.source_closure(old))
    sha = lambda env: hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
    controller, strategy = shadow_runtime._strategy()
    base = {'schema': 'sentinel.shadow-reviewed-config/1', 'observation_id': OBS, 'starting_cash': '50000',
        'execution_model': shadow_runtime.SHADOW_EXECUTION_MODEL, 'cutoff_policy': shadow_runtime.SHADOW_CUTOFF_POLICY,
        'publication_timing_policy': shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY}
    subject = '3'*64
    def context(environment, revision, image):
        reviewed = {**base, 'validated_source_identity_sha256': sha(environment)}
        runtime_id = {'schema': 'sentinel.shadow-runtime-identity/1', 'git_commit': revision,
            'runtime_image_digest': image, 'sentinel_source_sha256': environment['sentinel_source']['hash'],
            'wealth_core_source_sha256': '2'*64, 'environment_identity_sha256': sha(environment),
            'validated_source_identity_sha256': sha(environment), 'validated_shadow_config_sha256': digest(reviewed),
            'reviewed_shadow_config': reviewed, 'validated_data_publication_sha256': subject}
        return {'observation_id': OBS, 'starting_cash': '50000', 'controller': controller, 'strategy': strategy, 'runtime': runtime_id}
    prior = context(old_env, '4'*40, 'sha256:'+'5'*64)
    current = context(env, '6'*40, 'sha256:'+'7'*64)
    monkeypatch.setattr(admission.identity, 'rehearsal_identity', lambda: {'environment': deepcopy(env)})
    monkeypatch.setattr(admission.identity, '_imported_package_root', lambda _: root)
    monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kwargs: prior['runtime'])
    monkeypatch.setattr(admission, 'current_context', lambda **kw: deepcopy(current))
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', OBS)
    monkeypatch.setenv('SENTINEL_SHADOW_STARTING_CASH', '50000')
    manifest = {'schema': 'sentinel.retained-source-manifest/1', 'revision': '4'*40, 'files': old}
    return prior, current, manifest


def _start(conn, executable):
    prior, current, manifest = executable
    pub = inputs.current(conn)
    subject = shadow_runtime._data_publication_subject_sha256(pub, pub.window_end)
    prior['runtime']['validated_data_publication_sha256'] = subject
    current['runtime']['validated_data_publication_sha256'] = subject
    conn.rollback()
    result = runtime.advance(conn, through=pub.window_end, observation_id=OBS, starting_cash=50000)
    conn.rollback()
    return result


@pytest.mark.parametrize('ready', [{'formed': True}], indirect=True)
def test_upgrade_admission_preserves_book_and_restart_then_daily(conn, ready, executable, operational_source, monkeypatch):
    first = _start(conn, executable)
    before = origin.read(conn).model_dump(by_alias=True)
    conn.rollback()
    _, current, manifest = executable
    value = admission.admit(conn, context=current, manifest=manifest)
    assert value.authority_effect == 'NONE'
    assert origin.read(conn).model_dump(by_alias=True) == before
    conn.rollback()
    assert admission.admit(conn, context=current, manifest=manifest) == value
    monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kw: current['runtime'])
    monkeypatch.setattr(initial, 'initialize', lambda *a, **k: pytest.fail('upgrade repeated formation'))
    with inputs.pinned(conn) as pub:
        proof = retained_parity.prove(conn, held=pub, observation_id=OBS, starting_cash=50000)
    assert proof['state'].state_hash == first.state.state_hash
    assert proof['retained']['admission_sha256'] == digest(value.model_dump(by_alias=True))
    assert proof['retained']['book_runtime_sha256'] != digest(current['runtime'])
    conn.rollback()
    from sentinel import restore_validation
    restored = restore_validation._rolling_closure(conn)
    assert restored['state_present'] and restored['session'] == first.session
    conn.rollback()
    from dataclasses import replace
    real = retained_parity.advance_session
    with monkeypatch.context() as local:
        def different(*a, **kw):
            value = real(*a, **kw)
            return replace(value, shadow_peak_nav=value.shadow_peak_nav+1)
        local.setattr(retained_parity, 'advance_session', different)
        with inputs.pinned(conn) as pub, pytest.raises(RuntimeError, match='CANONICAL_RESULT_CHANGED'):
            retained_parity.prove(conn, held=pub, observation_id=OBS, starting_cash=50000)
    conn.rollback()
    monkeypatch.setattr(inputs, 'prepare', lambda *a, **kw: pytest.fail('retained state treated as fresh'))
    monkeypatch.setattr(inputs, '_prepare', lambda *a, **kw: pytest.fail('same-session input downloaded again'))
    with monkeypatch.context() as local:
        local.setattr(admission, 'admit', lambda *a, **kw: value)
        local.setattr(retained_go, 'load_manifest', lambda *a: manifest)
        local.setenv(retained_go.MANIFEST_ENV, 'fixture')
        assert retained_go.prepare(conn, target_session='2026-09-14',
            absolute_deadline=datetime.now(timezone.utc)+timedelta(minutes=10))['status'] == 'RETAINED_STATE_VERIFIED'
    refresh(conn, operational_source, monkeypatch)
    second = runtime.advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=50000)
    assert second.state.wealth_core['episodes']
    assert daily.read(conn).runtime_identity == before['runtime_identity']
    conn.rollback()
    with inputs.pinned(conn) as pub:
        proof = retained_parity.prove(conn, held=pub, observation_id=OBS, starting_cash=50000)
    assert proof['state'].state_hash == second.state.state_hash


@pytest.mark.parametrize('ready', [{}], indirect=True)
@pytest.mark.parametrize('defect', ['signature', 'runtime', 'state', 'input', 'backup', 'fence'])
def test_admission_or_retained_proof_refuses_without_changing_book(conn, ready, executable, monkeypatch, defect):
    _start(conn, executable)
    before = origin.read(conn)
    conn.rollback()
    _, current, manifest = executable
    if defect == 'backup':
        from sentinel import backup_runtime_authority
        monkeypatch.setattr(backup_runtime_authority, 'require', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('backup refused')))
    elif defect == 'fence':
        conn.execute('UPDATE sentinel_automation_control SET kill_switch_engaged=FALSE')
        conn.commit()
    else:
        raw = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s', (origin.CURSOR,)).fetchone()[0]
        if defect == 'signature': raw['hmac_sha256'] = '0'*64
        else:
            key = {'runtime': 'runtime_identity', 'state': 'state_sha256', 'input': 'input_value'}[defect]
            raw['checkpoint'][key] = {} if key.endswith('identity') or key.endswith('value') else '0'*64
            raw['hmac_sha256'] = origin._signature(raw['checkpoint'])
        conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s', (canonical_json(raw), origin.CURSOR))
        conn.commit()
    with pytest.raises((RuntimeError, ValueError, KeyError)):
        admission.admit(conn, context=current, manifest=manifest)
    assert conn.execute('SELECT COUNT(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE %s', (admission.PREFIX+'%',)).fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0


@pytest.mark.parametrize('ready', [{}], indirect=True)
def test_lost_admission_acknowledgement_recovers_exact_append(conn, ready, executable, monkeypatch):
    _start(conn, executable)
    _, current, manifest = executable
    class LostAck:
        def __getattr__(self, name): return getattr(conn, name)
        def commit(self):
            conn.commit()
            raise OSError('lost admission acknowledgement')
    with pytest.raises(OSError, match='lost admission'):
        admission.admit(LostAck(), context=current, manifest=manifest)
    value = admission.read(conn, current, origin.read(conn))
    conn.rollback()
    monkeypatch.setattr(admission, 'prove_compatibility', lambda *a, **kw: pytest.fail('admission repeated'))
    assert admission.admit(conn, context=current, manifest=manifest) == value
    assert conn.execute('SELECT COUNT(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE %s', (admission.PREFIX+'%',)).fetchone()[0] == 1


@pytest.mark.parametrize('ready', [{}], indirect=True)
@pytest.mark.parametrize('defect', ['hmac', 'process', 'foreign_lineage'])
def test_admission_readers_refuse_tamper_or_unknown_lineage(conn, ready, executable, monkeypatch, defect):
    _start(conn, executable)
    _, current, manifest = executable
    value = admission.admit(conn, context=current, manifest=manifest)
    if defect == 'foreign_lineage':
        conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES ('catchup-foreign',%s,'{}')", ('2026-09-14',))
    else:
        raw = {'admission': value.model_dump(by_alias=True), 'hmac_sha256': '0'*64}
        if defect == 'process':
            raw['admission']['process_sha256'] = '0'*64
            raw['hmac_sha256'] = admission._signature(raw['admission'])
        conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
            (canonical_json(raw), admission._key(current)))
    conn.commit()
    monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kw: current['runtime'])
    with pytest.raises(RuntimeError):
        runtime.classify(conn, observation_id=OBS, starting_cash=50000, structural_only=True)


@pytest.mark.parametrize('ready', [{}], indirect=True)
@pytest.mark.parametrize('state', ['FILLED', 'CANCELLED', 'REJECTED', 'UNKNOWN', 'PLANNED'])
def test_upgrade_preserves_binding_and_terminal_journal_but_refuses_inflight(conn, ready, executable, state):
    from sentinel import binding
    from sentinel.execution import journal
    from sentinel.execution.states import CommandState, blocks_overlapping
    from tests.sentinel.test_journal_and_reconcile import cmd, DEPLOY
    _start(conn, executable)
    owned = binding.bind(conn, deployment_id=DEPLOY.deployment_id, broker=DEPLOY.broker,
                         broker_account_id=DEPLOY.broker_account_id)
    command = cmd(state=CommandState(state), filled='10' if state == 'FILLED' else '0')
    journal.save_command(conn, command)
    original = origin.read(conn)
    commands = journal.load_commands(conn, DEPLOY)
    conn.rollback()
    _, current, manifest = executable
    if blocks_overlapping(command.state):
        with pytest.raises(RuntimeError, match='COMMAND_RECONCILIATION'):
            admission.admit(conn, context=current, manifest=manifest)
    else:
        assert admission.admit(conn, context=current, manifest=manifest).authority_effect == 'NONE'
    assert binding.load(conn) == owned
    assert journal.load_commands(conn, DEPLOY) == commands
    assert origin.read(conn) == original

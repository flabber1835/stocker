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
def executable(ready, monkeypatch, request):
    """Runtime attestation I/O is controlled; canonical book/DB/HMAC stay real."""
    root = Path(admission.__file__).parent
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob('*.py') if '__pycache__' not in p.parts}
    old = {key: value for key, value in actual.items() if key not in admission.ADDITIONS}
    if getattr(request, 'param', None) == 'execution':
        from sentinel.execution_upgrade import profile
        for name, record in profile()['files'].items():
            old[name] = record['before'][0]
    if getattr(request, 'param', None) == 'operational':
        from sentinel.operational_liveness_upgrade import profile
        old.pop('operational_liveness_upgrade.py', None)
        for name, record in profile()['files'].items():
            old[name] = record['before'][0]
    if getattr(request, 'param', None) == 'operational_runtime':
        from sentinel.operational_runtime_upgrade import profile
        old.pop('operational_runtime_upgrade.py', None)
        for name in profile()['additions']:
            old.pop(name, None)
        for name, record in profile()['files'].items():
            old[name] = record['before'][0]
    if getattr(request, 'param', None) in ('installed', 'preceding_release'):
        revision = '241da1f7' if request.param == 'installed' else 'f52301f2'
        manifest = json.loads((Path(__file__).parent/
            ('fixtures/retained-source-history/' + revision + '.json')).read_bytes())
        old = manifest['files']
    if getattr(request, 'param', None) == 'callback_liveness':
        from sentinel.callback_liveness_upgrade import profile
        old.pop('callback_liveness_upgrade.py', None)
        for name, record in profile()['files'].items():
            old[name] = record['before'][0]
    if getattr(request, 'param', None) not in ('installed', 'preceding_release'):
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
    revision = manifest['revision'] if getattr(request, 'param', None) in ('installed', 'preceding_release') else '4'*40
    prior = context(old_env, revision, 'sha256:'+'5'*64)
    current = context(env, '6'*40, 'sha256:'+'7'*64)
    if getattr(request, 'param', None) == 'economic':
        current['strategy'] = {**current['strategy'], 'data_semantics_source_sha256': '9'*64}
    monkeypatch.setattr(admission.identity, 'rehearsal_identity', lambda: {'environment': deepcopy(env)})
    monkeypatch.setattr(admission.identity, '_imported_package_root', lambda _: root)
    monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kwargs: prior['runtime'])
    monkeypatch.setattr(admission, 'current_context', lambda **kw: deepcopy(current))
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', OBS)
    monkeypatch.setenv('SENTINEL_SHADOW_STARTING_CASH', '50000')
    if getattr(request, 'param', None) not in ('installed', 'preceding_release'):
        manifest = {'schema': 'sentinel.retained-source-manifest/1', 'revision': revision, 'files': old}
    return prior, current, manifest


@pytest.mark.parametrize('ready', [{'formed': True}], indirect=True)
@pytest.mark.parametrize('executable', ['economic'], indirect=True)
def test_economic_policy_transition_keeps_origin_and_restarts_exactly_once(
        conn, ready, executable, operational_source, monkeypatch):
    first = _start(conn, executable)
    before = origin.read(conn).model_dump(by_alias=True)
    conn.rollback()
    _, current, manifest = executable
    admitted = admission.admit(conn, context=current, manifest=manifest)
    assert isinstance(admitted, admission.EconomicAdmission)
    assert origin.read(conn).model_dump(by_alias=True) == before
    conn.rollback()
    monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kw: current['runtime'])
    monkeypatch.setattr(shadow_runtime, '_strategy', lambda: (current['controller'], current['strategy']))
    monkeypatch.setattr(inputs, 'production_strategy', lambda: (current['controller'], current['strategy']))
    from sentinel import strategy
    monkeypatch.setattr(strategy, 'production_strategy', lambda: (current['controller'], current['strategy']))
    monkeypatch.setattr(initial, 'initialize', lambda *a, **kw: pytest.fail('economic upgrade repeated formation'))
    from sentinel.core.cash_distributions import entitlement
    from stock_strategy_shared.wealth_core.ledger import Ledger
    ex_date = '2026-09-11'
    book = Ledger.from_dict(first.state.ledger)
    owned = [(row['permaticker'], row['ticker']) for row in operational_source['TICKERS']
             if entitlement(book, security_id=row['permaticker'], ex_date=ex_date)]
    assert owned, 'formed fixture must contain historical dividend ownership'
    sid, ticker = owned[0]
    operational_source['ACTIONS'].append(dict(ticker=ticker, date=ex_date,
        action='dividend', value='.125', name='late captured cash', contraticker=None, contraname=None))
    refresh(conn, operational_source, monkeypatch)
    second = runtime.advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=50000)
    assert second.state.strategy_identity == current['strategy']
    assert second.state.ledger['events'][:len(first.state.ledger['events'])] == first.state.ledger['events']
    assert origin.read(conn).model_dump(by_alias=True) == before
    checkpoint = daily.read(conn)
    assert checkpoint.input_value['strategy_transition']['prior_state_sha256'] == first.state.state_hash
    assert any(row['security_id'] == sid and row['status'] == 'ACCRUED_FORWARD'
               for row in second.state.last_evidence['cash_distributions']['observations'])
    assert checkpoint.input_value['cash_distributions']['prior_state_sha256'] == first.state.state_hash
    conn.rollback()
    restarted = runtime.advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=50000)
    assert restarted.state.state_hash == second.state.state_hash
    assert admission.admit(conn, context=current, manifest=manifest) == admitted
    with inputs.pinned(conn) as held:
        proof = retained_parity.prove(conn, held=held, observation_id=OBS, starting_cash=50000)
    assert proof['state'].state_hash == second.state.state_hash
    # A later software image with the same economic policy can reuse the
    # migrated daily state and immutable original genesis.
    future = deepcopy(current)
    future['runtime'].update(git_commit='8'*40, runtime_image_digest='sha256:'+'9'*64)
    # A reviewed execution-source repair changes the source fingerprint even
    # while every selected economic setting and the cash policy remain equal.
    future['strategy'] = {**future['strategy'], 'data_semantics_source_sha256': 'd'*64}
    monkeypatch.setattr(admission, 'current_context', lambda **kw: deepcopy(future))
    monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kw: future['runtime'])
    monkeypatch.setattr(shadow_runtime, '_strategy', lambda: (future['controller'], future['strategy']))
    monkeypatch.setattr(inputs, 'production_strategy', lambda: (future['controller'], future['strategy']))
    monkeypatch.setattr(strategy, 'production_strategy', lambda: (future['controller'], future['strategy']))
    subsequent = admission.admit(conn, context=future, manifest=manifest)
    assert subsequent.process_sha256 != admitted.process_sha256
    later = runtime.advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=50000)
    assert later.state.state_hash == second.state.state_hash and not later.appended
    from sentinel.paper.validation import _require_state_strategy, PaperActivationRefused
    _require_state_strategy(conn, later.state, future['strategy'], retained_shadow=True)
    with pytest.raises(PaperActivationRefused, match='differs from runtime'):
        _require_state_strategy(conn, later.state, future['strategy'])
    assert origin.read(conn).model_dump(by_alias=True) == before
    conn.rollback()
    with inputs.pinned(conn) as held:
        proof = retained_parity.prove(conn, held=held, observation_id=OBS, starting_cash=50000)
        assert proof['retained']['schema'] == retained_parity.SPLIT_SCHEMA
        assert proof['retained']['book_strategy_sha256'] == digest(current['strategy'])
        assert proof['retained']['strategy_sha256'] == digest(future['strategy'])
        assert proof['retained']['admission_sha256'] == digest(subsequent.model_dump(by_alias=True))
        from sentinel import observation_authority, observation_startup
        from decimal import Decimal
        warmup = observation_authority._retained_warmup(conn, pub=held, cash=Decimal('50000'),
            controller=future['controller'], strategy=future['strategy'])
        observation_startup.require(warmup, strategy_sha256=digest(future['strategy']),
            controller_sha256=future['controller'].digest)
    conn.rollback()
    from sentinel import restore_validation
    assert restore_validation._rolling_closure(conn)['session'] == second.session
    conn.rollback()
    # Same-session GO must authenticate the retained publication without a new
    # price generation, formation or financial decision.
    with monkeypatch.context() as local:
        local.setattr(inputs, '_prepare', lambda *a, **kw: pytest.fail('same-session source reacquired'))
        local.setattr(retained_go, 'load_manifest', lambda *a: manifest)
        local.setenv(retained_go.MANIFEST_ENV, 'fixture')
        assert retained_go.prepare(conn, target_session=second.session,
            absolute_deadline=datetime.now(timezone.utc)+timedelta(minutes=10))['status'] == 'RETAINED_STATE_VERIFIED'
    refresh(conn, operational_source, monkeypatch)
    third = runtime.advance(conn, through='2026-09-16', observation_id=OBS, starting_cash=50000)
    assert third.state.strategy_identity == future['strategy']
    assert third.state.ledger['events'][:len(second.state.ledger['events'])] == second.state.ledger['events']
    assert origin.read(conn).model_dump(by_alias=True) == before
    conn.rollback()
    assert runtime.advance(conn, through=third.session, observation_id=OBS, starting_cash=50000).state.state_hash == third.state.state_hash
    with inputs.pinned(conn) as held:
        final = retained_parity.prove(conn, held=held, observation_id=OBS, starting_cash=50000)
    assert final['retained']['schema'] == retained_parity.SCHEMA
    assert final['state'].state_hash == third.state.state_hash
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0


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
@pytest.mark.parametrize('phase', ['admission', 'committed_candidate'])
def test_retained_go_metadata_wait_preserves_real_book_and_recovers_once(
        conn, ready, executable, operational_source, monkeypatch, phase):
    from psycopg.pq import TransactionStatus
    from sentinel import backup_runtime_authority as backup
    first = _start(conn, executable)
    before = dict(conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions').fetchall())
    conn.rollback()
    _, current, manifest = executable
    target = first.session
    real_require = backup.require
    failures = []
    def require(connection, *, operation, **kwargs):
        selected = ('compatible retained runtime admission' if phase == 'admission'
                    else 'rolling runtime attestation')
        limit = 1 if phase == 'admission' else 2
        if operation == selected and len(failures) < limit:
            failures.append(operation)
            backup._require_segment_frontier('000000010000001000000052.00000248.backup',
                segment_size=16*1024*1024, operation=operation)
        return real_require(connection, operation=operation, **kwargs)
    if phase == 'committed_candidate':
        admission.admit(conn, context=current, manifest=manifest)
        monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kw: current['runtime'])
        refresh(conn, operational_source, monkeypatch)
        target = '2026-09-15'
        monkeypatch.setattr(backup, 'require', require)
        with pytest.raises(backup.BackupRuntimeUnavailable):
            runtime.advance(conn, through=target, observation_id=OBS, starting_cash=50000)
        candidate = daily.read(conn)
        assert candidate.session == target
        conn.rollback()
        monkeypatch.setattr(runtime.daily, 'advance', lambda *a, **kw: pytest.fail('committed decision replayed'))
    else:
        monkeypatch.setattr(backup, 'require', require)
    monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kw: current['runtime'])
    monkeypatch.setattr(initial, 'initialize', lambda *a, **kw: pytest.fail('retained book reformed'))
    monkeypatch.setattr(inputs, 'prepare', lambda *a, **kw: pytest.fail('fresh preparation'))
    monkeypatch.setattr(inputs, '_prepare', lambda *a, **kw: pytest.fail('completed inputs reacquired'))
    monkeypatch.setattr(retained_go, 'load_manifest', lambda *a: manifest)
    monkeypatch.setenv(retained_go.MANIFEST_ENV, 'fixture')
    waits = []
    def sleep(seconds):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        waits.append(seconds)
    monkeypatch.setattr(retained_go.time, 'sleep', sleep)
    deadline = datetime.now(timezone.utc)+timedelta(minutes=10)
    assert retained_go.prepare(conn, target_session=target, absolute_deadline=deadline)['status'] == 'RETAINED_STATE_VERIFIED'
    assert waits == [10.0]
    assert len(failures) == (1 if phase == 'admission' else 2)
    after = dict(conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions').fetchall())
    assert all(after[key] == value for key, value in before.items())
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
    conn.rollback()
    verified = runtime.status(conn, observation_id=OBS, starting_cash=50000)
    if phase == 'committed_candidate':
        assert verified.state.state_hash == candidate.state_sha256
    else:
        assert verified.state.state_hash == first.state.state_hash
    conn.rollback()
    assert retained_go.prepare(conn, target_session=target, absolute_deadline=deadline)['status'] == 'RETAINED_STATE_VERIFIED'
    assert dict(conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions').fetchall()) == after


@pytest.mark.parametrize('ready', [{'formed': True}], indirect=True)
@pytest.mark.parametrize('executable', [None, 'execution'], indirect=True)
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

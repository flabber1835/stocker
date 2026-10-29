"""Typed negative waits preserve real rolling producer formation, never GO."""
from contextlib import contextmanager
import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest

from scripts import sentinel_activation_shadow as probe
from sentinel import rolling_runtime as runtime, rolling_initialization as initial
from sentinel import shadow_runtime, shadow_service, shadow_service_status as owner_status
from sentinel.feed import operational_snapshot as op
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS
from tests.sentinel.test_rolling_daily import refresh
from tests.sentinel.test_rolling_runtime import advance
from tests.sentinel.test_rolling_readiness_fusion import declared_nonfinancial_source_fixture  # noqa: F401


NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


def document(**updates):
    value = dict(schema=probe.SCHEMA, state='PUBLICATION_AHEAD', session='2026-09-15',
        publisher_attempt_id='a'*32, publisher_binding_sha256='b'*64,
        publisher_observed_at=NOW.isoformat(), publisher_deadline=(NOW+timedelta(seconds=120)).isoformat())
    value.update(updates)
    return value


def result(value=None, **updates):
    return CompletedProcess([], updates.get('returncode', probe.FORMATION_EXIT),
        updates.get('stdout', probe.WAIT_MARKER+json.dumps(value or document())), updates.get('stderr', ''))


@pytest.mark.parametrize('state', ['PUBLICATION_AHEAD', 'TRAILING_CANDIDATE', 'NEXT_FRESH_SESSION'])
def test_versioned_negative_documents_are_accepted(state):
    value = document(state=state)
    assert probe.decode_result(result(value), now=NOW) == value


def test_idle_next_fresh_session_is_negative_without_invented_attempt():
    value = document(state='NEXT_FRESH_SESSION', publisher_attempt_id=None, publisher_deadline=None)
    assert probe.decode_result(result(value), now=NOW) == value
    assert probe.decode_result(SimpleNamespace(returncode=0, stdout='{"status":"VERIFIED"}'), now=NOW) is None


@pytest.mark.parametrize('updates', [
    {'schema':'other'}, {'state':'VERIFIED'}, {'state':0}, {'state':[]}, {'state':{}}, {'session':'2026-02-30'},
    {'session':'2026-9-15'}, {'publisher_binding_sha256':'b'*63}, {'publisher_binding_sha256':0},
    {'publisher_attempt_id':0}, {'publisher_attempt_id':False}, {'publisher_attempt_id':'a'*31},
    {'publisher_attempt_id':None}, {'publisher_deadline':None}, {'publisher_deadline':0.0},
    {'publisher_observed_at':(NOW-timedelta(seconds=61)).isoformat()},
    {'publisher_observed_at':(NOW+timedelta(seconds=6)).isoformat()},
    {'publisher_observed_at':NOW.replace(tzinfo=None).isoformat()},
    {'publisher_deadline':NOW.isoformat()},
    {'publisher_deadline':(NOW+timedelta(seconds=7201)).isoformat()},
    {'publisher_observed_at':(NOW+timedelta(seconds=4)).isoformat(),
     'publisher_deadline':(NOW+timedelta(seconds=2)).isoformat()},
    {'publisher_attempt_id':None,'publisher_deadline':None}, {'extra':'field'},
])
def test_malformed_or_expired_negative_document_is_fatal(updates):
    with pytest.raises((ValueError, TypeError)):
        probe.decode_result(result(document(**updates)), now=NOW)


@pytest.mark.parametrize('updates', [
    {'returncode':0}, {'returncode':2}, {'stdout':'unrelated failure'},
    {'stdout':'noise\n'+probe.WAIT_MARKER+json.dumps(document())},
    {'stdout':probe.WAIT_MARKER+json.dumps(document())+'\n'+probe.WAIT_MARKER+json.dumps(document())},
    {'stderr':probe.WAIT_MARKER+json.dumps(document())},
    {'stdout':probe.WAIT_MARKER+'{"schema":"a","schema":"b"}'},
    {'stdout':probe.WAIT_MARKER+'{"schema":NaN}'},
])
def test_mixed_spoofed_or_contradictory_wire_response_is_fatal(updates):
    with pytest.raises(ValueError):
        probe.decode_result(result(**updates), now=NOW)


def child_namespace():
    # Load the actual child functions without replacing the process-wide native handler.
    body = probe.code().split('shadow_runtime.verified_shadow_status=_status_with_formation')[0]
    namespace = {}
    exec(compile(body, '<shadow-formation-child>', 'exec'), namespace)
    return namespace


@pytest.fixture
def signed_owner(tmp_path, monkeypatch):
    if not os.environ.get('SENTINEL_PUBLICATION_RECEIPT_KEY'):
        monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'synthetic-formation-test-key-'*3)
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'2'*64)
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', OBS)
    monkeypatch.setenv('SENTINEL_STATE_DIR', str(tmp_path))
    def publish(dsn, *, active=True, observed=None, attempt='a'*32, incarnation='c'*32):
        instant = observed or datetime.now(timezone.utc)
        pending = tmp_path/owner_status.PENDING_NAME
        if active:
            pending.write_text(json.dumps(dict(schema='sentinel.shadow-supervisor-pending/2',
                attempt_id=attempt, started_at_unix=instant.timestamp())), encoding='utf-8')
        else:
            pending.unlink(missing_ok=True)
        owner_status._write(tmp_path/owner_status.NAME, owner_status.Status(
            binding_sha256=owner_status.binding(dsn), incarnation=incarnation, state='RUNNING',
            reason='ACTIVE_WORKER' if active else 'IDLE', observed_at=instant,
            attempt_id=attempt if active else None,
            worker_deadline=instant+timedelta(seconds=120) if active else None))
    return publish, tmp_path


def test_positive_active_owner_requires_signed_status_and_both_durable_pending_reads(signed_owner):
    publish, directory = signed_owner
    publish('postgresql://synthetic/test')
    ns = child_namespace()
    config = SimpleNamespace(database_url='postgresql://synthetic/test')
    assert ns['_owner'](config)['reason'] == 'ACTIVE_WORKER'
    # Executed falsifier target: native status alone permits ACTIVE with absent pending.
    (directory/owner_status.PENDING_NAME).unlink()
    assert owner_status.read(directory, config.database_url)['reason'] == 'ACTIVE_WORKER'
    with pytest.raises(ValueError, match='ownership'):
        ns['_owner'](config)


@pytest.mark.parametrize('defect', ['stale','future','wrong_binding','critical','tampered','mismatched_pending'])
def test_unfresh_or_invalid_owner_is_fatal(signed_owner, defect):
    publish, directory = signed_owner
    observed = datetime.now(timezone.utc)
    if defect == 'stale': observed -= timedelta(seconds=61)
    if defect == 'future': observed += timedelta(seconds=6)
    publish('postgresql://synthetic/test', observed=observed)
    if defect == 'critical': (directory/owner_status.CRITICAL_NAME).write_text('{}')
    if defect == 'tampered': (directory/owner_status.NAME).write_text('{}')
    if defect == 'mismatched_pending':
        (directory/owner_status.PENDING_NAME).write_text(json.dumps(dict(
            schema='sentinel.shadow-supervisor-pending/2', attempt_id='d'*32,
            started_at_unix=observed.timestamp())))
    dsn = 'postgresql://synthetic/other' if defect == 'wrong_binding' else 'postgresql://synthetic/test'
    with pytest.raises((ValueError, KeyError)):
        child_namespace()['_owner'](SimpleNamespace(database_url=dsn))


def configured_child(conn, monkeypatch, signed_owner):
    publish, _ = signed_owner
    config = SimpleNamespace(database_url=conn.info.dsn, observation_id=OBS, starting_cash=Decimal(100_000))
    monkeypatch.setattr(shadow_service.ShadowServiceConfig, 'from_env', staticmethod(lambda:config))
    # Existing native rolling fixtures use the Sharadar historical provider; replace
    # only this external Alpaca provider label check, retaining real input/authority proofs.
    monkeypatch.setattr(op, 'require_alpaca_openfigi', lambda *_:None)
    publish(conn.info.dsn)
    return child_namespace(), config


def negative(ns, conn, capsys):
    with pytest.raises(SystemExit) as stopped:
        ns['_status_with_formation'](conn, observation_id=OBS, starting_cash=100_000)
    assert stopped.value.code == probe.FORMATION_EXIT
    output = capsys.readouterr().out
    return probe.decode_result(CompletedProcess([], probe.FORMATION_EXIT, output, ''))


def test_real_pg_published_before_checkpoint_is_typed_adjacent_wait_then_fresh_go(
        conn, published, issuer_source, monkeypatch, signed_owner, capsys):
    first = advance(conn)
    refresh(conn, issuer_source, monkeypatch)
    ns, _ = configured_child(conn, monkeypatch, signed_owner)
    waiting = negative(ns, conn, capsys)
    assert waiting['state'] == 'PUBLICATION_AHEAD'
    assert waiting['session'] != first.session
    current = advance(conn, waiting['session'])
    result = ns['_status_with_formation'](conn, observation_id=OBS, starting_cash=100_000)
    assert result.record_sha256 == current.record_sha256
    assert probe.WAIT_MARKER not in capsys.readouterr().out


def test_real_pg_committed_candidate_before_attestation_is_typed_wait_then_fresh_go(
        conn, published, monkeypatch, signed_owner, capsys):
    initial.initialize(conn, observation_id=OBS, starting_cash=100_000)
    ns, _ = configured_child(conn, monkeypatch, signed_owner)
    assert negative(ns, conn, capsys)['state'] == 'TRAILING_CANDIDATE'
    expected = advance(conn)
    assert ns['_status_with_formation'](conn, observation_id=OBS, starting_cash=100_000).record_sha256 == expected.record_sha256


@pytest.fixture
def formation_fixture(monkeypatch):
    ns = child_namespace()
    current = SimpleNamespace(window_end='2026-09-15', to_dict=lambda:{'window_end':'2026-09-15','seal':'current'})
    proof = SimpleNamespace(rollback=lambda:None, execute=lambda *_:None)
    @contextmanager
    def connection(_): yield proof
    @contextmanager
    def pinned(*_, **__): yield current
    monkeypatch.setattr(ns['committed_read'], 'proof_connection', connection)
    monkeypatch.setattr(ns['readers'], 'pinned', pinned)
    monkeypatch.setattr(ns['readers'], 'is_rolling', lambda _:True)
    monkeypatch.setattr(ns['operational_snapshot'], 'require_alpaca_openfigi', lambda *_:None)
    monkeypatch.setattr(ns['rolling_go_inputs'], 'require_schemas', lambda *_:None)
    validated = []
    monkeypatch.setattr(ns['rolling_go_inputs'], 'validate_status', lambda *_:validated.append(True))
    config = SimpleNamespace(database_url='fixture', observation_id=OBS, starting_cash=100_000)
    monkeypatch.setattr(ns['shadow_service'].ShadowServiceConfig, 'from_env', staticmethod(lambda:config))
    now = datetime.now(timezone.utc)
    owner = dict(reason='ACTIVE_WORKER', incarnation='c'*32, binding_sha256='b'*64,
        observed_at=now, attempt_id='a'*32, worker_deadline=now+timedelta(seconds=120))
    ns['_owner'] = lambda _:dict(owner)
    monkeypatch.setattr(ns['shadow_runtime'], 'classify_shadow_lineage', lambda *_a, **_kw:
        dict(status='RECONSTRUCTED_STRUCTURAL', latest_session=current.window_end))
    monkeypatch.setattr(ns['rolling_runtime'].initial, '_context', lambda *_:{})
    monkeypatch.setattr(ns['rolling_runtime'], '_closure', lambda *_a, **_kw:
        (SimpleNamespace(publication=current.to_dict()),None,None,None,None))
    return ns, current, owner, validated


@pytest.mark.parametrize('active', [True,False])
def test_reconstructed_current_session_waits_for_next_fresh_session(formation_fixture, active):
    ns, current, owner, validated = formation_fixture
    if not active: owner.update(reason='IDLE', attempt_id=None, worker_deadline=None)
    value = ns['_formation'](object(), OBS, 100_000, 'RECONSTRUCTION_IS_NOT_PROSPECTIVE_AUTHORITY')
    assert value['state'] == 'NEXT_FRESH_SESSION' and value['session'] == '2026-09-16'
    assert value['publisher_attempt_id'] == owner['attempt_id'] and validated == [True]
    assert probe.decode_result(result(value)) == value


@pytest.mark.parametrize('defect', ['same_session_publication','farther_gap','incarnation','binding'])
def test_formation_does_not_conceal_changed_publication_or_owner(formation_fixture, monkeypatch, defect):
    ns, current, owner, _ = formation_fixture
    reason = 'RECONSTRUCTION_IS_NOT_PROSPECTIVE_AUTHORITY'
    if defect == 'same_session_publication':
        monkeypatch.setattr(ns['rolling_runtime'], '_closure', lambda *_a, **_kw:
            (SimpleNamespace(publication={'seal':'changed'}),None,None,None,None))
    elif defect == 'farther_gap':
        reason = 'ROLLING_RUNTIME_PUBLICATION_CHANGED'
        monkeypatch.setattr(ns['shadow_runtime'], 'classify_shadow_lineage', lambda *_a, **_kw:
            dict(status='ATTESTED_STRUCTURAL', latest_session='2026-09-11'))
    else:
        before, after = dict(owner), dict(owner)
        after['incarnation' if defect=='incarnation' else 'binding_sha256'] = 'd'*(32 if defect=='incarnation' else 64)
        values=iter([before,after])
        ns['_owner']=lambda _:next(values)
    with pytest.raises(ValueError): ns['_formation'](object(), OBS, 100_000, reason)


@pytest.mark.parametrize('change', [-1,1])
def test_same_attempt_deadline_may_only_shorten(formation_fixture, change):
    ns, _, owner, _ = formation_fixture
    before, after = dict(owner), dict(owner)
    after['worker_deadline'] += timedelta(microseconds=change)
    values = iter([before,after])
    ns['_owner'] = lambda _:next(values)
    if change > 0:
        with pytest.raises(ValueError, match='worker changed'):
            ns['_formation'](object(), OBS, 100_000, 'RECONSTRUCTION_IS_NOT_PROSPECTIVE_AUTHORITY')
    else:
        value = ns['_formation'](object(), OBS, 100_000, 'RECONSTRUCTION_IS_NOT_PROSPECTIVE_AUTHORITY')
        assert value['publisher_deadline'] == after['worker_deadline'].isoformat()


def refusal(code, cause_type=None):
    error = shadow_runtime.ShadowRuntimeRefused('native refusal')
    error.__cause__ = (cause_type or runtime.Refused)(code)
    return error


@pytest.mark.parametrize('transition', ['active_to_idle','idle_to_active','active_to_successor'])
def test_owner_handoff_reobserves_native_status_once_without_stale_wait(formation_fixture, transition, capsys):
    ns, _, owner, _ = formation_fixture
    active, idle = dict(owner), {**owner,'reason':'IDLE','attempt_id':None,'worker_deadline':None}
    successor = {**active, 'attempt_id':'d'*32, 'worker_deadline':owner['worker_deadline']+timedelta(seconds=10)}
    values = iter({'active_to_idle':[active,idle], 'idle_to_active':[idle,active],
                   'active_to_successor':[active,successor]}[transition])
    ns['_owner'] = lambda _:next(values)
    calls=[]
    positive=object()
    def original(*_, **__):
        calls.append(True)
        if len(calls)==1: raise refusal('RECONSTRUCTION_IS_NOT_PROSPECTIVE_AUTHORITY')
        return positive
    ns['_original_shadow_status']=original
    assert ns['_status_with_formation'](object(),observation_id=OBS,starting_cash=100_000) is positive
    assert len(calls)==2 and capsys.readouterr().out==''


@pytest.mark.parametrize('error', [refusal('OTHER_REFUSAL'),
    refusal('ROLLING_RUNTIME_PUBLICATION_CHANGED', ValueError),
    refusal('prefix ROLLING_RUNTIME_PUBLICATION_CHANGED')])
def test_only_exact_native_refusal_type_and_code_can_enter_formation(error):
    ns=child_namespace()
    def original(*_, **__): raise error
    ns['_original_shadow_status']=original
    ns['_formation']=lambda *_:pytest.fail('unknown refusal must remain fatal')
    with pytest.raises(shadow_runtime.ShadowRuntimeRefused):
        ns['_status_with_formation'](object(),observation_id=OBS,starting_cash=100_000)


def test_generated_child_cannot_dispatch_a_mutating_argv():
    assert probe.code().endswith("raise SystemExit(main(['shadow-status']))")


def mutated_guard(namespace, function_name, needle, replacement=False):
    """Execute the generated child after removing one selected proof gate."""
    source = probe.code().split('shadow_runtime.verified_shadow_status=_status_with_formation')[0]
    tree = ast.parse(source)
    definition = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                      and node.name == function_name)
    selected = [node for node in ast.walk(definition) if isinstance(node, ast.If)
                and needle in (ast.get_source_segment(source, node.test) or '')]
    assert len(selected) == 1, 'falsifier must remove precisely one actual child gate'
    selected[0].test = ast.Constant(replacement)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[])),
                 '<removed-shadow-proof-guard>', 'exec'), namespace)
    return namespace[function_name]


def require_refusal(call, expected=ValueError):
    try:
        call()
    except expected:
        return
    except BaseException as exc:
        raise AssertionError('removed proof gate produced a different result') from exc
    raise AssertionError('removed proof gate accepted unproved formation')


@pytest.mark.parametrize('gate', ['adjacency','publication','pending_presence','latest_presence',
                                 'pending_mismatch','native_type','native_code','deadline'])
def test_executed_guard_removal_falsifiers(formation_fixture, signed_owner, monkeypatch, capsys, gate):
    ns, current, owner, _ = formation_fixture
    name, needle, replacement = '_formation', '', False
    reason = 'RECONSTRUCTION_IS_NOT_PROSPECTIVE_AUTHORITY'
    def invoke(function):
        return function(object(), OBS, 100_000, reason)
    if gate == 'adjacency':
        reason = 'ROLLING_RUNTIME_PUBLICATION_CHANGED'
        monkeypatch.setattr(ns['shadow_runtime'], 'classify_shadow_lineage', lambda *_a, **_kw:
            dict(status='ATTESTED_STRUCTURAL', latest_session='2026-09-11'))
        needle, replacement = 'calendar.next_session(prior)', True
    elif gate == 'publication':
        monkeypatch.setattr(ns['rolling_runtime'], '_closure', lambda *_a, **_kw:
            (SimpleNamespace(publication={'seal':'changed'}),None,None,None,None))
        needle = 'checkpoint.publication'
    elif gate == 'deadline':
        needle = "after['worker_deadline']>before['worker_deadline']"
        def invoke(function):
            values = iter([dict(owner), {**owner,'worker_deadline':owner['worker_deadline']+timedelta(seconds=1)}])
            ns['_owner'] = lambda _:next(values)
            return function(object(), OBS, 100_000, reason)
    elif gate.startswith('pending') or gate == 'latest_presence':
        name, needle = '_owner', 'pending is None'
        ns['_owner'] = child_namespace()['_owner']
        publish, directory = signed_owner
        config = SimpleNamespace(database_url='postgresql://synthetic/test')
        publish(config.database_url)
        snapshot = ns['shadow_service_probe'].observe(directory)
        authenticated = owner_status.decode_probe(snapshot, config.database_url)
        if gate == 'pending_presence': snapshot.update(pending=None, latest_pending=None)
        elif gate == 'latest_presence': snapshot['latest_pending'] = None
        else:
            changed = json.loads(snapshot['latest_pending'])
            changed['attempt_id'] = 'd'*32
            snapshot['latest_pending'] = json.dumps(changed).encode()
            # The canonical decoder independently rejects this mismatch. Isolate
            # the additional local check after proving real signature/binding,
            # so its own removal is observable rather than hidden by redundancy.
            monkeypatch.setattr(ns['shadow_service_status'], 'decode_probe', lambda *_:authenticated)
        monkeypatch.setattr(ns['shadow_service_probe'], 'observe', lambda _:snapshot)
        def invoke(function): return function(config)
    else:
        name, needle = '_status_with_formation', 'type(cause)'
        error = refusal('OTHER_REFUSAL' if gate=='native_code' else 'ROLLING_RUNTIME_PUBLICATION_CHANGED',
                        ValueError if gate=='native_type' else None)
        def original(*_, **__): raise error
        ns['_original_shadow_status'] = original
        ns['_formation'] = lambda *_:document()
        def invoke(function): return function(object(), observation_id=OBS, starting_cash=100_000)
    real = ns[name]
    expected = shadow_runtime.ShadowRuntimeRefused if gate.startswith('native') else ValueError
    require_refusal(lambda:invoke(real), expected)
    broken = mutated_guard(ns, name, needle, replacement)
    with pytest.raises(AssertionError):
        require_refusal(lambda:invoke(broken), expected)
    ns[name] = real
    require_refusal(lambda:invoke(real), expected)
    capsys.readouterr()

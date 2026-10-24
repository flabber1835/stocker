"""Reusable delivery readers bind current facts and remain read-only."""
import ast
from contextlib import contextmanager
from copy import deepcopy
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import urllib.request

import pytest


ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
PACKAGE = ROOT/'scripts'/'sentinel_local_delivery'
SPEC = importlib.util.spec_from_file_location('delivery_evidence_fixture', PACKAGE/'__init__.py',
                                             submodule_search_locations=[str(PACKAGE)])
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
evidence = importlib.import_module(SPEC.name+'.evidence')
checks = importlib.import_module(SPEC.name+'.checks')
model = importlib.import_module(SPEC.name+'.model')
host_module = importlib.import_module(SPEC.name+'.host')


def prepared():
    binding = dict(deployment_id='fictional-deployment', broker='alpaca', broker_account_id='PAPER-Z',
        takeover_epoch=9, ownership_state='SENTINEL_OWNED', notes='original')
    control = {key: value for key, value in binding.items() if key not in ('ownership_state', 'notes')}
    control.update(generation=99, enabled=True, kill_switch_engaged=False, authority_verdict='PASS',
        certificate_sha256='certificate', rollout_mode='CONTROLLER', rollout_version=12, config_sha256='config')
    cycle = {**control, 'control_generation': 99, 'plan_id': 'future-plan',
        'decision_session': '2031-04-21', 'effective_session': '2031-04-22'}
    return dict(system='123456789', candidate_count=1, control=control, cycle=cycle, binding=binding,
        plan={'plan_id': 'future-plan'}, archive_mode='off', archive_command='', fsync='on',
        full_page_writes='on', ready=True, inflight=0, other_active=0, jobs_active=0, job_live_owners=0,
        publication={'version': 87, 'window_end': '2031-04-21'},
        source_binding={'job_state': 'PUBLISHED', 'job_publication': 87},
        authority_md5='authority', opening_md5='opening', push_policy_md5='notification-policy',
        push_subscriptions={'active': 2})


class Host:
    def __init__(self, state=None):
        self.state = deepcopy(state or prepared())
        self.request = {'predecessor': {'system': '123456789'}}
        self.calls = []
    def sql(self, statement):
        self.calls.append(statement)
        return deepcopy(self.state)
    def load_values(self):
        return {'SENTINEL_LOCAL_PAPER_ACCOUNT_ID': 'PAPER-Z'}


def test_snapshot_derives_a_different_subject_without_release_constants():
    host = Host()
    assert evidence.snapshot(host) == prepared()
    assert host.calls == [checks.SNAPSHOT_SQL]
    assert 's.control_generation=c.generation' in checks.SNAPSHOT_SQL
    assert "s.execute_at>clock_timestamp()+interval '15 minutes'" in checks.SNAPSHOT_SQL
    assert '2026-10-' not in checks.SNAPSHOT_SQL and 'PA3NDXAHULSS' not in checks.SNAPSHOT_SQL
    assert 'jsonb_agg(to_jsonb' not in checks.SNAPSHOT_SQL
    assert 'string_agg(md5(to_jsonb(x)::text)' in checks.SNAPSHOT_SQL


@pytest.mark.parametrize('path,value', [
    (('candidate_count',), 2), (('system',), 'foreign'), (('archive_mode',), 'on'),
    (('archive_command',), 'external-command'), (('fsync',), 'off'), (('full_page_writes',), 'off'),
    (('control', 'enabled'), False), (('control', 'kill_switch_engaged'), True),
    (('control', 'authority_verdict'), 'FAIL'), (('control', 'broker_account_id'), 'foreign'),
    (('binding', 'ownership_state'), 'LEGACY'), (('binding', 'takeover_epoch'), 8),
    (('ready',), False), (('cycle', 'plan_id'), 'other'), (('cycle', 'control_generation'), 98),
    (('cycle', 'config_sha256'), 'other'), (('cycle', 'certificate_sha256'), 'other'),
    (('inflight',), 1), (('other_active',), 1), (('jobs_active',), 1), (('job_live_owners',), 1),
    (('publication', 'window_end'), '2031-04-20'), (('source_binding', 'job_state'), 'ACQUIRING'),
    (('source_binding', 'job_publication'), 86), (('authority_md5',), None),
    (('push_subscriptions', 'active'), 0), (('push_policy_md5',), None)])
def test_snapshot_refuses_mixed_binding_busy_or_unready_evidence(path, value):
    host = Host()
    parent = host.state
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(model.DeliveryRefused):
        evidence.snapshot(host)


def test_future_hold_only_plan_preserves_absent_opening_sizing_instead_of_inventing_it():
    host = Host()
    host.state['opening_md5'] = None
    assert evidence.snapshot(host)['opening_md5'] is None


def test_host_sql_uses_server_read_only_and_bounded_small_hashes():
    host = object.__new__(host_module.Host)
    calls = []
    host.run = lambda argv, **kwargs: calls.append((argv, kwargs)) or SimpleNamespace(stdout=b'null')
    assert host.sql(checks.SNAPSHOT_SQL) is None
    argv, kwargs = calls[0]
    command = argv[-1]
    assert command.startswith('BEGIN READ ONLY;') and command.endswith('; ROLLBACK;')
    assert "statement_timeout='15000ms'" in command and "lock_timeout='1000ms'" in command
    assert "work_mem='4MB'" in command and 'max_parallel_workers_per_gather=0' in command
    assert kwargs == {'timeout': 25}
    assert not re.search(r'\b(?:INSERT|UPDATE|DELETE|TRUNCATE|CREATE|DROP|ALTER)\b', command)


def test_canonical_adapter_passes_dynamic_authenticated_subject_and_keeps_full_proof():
    host = Host()
    answer = {'transaction_read_only': True, 'plan': 'future-plan', 'wealth': 'economic-wealth',
              'strategy': 'economic-strategy', 'book': {'original': 'unchanged'}}
    def compose(values, *args, **kwargs):
        host.calls.append((values, args, kwargs))
        expected = json.loads(args[-1])
        assert expected['binding'] == host.state['binding']
        assert expected['decision'] == '2031-04-21' and expected['effective'] == '2031-04-22'
        assert expected['version'] == 87 and expected['config'] == 'config'
        assert expected['account'] == 'PAPER-Z'
        assert args[-2] == checks.CANONICAL and kwargs == {'timeout': 300}
        return SimpleNamespace(stdout=json.dumps(answer).encode())
    host.compose = compose
    assert evidence.canonical_check(host, {'literal': 'configuration'}, host.state) == answer
    program = ast.parse(checks.CANONICAL)
    function = next(node for node in program.body if isinstance(node, ast.FunctionDef) and node.name == 'verify_once')
    connection = next(node for node in function.body if isinstance(node, ast.With))
    assert ast.unparse(connection.body[-1]) == 'conn.rollback()'
    assert 'default_transaction_read_only=on' in checks.CANONICAL
    assert "conn.execute('SHOW transaction_read_only')" in checks.CANONICAL
    assert 'rolling_checkpoint.read(conn)' in checks.CANONICAL
    assert 'starting_cash=50000' not in checks.CANONICAL


def configuration_host(*, failure=None, mutate=None):
    host = Host()
    host.request.update(predecessor={'image': 'old-image'}, candidate={'image': 'new-image'})
    host.calls = []
    host.predecessor_services=lambda:host_module.SERVICES
    def compose(values, *args):
        assert args == ('config', '--format', 'json')
        role = values['role']
        environment = {'SENTINEL_AUTOMATION_RETRY_BASE_SECONDS': '5', 'SENTINEL_PAPER_DEBUG_WINDOW': ''}
        if failure == 'semantic' and role == 'candidate':
            environment['SENTINEL_AUTOMATION_RETRY_BASE_SECONDS'] = '10'
        services = {name: {'image': host.request[role]['image'], 'environment': {}}
            for name in (*host_module.SERVICES, 'sentinel-authorized-cli')}
        services['sentinel-automation']['environment'] = environment
        shared = {key: 'fixture:'+key for key in evidence._VERIFICATION_SUBJECT_ENV}
        shared['SENTINEL_SHADOW_STARTING_CASH'] = '50000'
        for name in ('sentinel-panel', 'sentinel-verifier', 'sentinel-shadow', 'sentinel-authorized-cli'):
            services[name]['environment'].update(shared)
        # Role-specific execution grants are deliberately different from the
        # read-only panel/verifier subject, and shadow has no execution policy.
        for key in evidence._ROLE_AUTHORITY_ENV:
            services['sentinel-shadow']['environment'][key] = 'shadow-grant'
            services['sentinel-authorized-cli']['environment'][key] = 'execution-grant'
        for key in evidence._PAPER_SUBJECT_ENV:
            services['sentinel-shadow']['environment'].pop(key)
        if failure == 'image' and role == 'candidate':
            services['sentinel-panel']['image'] = 'foreign'
        if failure == 'panel-secret':
            services['sentinel-panel']['environment']['ALPACA_API_KEY'] = 'fictional-secret'
        if mutate is not None and role == 'candidate':
            mutate(services)
        return SimpleNamespace(stdout=json.dumps({'services': services}).encode())
    def run(argv, **kwargs):
        host.calls.append((argv, kwargs))
        assert '--network' in argv and argv[argv.index('--network')+1] == 'none'
        assert '-v' not in argv and '--volume' not in argv and '-e' not in argv
        selected = json.loads(kwargs['data'])
        assert set(selected) == {'SENTINEL_AUTOMATION_RETRY_BASE_SECONDS', 'SENTINEL_PAPER_DEBUG_WINDOW'}
        assert argv[-1] == checks.AUTOMATION_CONFIG
        return SimpleNamespace(stdout=b'foreign' if failure == 'fingerprint' else b'config\n')
    host.compose, host.run = compose, run
    return host


def test_configuration_comparison_uses_both_exact_offline_images_without_credentials():
    host = configuration_host()
    evidence.compare_configuration(host, {'role': 'predecessor'}, {'role': 'candidate'}, host.state)
    assert len(host.calls) == 2
    assert [argv[-4] for argv, _ in host.calls] == ['old-image', 'new-image']


@pytest.mark.parametrize('failure', ['semantic', 'image', 'panel-secret', 'fingerprint'])
def test_configuration_drift_foreign_image_or_panel_credentials_refuse(failure):
    host = configuration_host(failure=failure)
    with pytest.raises(model.DeliveryRefused):
        evidence.compare_configuration(host, {'role': 'predecessor'}, {'role': 'candidate'}, host.state)


def test_host_verification_contract_covers_every_runtime_subject_key():
    tree = ast.parse((ROOT/'sentinel/panel/read_projection.py').read_text(encoding='utf-8'))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'SUBJECT_ENV' for target in node.targets))
    assert evidence._VERIFICATION_SUBJECT_ENV == frozenset(ast.literal_eval(assignment.value.args[0]))


def test_local_verification_default_cash_matches_actual_shadow_and_execution_subject():
    import yaml
    overlay = yaml.safe_load((ROOT/'docker-compose.sentinel-local-paper.yml').read_text(encoding='utf-8'))
    base = yaml.safe_load((ROOT/'docker-compose.sentinel-automation.yml').read_text(encoding='utf-8'))
    key = 'SENTINEL_SHADOW_STARTING_CASH'
    expected = base['services']['sentinel-shadow']['environment'][key]
    assert expected == '${SENTINEL_SHADOW_STARTING_CASH:-50000}'
    assert base['services']['sentinel-authorized-cli']['environment'][key] == expected
    for service in ('sentinel-panel', 'sentinel-verifier'):
        assert overlay['services'][service]['environment'][key] == expected


@pytest.mark.parametrize('key', sorted(evidence._VERIFICATION_SUBJECT_ENV))
def test_candidate_panel_and_verifier_must_share_the_exact_full_subject(key):
    def change(services):
        services['sentinel-verifier']['environment'][key] = 'different-subject'
    host = configuration_host(mutate=change)
    with pytest.raises(model.DeliveryRefused, match='VERIFICATION_SUBJECT_MISMATCH: '+key):
        evidence.compare_configuration(host, {'role': 'predecessor'}, {'role': 'candidate'}, host.state)
    assert not host.calls  # Refuse before any canonical/application handoff.


@pytest.mark.parametrize('key', sorted(evidence._VERIFICATION_SUBJECT_ENV
    - evidence._PAPER_SUBJECT_ENV - evidence._ROLE_AUTHORITY_ENV))
def test_matching_readers_cannot_select_a_different_canonical_book_subject(key):
    def change(services):
        for name in ('sentinel-panel', 'sentinel-verifier'):
            services[name]['environment'][key] = 'different-subject'
    host = configuration_host(mutate=change)
    with pytest.raises(model.DeliveryRefused, match='VERIFICATION_BOOK_SUBJECT_MISMATCH: '+key):
        evidence.compare_configuration(host, {'role': 'predecessor'}, {'role': 'candidate'}, host.state)
    assert not host.calls


@pytest.mark.parametrize('key', sorted(evidence._PAPER_SUBJECT_ENV))
def test_matching_readers_cannot_select_a_different_execution_policy(key):
    def change(services):
        for name in ('sentinel-panel', 'sentinel-verifier'):
            services[name]['environment'][key] = 'different-policy'
    host = configuration_host(mutate=change)
    with pytest.raises(model.DeliveryRefused, match='VERIFICATION_PAPER_SUBJECT_MISMATCH: '+key):
        evidence.compare_configuration(host, {'role': 'predecessor'}, {'role': 'candidate'}, host.state)
    assert not host.calls


def test_role_polling_clocks_do_not_become_financial_subjects():
    def change(services):
        services['sentinel-panel']['environment']['SENTINEL_PANEL_POLL_SECONDS'] = '7'
        services['sentinel-verifier']['environment']['SENTINEL_SHADOW_POLL_SECONDS'] = '30'
        services['sentinel-shadow']['environment']['SENTINEL_SHADOW_POLL_SECONDS'] = '300'
    host = configuration_host(mutate=change)
    evidence.compare_configuration(host, {'role': 'predecessor'}, {'role': 'candidate'}, host.state)
    assert len(host.calls) == 2


def test_removing_rendered_subject_guard_has_a_capital_mismatch_falsifier(monkeypatch):
    import inspect
    source = inspect.getsource(evidence.compare_configuration)
    guard = '            _require_verification_subject(configuration)\n'
    assert source.count(guard) == 1
    scope = dict(vars(evidence))
    exec(compile(source.replace(guard, ''), 'removed verification subject guard', 'exec'), scope)
    monkeypatch.setattr(evidence, 'compare_configuration', scope['compare_configuration'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_matching_readers_cannot_select_a_different_canonical_book_subject(
            'SENTINEL_SHADOW_STARTING_CASH')


@pytest.mark.parametrize('result',['busy','stopped-disconnect','ambiguous-disconnect'])
def test_initial_bridge_holds_restart_before_signal_and_restores_only_definite_busy(tmp_path,monkeypatch,result):
    host=Host();host.source=tmp_path
    raw=b'qualified compatibility helper'
    path=tmp_path/'sentinel/shadow_drain_compat.py';path.parent.mkdir();path.write_bytes(raw)
    import hashlib
    host.request.update(operation_id='guarded-bridge',predecessor={'commit':model.COMPAT_DRAIN_PREDECESSOR,'image':'old'},
        qualification={'source_files':{'sentinel/shadow_drain_compat.py':hashlib.sha256(raw).hexdigest()}})
    policy={'Name':'unless-stopped','MaximumRetryCount':0}
    item={'Id':'exact-container','Image':'old','State':{'Running':True},'HostConfig':{'RestartPolicy':deepcopy(policy)}}
    target=dict(container='exact-container',image='old',restart_policy=deepcopy(policy))
    host.container=lambda name:deepcopy(item)
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        if argv[:2]==['docker','update']:
            item['HostConfig']['RestartPolicy']['Name']=argv[2].split('=')[1]
            return SimpleNamespace(stdout=b'')
        assert argv[:2]==['docker','exec']
        assert item['HostConfig']['RestartPolicy']['Name']=='no'
        if result=='busy':return SimpleNamespace(stdout=b'{"status":"BUSY_BEFORE_BARRIER"}')
        if result=='stopped-disconnect':item['State']['Running']=False
        raise model.DeliveryRefused('EXPECTED_EXEC_DISCONNECT')
    host.run=run
    def barrier(*args):
        model.require(not item['State']['Running'],'BARRIER_NOT_STOPPED')
        return {'method':'EXACT_B2_KERNEL_BARRIER','acknowledgement':{'immutable':True}}
    monkeypatch.setattr(evidence,'_compat_barrier',barrier)
    if result=='stopped-disconnect':
        assert evidence.request_drain(host,{},target)['method']=='EXACT_B2_KERNEL_BARRIER'
    else:
        with pytest.raises(model.DeliveryRefused,match='BUSY_BEFORE_BARRIER' if result=='busy' else 'BARRIER_NOT_STOPPED'):
            evidence.request_drain(host,{},target)
    assert calls[0]==['docker','update','--restart=no','exact-container']
    assert item['HostConfig']['RestartPolicy']['Name']==('unless-stopped' if result=='busy' else 'no')


def compatibility_barrier_host(*, changed=None, before_read=False):
    host=Host()
    host.request.update(operation_id='guarded-bridge',candidate={'image':'qualified-candidate'})
    item=dict(Id='exact-container',Image='old',State=dict(Running=False,Restarting=False),
        HostConfig={'RestartPolicy':{'Name':'no','MaximumRetryCount':0}},
        Mounts=[dict(Destination='/var/lib/sentinel',Type='volume',Name='sentinel_sentinel_state')])
    target=dict(container=item['Id'],image=item['Image'])
    def change():
        if changed=='policy':item['HostConfig']['RestartPolicy']['Name']='unless-stopped'
        elif changed=='running':item['State']['Running']=True
        elif changed=='restarting':item['State']['Restarting']=True
        elif changed=='container':item['Id']='another-container'
        elif changed=='image':item['Image']='another-image'
    if before_read:change()
    host.container=lambda _name:deepcopy(item)
    host.compose=lambda *args:SimpleNamespace(stdout=json.dumps({'services':{'sentinel-shadow':
        {'environment':{'SENTINEL_PUBLICATION_RECEIPT_KEY':'private-test-key'}}}}).encode())
    @contextmanager
    def private_environment(_values):yield '/owner-private-env'
    host.private_environment=private_environment
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        if not before_read:change()
        return SimpleNamespace(stdout=b'{"immutable":"authenticated-barrier"}')
    host.run=run
    return host,target,calls


@pytest.mark.parametrize('changed',['policy','running','restarting','container','image'])
def test_recovered_compatibility_barrier_rechecks_hold_after_proof_read(changed):
    host,target,calls=compatibility_barrier_host(changed=changed)
    with pytest.raises(model.DeliveryRefused):
        evidence._compat_barrier(host,{},target)
    assert len(calls)==1


def test_recovered_compatibility_barrier_requires_restart_hold_before_proof_read():
    host,target,calls=compatibility_barrier_host(changed='policy',before_read=True)
    with pytest.raises(model.DeliveryRefused,match='RESTART_HOLD_CHANGED'):
        evidence._compat_barrier(host,{},target)
    assert not calls


def test_exact_stopped_compatibility_barrier_with_restart_hold_is_accepted():
    host,target,calls=compatibility_barrier_host()
    assert evidence._compat_barrier(host,{},target)==dict(method='EXACT_B2_KERNEL_BARRIER',
        acknowledgement={'immutable':'authenticated-barrier'})
    assert len(calls)==1


def test_removing_post_read_inspection_has_a_restart_policy_falsifier(monkeypatch):
    import inspect
    source=inspect.getsource(evidence._compat_barrier)
    before,after=source.split('    value=json.loads(result.stdout)\n',1)
    after=after.replace("    container=host.container('sentinel-shadow')\n",'',1)
    scope=dict(vars(evidence))
    exec(compile(before+'    value=json.loads(result.stdout)\n'+after,'barrier inspection falsifier','exec'),scope)
    monkeypatch.setattr(evidence,'_compat_barrier',scope['_compat_barrier'])
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_recovered_compatibility_barrier_rechecks_hold_after_proof_read('policy')


def test_probe_uses_effective_shadow_subject_instead_of_release_literals():
    host = object.__new__(host_module.Host)
    selected = {'SENTINEL_SHADOW_OBSERVATION_ID': 'another-observer',
        'SENTINEL_SHADOW_STARTING_CASH': '75000.00',
        'SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY': 'reviewed-timing'}
    host.load_values = lambda: {'literal': 'configuration'}
    host.compose = lambda values, *args: SimpleNamespace(stdout=json.dumps(
        {'services': {'sentinel-shadow': {'environment': selected}}}).encode())
    calls = []
    host.run = lambda argv, **kwargs: calls.append((argv, kwargs)) or SimpleNamespace(stdout=b'{}')
    assert host.probe('a'*40, 'sha256:'+'b'*64) == {}
    argv, _ = calls[0]
    assert json.loads(argv[-1]) == selected
    assert "observation_id='primary'" not in argv[-2] and "starting_cash='50000'" not in argv[-2]
    assert 'cash.normalize()' in argv[-2]


class Contention(RuntimeError):
    pass


def run_retry(operation, *, mutation=None):
    clock = SimpleNamespace(value=0, sleeps=[])
    def sleep(value):
        clock.sleeps.append(value)
        clock.value += value
    clock.monotonic = lambda: clock.value
    clock.sleep = sleep
    code = checks.CANONICAL
    if mutation:
        code = code.replace(*mutation)
    tree = ast.parse(code)
    start = next(index for index, node in enumerate(tree.body)
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id == 'started')
    scope = dict(time=clock, CorpusLockUnavailable=Contention,
                 verify_once=lambda: operation(clock), json=json, print=lambda *args: None)
    try:
        exec(compile(ast.Module(body=tree.body[start:], type_ignores=[]), 'actual retry loop', 'exec'), scope)
    finally:
        run_retry.last_clock = clock
    return scope.get('output')


def assert_finite_contention():
    calls = []
    def blocked(clock):
        calls.append(clock.value)
        raise Contention('bounded contention')
    with pytest.raises(Contention):
        run_retry(blocked)
    assert run_retry.last_clock.value == 20
    assert len(calls) == 41


def test_actual_canonical_retry_loop_is_typed_and_keeps_original_20_second_bound():
    assert_finite_contention()
    calls = []
    def recover(clock):
        calls.append(clock.value)
        if len(calls) < 3:
            raise Contention('corpus pin')
        return {'proof': 'complete'}
    assert run_retry(recover) == {'proof': 'complete'} and len(calls) == 3
    def defect(clock):
        raise ValueError('software defect')
    with pytest.raises(ValueError):
        run_retry(defect)
    assert run_retry.last_clock.sleeps == []


def test_canonical_retry_bound_falsifier_is_detected(monkeypatch):
    monkeypatch.setattr(checks, 'CANONICAL', checks.CANONICAL.replace(
        'retry_deadline=min(outer_deadline,now+20)', 'retry_deadline=min(outer_deadline,now+200)'))
    with pytest.raises(AssertionError):
        assert_finite_contention()


def test_proof_cannot_finish_outside_original_outer_deadline():
    def slow(clock):
        clock.value = 301
        return {'proof': 'late'}
    with pytest.raises(AssertionError, match='original deadline'):
        run_retry(slow)


def native_program(monkeypatch, *, account='PAPER-Z', orders=None):
    for key, value in {'ALPACA_BASE_URL': 'https://paper-api.alpaca.markets',
        'SENTINEL_LOCAL_PAPER_ACCOUNT_ID': 'PAPER-Z', 'ALPACA_API_KEY': 'fictional-key',
        'ALPACA_SECRET_KEY': 'fictional-secret'}.items():
        monkeypatch.setenv(key, value)
    calls = []
    def open_request(request, *, timeout):
        calls.append((request.full_url, request.get_method()))
        assert request.get_method() == 'GET' and timeout == 15
        path = request.full_url.removeprefix('https://paper-api.alpaca.markets')
        data = {'/v2/account': {'account_number': account, 'status': 'ACTIVE'},
            '/v2/orders?status=open&limit=500': orders or [],
            '/v2/positions': [{'asset_id': 'different-security', 'qty': '17'}]}[path]
        return io.StringIO(json.dumps(data))
    monkeypatch.setattr(urllib.request, 'urlopen', open_request)
    scope = {'print': lambda *args: None}
    try:
        exec(compile(checks.NATIVE_POSITIONS, 'GET-only native program', 'exec'), scope)
    finally:
        native_program.last_calls = calls
    return scope


def test_native_program_checks_actual_account_and_zero_working_orders_before_positions(monkeypatch):
    assert native_program(monkeypatch)['positions'] == [{'asset_id': 'different-security', 'qty': '17'}]
    assert len(native_program.last_calls) == 3
    with pytest.raises(AssertionError):
        native_program(monkeypatch, account='foreign')
    assert len(native_program.last_calls) == 1
    with pytest.raises(AssertionError):
        native_program(monkeypatch, orders=[{'id': 'working'}])
    assert len(native_program.last_calls) == 2


def test_notification_history_allows_only_append_and_pending_progress():
    before = {key: {'original': 'unchanged'} for key in evidence._NOTIFICATION_GROUPS}
    after = {key: {**value, 'added': 'new'} for key, value in before.items()}
    host = Host(after)
    assert all(count == 1 for count in evidence.check_notification_history(host, before).values())
    host.state['alerts']['original'] = 'changed-acknowledgement-or-payload'
    with pytest.raises(model.DeliveryRefused, match='alerts'):
        evidence.check_notification_history(host, before)


def test_embedded_readers_have_no_release_subject_or_mutation_code():
    for name in ('CANONICAL', 'IDLE', 'PANEL', 'NATIVE_POSITIONS'):
        text = getattr(checks, name)
        compile(text, name, 'exec')
        assert 'PA3NDXAHULSS' not in text and '2026-10-' not in text
        assert not re.search(r'method=[\'"](?:POST|PATCH|DELETE|PUT)[\'"]', text)
    assert not re.search(r'\b(?:INSERT|UPDATE|DELETE|TRUNCATE|CREATE|DROP|ALTER)\b',
                         checks.SNAPSHOT_SQL+checks.NOTIFICATION_SQL)

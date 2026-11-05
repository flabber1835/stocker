"""Financial admission/UNKNOWN/export falsifiers; no canonical replay."""
import ast
import base64
from copy import deepcopy
import gzip
import json
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from types import MethodType

import pytest

CAP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CAP))
import system_campaign_financial_resume as m
from system_campaign_facts import digest


def parent():
    spec = json.loads((CAP / m.PARENTS).read_bytes())['arms']['P03']
    cp = dict(schema='research.pooled-vacancy-backtest/1', sha256=spec['outer_sha256'],
        source_cursor=spec['selected_session'], completed=spec['measured_closes'], base=deepcopy(spec['base']),
        journals=deepcopy(spec['journals']), repairs=deepcopy(spec['repairs']),
        run=dict(checkpoint_sha256=spec['inner_sha256'], state_sha256=spec['state_sha256'], input_sha256=spec['input_sha256']))
    return cp, spec


def stop():
    return dict(stopped=True, exit_code=0, oom_killed=False)


def proof():
    return dict(complete=True, counts=dict(formation=126, daily=2156),
                all_prefixes_verified=True, all_daily_factors_and_chains_verified=True)


def test_actual_request_preserves_every_frozen_driver_and_selects_only_unfinished():
    r = m.expected_request()
    assert r['arms'] == ['P07']
    assert r['maximum_parallel_financial_workers'] == 0
    assert r['maximum_parallel_readonly_workers'] == 1
    assert r['readonly_partial_review'] is r['financial_resume_authorized'] is False
    assert r['readonly_source_witnesses'] is True and m.request_authority(r)
    scope = r['source_witness_scopes']['P07']
    assert len(scope['terms']) == len(scope['additional_rows']) == 1
    assert scope['terms'][0]['ticker'] == 'ABMD' and scope['additional_rows'][0]['session'] == '2022-12-21'
    assert r['new_origin'] is r['diagnostic_state_adopted'] is False
    assert r['arm_inputs'] == {'P07':dict(new_factual_overlay=False,restored_correlation=False)}
    assert r['admitted_checkpoints'] == {a:m.root_spec(a)['outer_sha256'] for a in r['arms']}
    assert r['initial_reporting_origins'] == {} and r['selected_ordinary_augmentations'] == {}
    assert set(r['selected_research_models']) == {'P07'}
    assert r['full_measured_closes'] == 2156 and 'P11' in m.COMPLETED_ADMISSIONS
    assert sum(r[k] for k in ['financial_wait_seconds', 'review_wait_seconds', 'preflight_wait_seconds']) <= 245 * 60


def test_existing_workflow_selects_qualified_job_without_overlapping_own_arm():
    import yaml
    workflow = yaml.load((CAP.parent.parent / m.WORKFLOW).read_bytes(), Loader=yaml.BaseLoader)
    job = workflow['jobs']['suffix']
    assert job['strategy']['matrix']['arm'] == list(m.SELECTED_ARMS)
    assert job['strategy']['max-parallel'] == '1'
    assert 'concurrency' not in workflow
    assert job['concurrency'] == dict(group='system-optimization-002-financial-${{ matrix.arm }}', **{'cancel-in-progress':'false'})
    assert job['timeout-minutes'] == '285'
    assert workflow['permissions'] == {'contents': 'read', 'actions': 'read'}
    assert workflow['on']['push']['paths'] == ['research/capital_risk/' + m.REQUEST]
    assert any('system_campaign_financial_resume.py' in s.get('run', '') for s in job['steps'])
    checkout = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/checkout@'))
    assert '.github/workflows' in checkout['with']['sparse-checkout'].splitlines()
    installation = next(s for s in job['steps'] if s.get('name') == 'Install locked transfer dependencies')
    assert 'wwe-transfer-requirements.lock' in installation['run']
    probe = next(i for i, s in enumerate(job['steps']) if '--probe --request' in s.get('run', ''))
    staging = next(i for i, s in enumerate(job['steps']) if s.get('name') == 'Authenticate existing frozen inputs and offline runtime')
    assert 'system_campaign_stage_transport.py --factual-request' in job['steps'][staging]['run']
    assert job['steps'][staging]['env']['GH_TOKEN'] == '${{ github.token }}'
    assert probe < staging


def test_isolated_host_import_reproduces_missing_schema_dependency_and_then_passes(tmp_path):
    site = tmp_path / 'isolated-site'
    site.mkdir()
    def copy_package(name):
        spec = importlib.util.find_spec(name)
        assert spec is not None, name
        if spec.submodule_search_locations:
            source = Path(next(iter(spec.submodule_search_locations)))
            shutil.copytree(source, site / name)
        else:
            shutil.copyfile(spec.origin, site / Path(spec.origin).name)
    for name in ['cryptography', 'cffi', 'pycparser', '_cffi_backend']:
        copy_package(name)
    code = '''import sys,runpy,importlib.abc
assert not any('site-packages' in p for p in sys.path)
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel')):
   raise ImportError('ISOLATED_PROBE_FORBIDS_CANONICAL_RUNTIME:'+fullname)
sys.meta_path.insert(0,Fence())
sys.path[:0]=[sys.argv[1],sys.argv[2]]
script=sys.argv[1]+'/system_campaign_financial_resume.py'
sys.argv=[script,'--probe','--request',sys.argv[1]+'/system-campaign-factual-request.json']
runpy.run_path(script,run_name='__main__')
'''
    command = [sys.executable, '-I', '-S', '-B', '-c', code, str(CAP), str(site)]
    failed = subprocess.run(command, capture_output=True, timeout=60)
    assert failed.returncode != 0 and b"No module named 'pydantic'" in failed.stderr
    for name in ['pydantic', 'pydantic_core', 'annotated_types', 'typing_extensions', 'typing_inspection']:
        copy_package(name)
    passed = subprocess.run(command, capture_output=True, timeout=60)
    assert passed.returncode == 0, passed.stderr.decode(errors='replace')
    assert json.loads(passed.stdout)['financial_runtime_executed'] is False


def test_actual_original_parent_and_no_diagnostic_substitution():
    cp, spec = parent()
    assert m.strict_parent(cp, spec) is cp
    for changed in [dict(schema='research.disposable-trading-discovery-checkpoint/1'),
                    dict(authority='DISCOVERY_ONLY_NOT_FINANCIAL_AUTHORITY'), dict(financial_authority=False)]:
        with pytest.raises(ValueError):
            m.strict_parent(dict(cp, **changed), spec)


def test_removed_diagnostic_guard_fails_the_admission_assertion(monkeypatch):
    cp, spec = parent()
    cp['financial_authority'] = False
    def refused():
        try: m.strict_parent(cp, spec)
        except ValueError: return True
        return False
    assert refused()
    monkeypatch.setattr(m, 'require_strict_checkpoint', lambda value: value)
    with pytest.raises(AssertionError):
        assert refused()


@pytest.mark.parametrize('field', ['sha256', 'source_cursor', 'completed', 'base', 'journals', 'repairs'])
def test_wrong_parent_or_prefix_refused(field):
    cp, spec = parent()
    cp[field] = None
    with pytest.raises(ValueError):
        m.strict_parent(cp, spec)


@pytest.mark.parametrize('field', ['checkpoint_sha256', 'state_sha256', 'input_sha256'])
def test_wrong_inner_identity_refused(field):
    cp, spec = parent()
    cp['run'][field] = '0' * 64
    with pytest.raises(ValueError):
        m.strict_parent(cp, spec)


@pytest.mark.parametrize('key,value', [('stopped', False), ('exit_code', 1), ('exit_code', False), ('oom_killed', True)])
def test_incomplete_stop_never_satisfies_preflight_or_completion(key, value):
    bad = dict(stop(), **{key: value})
    assert not m.successful_stop(bad)
    assert not m.complete_review(bad, stop(), proof())
    assert not m.complete_review(stop(), bad, proof())


def test_complete_review_requires_entire_axis_and_all_proofs():
    assert m.complete_review(stop(), stop(), proof())
    for changed in [dict(counts=dict(formation=126, daily=2155)), dict(complete=False),
                    dict(all_prefixes_verified=False), dict(all_daily_factors_and_chains_verified=False)]:
        assert not m.complete_review(stop(), stop(), dict(proof(), **changed))


def test_original_gzip_dedup_preserves_names_and_exact_bytes(tmp_path):
    old, out = tmp_path / 'old', tmp_path / 'out'
    (old / 'book/month-end').mkdir(parents=True)
    (old / 'lineage/original-checkpoints').mkdir(parents=True)
    raw = gzip.compress(b'{"synthetic_checkpoint":true}\n', mtime=0)
    (old / 'book/month-end/a.json.gz').write_bytes(raw)
    (old / 'lineage/original-checkpoints/copy.json.gz').write_bytes(raw)
    (old / 'book/interrupted-daily-old.jsonl').write_bytes(b'original unadmitted tail\n')
    m.preserve_originals(old, out, {'arm': 'P03'})
    index = json.loads((out / 'lineage/original-checkpoint-inventory.json').read_bytes())
    assert len(index) == 2 and len(list((out / 'lineage/original-checkpoints').iterdir())) == 1
    assert {v['sha256'] for v in index.values()} == {m.sha(raw)}
    assert all((out / v['stored']).read_bytes() == raw for v in index.values())
    assert (out / 'lineage/prior-interrupted-tails/interrupted-daily-old.jsonl').read_bytes() == b'original unadmitted tail\n'
    m.verify_originals(old, out)
    index.pop(next(iter(index)))
    (out / 'lineage/original-checkpoint-inventory.json').write_text(json.dumps(index))
    with pytest.raises(ValueError, match='NO_ORIGINAL_GZIP_OMISSIONS'):
        m.verify_originals(old, out)


def test_real_synthetic_aes_gcm_export_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'protocol_sha256': 'b' * 64}))
    result = m.export_probe(tmp_path / 'marker', request, 'P03', b'k' * 32)
    assert result['status'] == 'REAL_SYNTHETIC_ENCRYPTED_EXPORT_ROUNDTRIP_PASSED'
    assert result['financial_sessions_advanced'] == 0


def launch_fixture(tmp_path, monkeypatch, event):
    import ephemeral_runner_capacity as capacity
    import system_campaign_financial_future as future
    import system_campaign_financial_review_repair as repair
    if not event.startswith('readonly-repair'):
        # Keep ordinary launch fixtures independent of the currently selected
        # real failed-review target; dedicated cases exercise that extra gate.
        monkeypatch.setattr(repair, 'applies', lambda spec: False)
    monkeypatch.setattr(future, 'stage_selected_sources', lambda *args: None)
    request = dict(m.expected_request())
    monkeypatch.setattr(m,'SELECTED_ARMS',('P07',))
    request.update(arms=['P07'],readonly_partial_review=event.startswith('readonly'),
                   financial_resume_authorized=not event.startswith(('readonly','witness')),
                   readonly_source_witnesses=event.startswith('witness'),
                   execution_mode=('READONLY_FROZEN_SOURCE_WITNESSES' if event.startswith('witness')
                       else 'READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION' if event.startswith('readonly')
                       else 'OWN_ADMITTED_FINANCIAL_CONTINUATION'))
    if event.startswith('witness'):
        from research.capital_risk.forecast_tests.test_financial_source_witnesses import source_fixture
        cp,scope,natives,rows=source_fixture()
        natives[0]['session'] = '2023-01-10'
        rows[0]['session'] = '2023-01-09'
        scope['terms'][0].update(session=rows[0]['session'], native_session=natives[0]['session'],
                                 native_term_sha256=future.digest(natives[0]))
        actual=m.root_spec('P07')
        cp.update(sha256=actual['outer_sha256'],source_cursor=actual['selected_session'],base=actual['base'])
        scope.update(parent_outer_sha256=cp['sha256'],parent_cursor=cp['source_cursor'])
        request['source_witness_scopes']={'P07':scope}
    request_path = tmp_path / 'request.json'
    if event.startswith('readonly-repair'):
        from system_campaign_financial_requalified_parent import validated
        historical=validated(m.root_spec('P07','75e0e1cfee3007e1ff47a638e62597ed49820c1ecc8a7c1cfc7675c9db800719'))[0]
        fixture_parts=json.loads((CAP/m.PARTIALS).read_bytes())
        fixture_parts['arms']['P07']=historical
        fixture_path=tmp_path/'historical-failed-review-partials.json'
        fixture_path.write_text(json.dumps(fixture_parts))
        monkeypatch.setattr(m,'PARTIALS',str(fixture_path))
    request_path.write_text(json.dumps(request))
    stage_path, cap_path = tmp_path / 'stage.json', tmp_path / 'capacity.json'
    stage_path.write_text('{}'); cap_path.write_text('{}')
    old = tmp_path / 'old'; old.mkdir()
    binding = {'parameters': {}}
    (old / 'source-bindings.json').write_text(json.dumps(binding))
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '1')
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    monkeypatch.setenv(m.SECRET, base64.b64encode(b'k' * 32).decode())
    monkeypatch.setattr(m, 'check_context', lambda env: None)
    monkeypatch.setattr(m, 'expected_request', lambda: request)
    monkeypatch.setattr(m, 'stage_valid', lambda value: None)
    monkeypatch.setattr(capacity, 'validate_prepared_receipt', lambda *a, **k: None)
    monkeypatch.setattr(m, 'export_probe', lambda *a: {'synthetic': True})
    monkeypatch.setattr(m, 'transport_admit', lambda *a: old)
    monkeypatch.setattr(m, 'admit_partial', lambda *a: old)
    monkeypatch.setattr(m, 'memory_bytes', lambda: {'MemAvailable': 20 * 1024**3})
    monkeypatch.setattr(m.shutil, 'disk_usage', lambda p: SimpleNamespace(free=50 * 1024**3))
    def build(source, dest, parameters):
        dest.mkdir(); return binding
    monkeypatch.setattr(m, 'build', build)
    monkeypatch.setattr(m, 'command', lambda *a: ['--entrypoint', 'python', '-B'])
    calls, exports = [], []
    def worker(values, name, output, **kwargs):
        mode = values[values.index('--mode') + 1]; calls.append(mode)
        if event == 'unknown-' + mode:
            raise m.StopUnknown('synthetic unknown')
        if mode == 'review' and event == 'readonly-repair-unknown':
            raise m.StopUnknown('synthetic readonly repair review unknown')
        if mode == 'preflight':
            for filename in ['strict-parent-preflight.json', 'old-prefix-canonical-review.json']:
                (output / filename).write_text('{}')
            spec=json.loads((output/'spec.json').read_bytes())
            monthly=dict(passed=True,checkpoint_sha256=spec['outer_sha256'],completed=spec['measured_closes'],
                         all_new_monthly_reports_exact=True,all_monthly_checkpoint_state_exact=True,financial_transitions_reexecuted=0)
            if event=='readonly-bad-monthly':monthly['all_monthly_checkpoint_state_exact']=False
            (output/'monthly-reproduction.json').write_text(json.dumps(monthly))
            if event.startswith('witness'):
                import system_campaign_financial_future as future
                payload=future.witness_payload(cp,'P07',scope,natives,rows)
                if event=='witness-bad-payload':payload['terms'][0]['source_row']['raw_close']='WRONG'
                (output/future.SOURCE_WITNESS_FILE).write_text(json.dumps(payload))
                (output/'source-witness-request.json').write_bytes(b'changed' if event=='witness-wrong-request' else request_path.read_bytes())
                if event=='witness-unknown-preflight':raise m.StopUnknown('synthetic source stop unknown')
            if event == 'failed-preflight': return dict(stop(), exit_code=1)
        if mode == 'review':
            (output / 'core-review.json').write_text(json.dumps(proof()))
            if event == 'readonly-repair-refused': return dict(stop(), exit_code=1)
        return stop()
    monkeypatch.setattr(m, 'stopped_run', worker)
    def seal(root, *args, **kwargs):
        exports.append(root); return {'synthetic_cipher': True}
    monkeypatch.setattr(m, 'seal', seal)
    args = SimpleNamespace(request=request_path, staging=stage_path, capacity=cap_path,
                           arm='P07', output=tmp_path / 'artifacts/receipt.json')
    return args, calls, exports


def test_failed_parent_review_cannot_launch_finance(tmp_path, monkeypatch):
    args, calls, exports = launch_fixture(tmp_path, monkeypatch, 'failed-preflight')
    assert m.launch(args) == 2 and calls == ['preflight']
    assert len(exports) == 1


@pytest.mark.parametrize('event,expected', [('failed-preflight', []), ('unknown-economic', [['preflight']]), ('readonly', [])])
def test_public_source_staging_occurs_only_after_successful_preflight_before_finance(tmp_path, monkeypatch, event, expected):
    import system_campaign_financial_future as future
    args, calls, exports = launch_fixture(tmp_path, monkeypatch, event)
    stages = []
    monkeypatch.setattr(future, 'stage_selected_sources', lambda *args: stages.append(list(calls)))
    m.launch(args)
    assert stages == expected


def test_unknown_financial_writer_cannot_export_mutable_snapshot(tmp_path, monkeypatch):
    args, calls, exports = launch_fixture(tmp_path, monkeypatch, 'unknown-economic')
    assert m.launch(args) == 2 and calls == ['preflight', 'economic'] and exports == []
    receipt = json.loads(args.output.read_bytes())
    assert receipt['status'] == 'WRITER_UNKNOWN_NO_MUTABLE_EXPORT' and 'encrypted_output' not in receipt


def test_removed_unknown_writer_fence_fails_the_no_export_assertion(tmp_path, monkeypatch):
    args, calls, exports = launch_fixture(tmp_path, monkeypatch, 'unknown-economic')
    tree = ast.parse((CAP / 'system_campaign_financial_resume.py').read_bytes())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'launch')
    region = next(n for n in fn.body if isinstance(n, ast.Try))
    sites = [n for n in ast.walk(region) if isinstance(n, ast.Assign)
             and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
             and n.targets[0].id == 'stopped_snapshot' and isinstance(n.value, ast.Constant)
             and n.value.value is False]
    assert len(sites) == 1
    class Remove(ast.NodeTransformer):
        def visit_Assign(self,node):
            return None if node is sites[0] else self.generic_visit(node)
    fn=Remove().visit(fn)
    namespace = dict(vars(m))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-unknown-writer-fence>', 'exec'), namespace)
    assert namespace['launch'](args) == 2
    with pytest.raises(AssertionError): assert exports == []


def test_unknown_reviewer_preserves_only_positively_stopped_financial_output(tmp_path, monkeypatch):
    args, calls, exports = launch_fixture(tmp_path, monkeypatch, 'unknown-review')
    assert m.launch(args) == 2 and calls == ['preflight', 'economic', 'review']
    assert len(exports) == 1 and not (exports[0] / 'stopped-review').exists()
    assert json.loads(args.output.read_bytes())['status'] == 'REVIEW_UNKNOWN_STOPPED_FINANCIAL_PRESERVED'


def test_readonly_success_exports_only_stopped_review_and_never_launches_finance(tmp_path,monkeypatch):
    args,calls,exports=launch_fixture(tmp_path,monkeypatch,'readonly')
    assert m.launch(args)==0 and calls==['preflight'] and len(exports)==1
    receipt=json.loads(args.output.read_bytes())
    assert receipt['status']=='READONLY_PARTIAL_REVIEW_PASSED_PENDING_ROOT'
    assert receipt['financial_resume_authorized'] is False and receipt['readonly_partial_review'] is True
    assert 'worker' not in receipt and 'reviewer' not in receipt


def test_readonly_monthly_mismatch_cannot_report_success_or_launch_finance(tmp_path,monkeypatch):
    args,calls,exports=launch_fixture(tmp_path,monkeypatch,'readonly-bad-monthly')
    assert m.launch(args)==2 and calls==['preflight'] and len(exports)==1
    assert json.loads(args.output.read_bytes())['status']=='REFUSED_STOPPED_EVIDENCE_PRESERVED'


def test_invalid_readonly_authority_refuses_before_any_worker(tmp_path,monkeypatch):
    args,calls,exports=launch_fixture(tmp_path,monkeypatch,'readonly')
    request=json.loads(args.request.read_bytes());request['financial_resume_authorized']=True
    args.request.write_text(json.dumps(request));monkeypatch.setattr(m,'expected_request',lambda:request)
    with pytest.raises(ValueError,match='EXACT_FINANCIAL_OR_READONLY_AUTHORITY'):m.launch(args)
    assert calls==exports==[]


def test_readonly_authority_guard_removal_is_detected_by_preflight_order(tmp_path,monkeypatch):
    args,calls,exports=launch_fixture(tmp_path,monkeypatch,'readonly')
    request=json.loads(args.request.read_bytes());request['financial_resume_authorized']=True
    args.request.write_text(json.dumps(request));monkeypatch.setattr(m,'expected_request',lambda:request)
    fn=next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='launch')
    sites=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and
           any(isinstance(a,ast.Constant) and a.value=='RESUME_EXACT_FINANCIAL_OR_READONLY_AUTHORITY' for a in n.value.args)]
    assert len(sites)==1;fn.body.remove(sites[0]);namespace=dict(vars(m))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-readonly-authority-order>','exec'),namespace)
    namespace['launch'](args)
    with pytest.raises(AssertionError):assert calls==exports==[]


def test_preflight_guard_removal_falsifier(tmp_path, monkeypatch):
    args, calls, exports = launch_fixture(tmp_path, monkeypatch, 'failed-preflight')
    original = m.successful_stop
    monkeypatch.setattr(m, 'successful_stop', lambda value: True)
    # The same failed preflight now leaks a financial launch; the protected
    # scenario above explicitly asserts the opposite.
    m.launch(args)
    assert calls != ['preflight']
    monkeypatch.setattr(m, 'successful_stop', original)


def test_oom_guard_removal_is_caught_by_same_completion_assertion():
    tree = ast.parse((CAP / 'system_campaign_financial_resume.py').read_bytes())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'successful_stop')
    boolean = fn.body[0].value
    boolean.values.pop()  # remove the actual OOM refusal
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-oom-guard>', 'exec'), namespace)
    bad = dict(stop(), oom_killed=True)
    assert not m.successful_stop(bad)
    with pytest.raises(AssertionError):
        assert not namespace['successful_stop'](bad)


@pytest.mark.parametrize('bad', [None, 'network', 'swap', 'credentials', 'entrypoint', 'command', 'writable_input'])
@pytest.mark.parametrize('arm', ['p03', 'p04'])
def test_actual_inspector_fences_and_entrypoint(tmp_path, monkeypatch, bad, arm):
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setattr(m.os, 'getuid', lambda: 1000, raising=False)
    monkeypatch.setattr(m.os, 'getgid', lambda: 1000, raising=False)
    name = 'capital-system-resume-' + arm + '-worker-123-1'
    value = dict(Name='/' + name, Image=m.EXECUTION_IMAGE, Id='a' * 64,
        HostConfig=dict(NetworkMode='none', Memory=8*1024**3, MemorySwap=8*1024**3,
            NanoCpus=2000000000, PidsLimit=64, ReadonlyRootfs=True, CapDrop=['ALL'],
            SecurityOpt=['no-new-privileges']),
        Mounts=[dict(Type='bind', Destination=p, RW=p=='/out')
                for p in ['/variant', '/frozen', '/driver', '/old', '/out'] + (['/correlation-prefix'] if arm=='p04' else [])],
        Config=dict(WorkingDir='/variant', User='1000:1000', Entrypoint=['python'], Env=[],
            Labels={'research.study':'full-system-search-20261029', 'research.role':'worker'},
            Cmd=['-B','-u','/driver/system_campaign_financial_resume.py','--mode','economic','--spec','/out/spec.json']))
    if bad == 'network': value['HostConfig']['NetworkMode'] = 'bridge'
    if bad == 'swap': value['HostConfig']['MemorySwap'] += 1
    if bad == 'credentials': value['Config']['Env'] = ['GH_TOKEN=synthetic']
    if bad == 'entrypoint': value['Config']['Entrypoint'] = ['/bin/sh']
    if bad == 'command': value['Config']['Cmd'][-1] = '/out/other.json'
    if bad == 'writable_input': value['Mounts'][0]['RW'] = True
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=json.dumps([value])))
    if bad is None: assert m.inspect(name)['Id'] == 'a' * 64
    else:
        with pytest.raises(ValueError): m.inspect(name)


def prefix_fixture(tmp_path, monkeypatch):
    old, aux = tmp_path / 'old', tmp_path / 'aux'
    (old / 'book').mkdir(parents=True); aux.mkdir()
    binding = b'{"parameters":{"inert":true}}\n'
    for root in (old, aux): (root / 'source-bindings.json').write_bytes(binding)
    cp = dict(sha256='f'*64, completed=1, source_cursor='2018-12-31', base={'inert':True},
              journals={}, run={'state_sha256':'b'*64})
    chain = digest('system-optimization-002/raw-correlation/1'); rows = []
    for stream, day, state in [('formation','2017-12-29','a'*64), ('daily','2018-12-31','b'*64)]:
        raw = (json.dumps(dict(session=day,state_sha256=state))+'\n').encode()
        (old / 'book' / (stream+'.jsonl')).write_bytes(raw)
        cp['journals'][stream] = dict(bytes=len(raw), prefix_sha256=m.sha(raw))
        row = dict(session=day,next_state_sha256=state)
        chain = digest(dict(previous=chain,record=row))
        rows.append((json.dumps(dict(row,chain_sha256=chain))+'\n').encode())
    (old / 'book/checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(cp).encode()))
    # Auxiliary future rows must be filtered before they enter the offline capsule.
    capture = gzip.compress(b''.join(rows)+b'{"session":"2021-03-31"}\n')
    (aux / 'correlation-inputs.jsonl.gz').write_bytes(capture)
    descriptor = dict(financial_parent_outer_sha256=cp['sha256'],financial_parent_completed=1,
        financial_parent_cursor=cp['source_cursor'],transport=dict(base=cp['base'],
            source_binding_sha256=m.sha(binding),artifact_id=123),
        observation_member=dict(name='correlation-inputs.jsonl.gz',bytes=len(capture),sha256=m.sha(capture)),
        prefix=dict(rows=2,raw_sha256=m.sha(b''.join(rows)),through=cp['source_cursor']))
    monkeypatch.setattr(m, 'prefix_descriptor', lambda: descriptor)
    return old, aux, cp, descriptor, rows


def test_auxiliary_history_restores_only_exact_parent_observations(tmp_path, monkeypatch):
    old, aux, cp, descriptor, rows = prefix_fixture(tmp_path, monkeypatch)
    capsule = m.prepare_prefix(old, aux, tmp_path / 'capsule')
    assert m.seed_rows(old, cp, {'arm':'P04'}, capsule) == rows
    assert set(p.name for p in capsule.iterdir()) == {'provenance.json','correlation-inputs.jsonl.gz'}
    assert gzip.decompress((capsule/'correlation-inputs.jsonl.gz').read_bytes()) == b''.join(rows)
    assert json.loads((capsule/'provenance.json').read_bytes())['auxiliary_financial_state_adopted'] is False
    assert not any('checkpoint' in p.name for p in capsule.iterdir())


@pytest.mark.parametrize('change',['source','state','chain','missing','wrong_parent','prefix_hash'])
def test_auxiliary_prefix_mismatch_refuses_before_capsule_creation(tmp_path, monkeypatch, change):
    old, aux, cp, descriptor, rows = prefix_fixture(tmp_path, monkeypatch)
    if change == 'source': (aux/'source-bindings.json').write_bytes(b'changed')
    elif change == 'state':
        raw = (old/'book/daily.jsonl').read_bytes().replace(b'b'*64,b'c'*64)
        (old/'book/daily.jsonl').write_bytes(raw)
    elif change == 'wrong_parent': descriptor['financial_parent_outer_sha256'] = '0'*64
    elif change == 'prefix_hash': descriptor['prefix']['raw_sha256'] = '0'*64
    else:
        raw = b''.join(rows).replace(b'chain_sha256',b'wrong_chain') if change == 'chain' else rows[0]
        capture = gzip.compress(raw)
        (aux/'correlation-inputs.jsonl.gz').write_bytes(capture)
        descriptor['observation_member'].update(bytes=len(capture),sha256=m.sha(capture))
    with pytest.raises((ValueError,KeyError)):
        m.prepare_prefix(old, aux, tmp_path/'capsule')
    assert not (tmp_path/'capsule').exists()


def test_future_capsule_guard_and_its_removal_falsifier(tmp_path, monkeypatch):
    old, aux, cp, descriptor, rows = prefix_fixture(tmp_path, monkeypatch)
    capsule = m.prepare_prefix(old,aux,tmp_path/'capsule')
    (capsule/'correlation-inputs.jsonl.gz').write_bytes(gzip.compress(b''.join(rows)+b'{"session":"2021-03-31"}\n'))
    with pytest.raises(ValueError,match='NO_FUTURE_OBSERVATIONS'): m.seed_rows(old,cp,{'arm':'P04'},capsule)
    node = next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='seed_rows')
    node.body.pop(-2)  # actual no-future-observation guard
    namespace = dict(vars(m))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-future-row-guard>','exec'),namespace)
    assert namespace['seed_rows'](old,cp,{'arm':'P04'},capsule) == rows


def test_forged_capsule_provenance_refuses(tmp_path, monkeypatch):
    old,aux,cp,_,_ = prefix_fixture(tmp_path,monkeypatch)
    capsule = m.prepare_prefix(old,aux,tmp_path/'capsule')
    value=json.loads((capsule/'provenance.json').read_bytes());value['auxiliary_financial_state_adopted']=True
    (capsule/'provenance.json').write_text(json.dumps(value))
    with pytest.raises(ValueError,match='CAPSULE_PROVENANCE'): m.seed_rows(old,cp,{'arm':'P04'},capsule)


def test_neutral_adoption_gate_blocks_advance_and_preserves_actual_written_gzip(tmp_path):
    from research.capital_risk.forecast_tests.test_pxd_pause import pair, OVERLAY
    before,after,_=pair()
    book=tmp_path/'book';book.mkdir()
    gate=m.AdoptionGate(before,book,tmp_path/'adoption',OVERLAY,'2024-05-02')
    writes=[];advances=[]
    def write(path,value):
        writes.append(deepcopy(value));Path(path).write_bytes(gzip.compress(json.dumps(value).encode()))
    gate.original_write=write;gate.original_advance=lambda *a:advances.append(a)
    with pytest.raises(ValueError,match='ADOPTION_REQUIRED'):gate.advance('inert')
    assert writes==advances==[]
    gate.write(book/'checkpoint.json.gz',before)
    with pytest.raises(ValueError,match='ADOPTION_REQUIRED'):gate.advance('inert')
    bad=deepcopy(after);bad['economics']['nav']='124'
    with pytest.raises(ValueError):gate.write(book/'checkpoint.json.gz',bad)
    assert len(writes)==1
    gate.write(book/'checkpoint.json.gz',after)
    assert (tmp_path/'adoption/checkpoint.json.gz').read_bytes()==(book/'checkpoint.json.gz').read_bytes()
    assert json.loads((tmp_path/'adoption/proof.json').read_bytes())['financial_state_unchanged'] is True
    gate.advance('inert');assert advances==[('inert',)]


def test_adoption_guard_removal_falsifier(tmp_path):
    from research.capital_risk.forecast_tests.test_pxd_pause import pair, OVERLAY
    before,_,_=pair();gate=m.AdoptionGate(before,tmp_path,tmp_path/'adoption',OVERLAY,'2024-05-02')
    advances=[];gate.original_advance=lambda *a:advances.append(a)
    with pytest.raises(ValueError,match='ADOPTION_REQUIRED'):gate.advance('inert')
    cls=next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='AdoptionGate')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='advance');fn.body.pop(0)
    namespace=dict(vars(m));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-adoption-guard>','exec'),namespace)
    MethodType(namespace['advance'],gate)('inert')
    assert advances==[('inert',)]


def p10_financial_parent():
    value=json.loads((CAP/m.PARENTS).read_bytes())['arms']['P10']
    return dict(base=deepcopy(value['base']),source_cursor=value['selected_session'],
                run=dict(checkpoint_sha256=value['inner_sha256']))


def test_p10_reuses_only_literal_primary_input_with_own_financial_predecessor():
    cp=p10_financial_parent();before=deepcopy(cp)
    document,retained=m.p10_document(cp)
    assert cp==before and document['predecessor_checkpoint_sha256']==cp['run']['checkpoint_sha256']
    assert document['predecessor_checkpoint_sha256']!=retained['runtime_checkpoint_sha256']
    assert document['schema']=='terminal-repair/1' and len(document['add'])==len(document['suppress'])==1
    assert document['suppress'][0]['session']=='2019-02-14'
    term,=document['add'];assert term['session']=='2019-02-15' and term['cash_per_share']==42.75
    assert term['security_id']=='1144531901989620662' and term['kind']=='CASH_MERGER'
    assert set(document)=={'schema','predecessor_checkpoint_sha256','source_evidence','suppress','add'}
    assert cp['base']['sources']==retained['base']['sources'] and len(cp['base']['sources'])==224


@pytest.mark.parametrize('change',['source','policy','consumed'])
def test_p10_wrong_source_policy_or_consumed_publication_refuses(change):
    cp=p10_financial_parent()
    if change=='source':cp['base']['sources'][next(iter(cp['base']['sources']))]='0'*64
    elif change=='policy':cp['base']['policy']='wealth-core-v5'
    else:cp['source_cursor']='2019-02-14'
    with pytest.raises(ValueError,match='P10_EXACT_OWN_BASE'):m.p10_document(cp)


def test_p10_actual_base_equality_guard_removal_falsifier():
    cp=p10_financial_parent();cp['base']['sources'][next(iter(cp['base']['sources']))]='0'*64
    with pytest.raises(ValueError,match='P10_EXACT_OWN_BASE'):m.p10_document(cp)
    fn=next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='p10_document')
    sites=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and
           any(isinstance(a,ast.Constant) and a.value=='RESUME_P10_EXACT_OWN_BASE_AND_RETAINED_INPUT_QUALIFICATION' for a in n.value.args)]
    assert len(sites)==1;fn.body.remove(sites[0]);namespace=dict(vars(m))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-p10-base-guard>','exec'),namespace)
    assert namespace['p10_document'](cp)[0]['add'][0]['cash_per_share']==42.75


def ordinary_pair():
    cp=dict(run=dict(checkpoint_sha256='c'*64))
    def document(day,sid):
        return dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='c'*64,
                    source_evidence=[dict(reference=sid,sha256='e'*64)],
                    suppress=[dict(session=day,security_id=sid,term_sha256='d'*64)],
                    add=[dict(session=day,security_id=sid)])
    return cp,[document('2019-07-30','ARRAY'),document('2019-07-31','DATA')]


def test_composition_preserves_each_input_and_binds_only_selected_parent():
    cp,documents=ordinary_pair();before=deepcopy(documents)
    result=m.combine_documents(documents,cp)
    assert documents==before
    assert result['predecessor_checkpoint_sha256']==cp['run']['checkpoint_sha256']
    assert all(result[k]==[r for d in documents for r in d[k]] for k in ('source_evidence','suppress','add'))
    result['add'][0]['security_id']='changed';assert documents==before


@pytest.mark.parametrize('change',['schema','predecessor','missing','duplicate_add','duplicate_suppress'])
def test_ordinary_composition_rejects_mixed_parents_or_duplicate_terms(change):
    cp,documents=ordinary_pair()
    if change=='schema':documents[1]['schema']='diagnostic-input/1'
    elif change=='predecessor':documents[1]['predecessor_checkpoint_sha256']='0'*64
    elif change=='missing':documents[1].pop('source_evidence')
    else:
        field=change.removeprefix('duplicate_');documents[1][field]=deepcopy(documents[0][field])
    with pytest.raises(ValueError):m.combine_documents(documents,cp)


@pytest.mark.parametrize('guard,change',[
    ('RESUME_COMPOSE_ONLY_EXACT_OWN_ORDINARY_DOCUMENTS','predecessor'),
    ('RESUME_NO_DUPLICATE_TERMINAL_INPUT_KEYS','add')])
def test_actual_input_composition_guard_removal_falsifiers(guard,change):
    cp,documents=ordinary_pair()
    if change=='predecessor':documents[1]['predecessor_checkpoint_sha256']='0'*64
    else:documents[1]['add']=deepcopy(documents[0]['add'])
    with pytest.raises(ValueError):m.combine_documents(documents,cp)
    fn=next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='combine_documents')
    sites=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and
           any(isinstance(a,ast.Constant) and a.value==guard for a in n.value.args)]
    assert len(sites)==1;fn.body.remove(sites[0]);namespace=dict(vars(m))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-ordinary-composition-guard>','exec'),namespace)
    assert namespace['combine_documents'](documents,cp)

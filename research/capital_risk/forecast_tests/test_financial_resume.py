"""Financial admission/UNKNOWN/export falsifiers; no canonical replay."""
import ast
import base64
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

CAP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CAP))
import system_campaign_financial_resume as m


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
    assert r['arms'] == ['P03', 'P04', 'P05', 'P06', 'P07', 'P09', 'P10', 'P11']
    assert r['maximum_parallel_financial_workers'] == 1
    assert r['new_origin'] is r['diagnostic_state_adopted'] is r['new_factual_overlay'] is False
    assert r['full_measured_closes'] == 2156
    assert sum(r[k] for k in ['financial_wait_seconds', 'review_wait_seconds', 'preflight_wait_seconds']) <= 245 * 60


def test_existing_workflow_selects_exactly_the_serial_financial_batch():
    import yaml
    workflow = yaml.load((CAP.parent.parent / m.WORKFLOW).read_bytes(), Loader=yaml.BaseLoader)
    job = workflow['jobs']['suffix']
    assert job['strategy']['matrix']['arm'] == list(m.ARMS)
    assert job['strategy']['max-parallel'] == '1'
    assert job['timeout-minutes'] == '285'
    assert workflow['permissions'] == {'contents': 'read', 'actions': 'read'}
    assert workflow['on']['push']['paths'] == ['research/capital_risk/' + m.REQUEST]
    assert any('system_campaign_financial_resume.py' in s.get('run', '') for s in job['steps'])
    checkout = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/checkout@'))
    assert '.github/workflows' in checkout['with']['sparse-checkout'].splitlines()


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
    request = dict(m.expected_request())
    request_path = tmp_path / 'request.json'
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
        if mode == 'preflight':
            for filename in ['strict-parent-preflight.json', 'old-prefix-canonical-review.json']:
                (output / filename).write_text('{}')
            if event == 'failed-preflight': return dict(stop(), exit_code=1)
        if mode == 'review': (output / 'core-review.json').write_text(json.dumps(proof()))
        return stop()
    monkeypatch.setattr(m, 'stopped_run', worker)
    def seal(root, *args, **kwargs):
        exports.append(root); return {'synthetic_cipher': True}
    monkeypatch.setattr(m, 'seal', seal)
    args = SimpleNamespace(request=request_path, staging=stage_path, capacity=cap_path,
                           arm='P03', output=tmp_path / 'artifacts/receipt.json')
    return args, calls, exports


def test_failed_parent_review_cannot_launch_finance(tmp_path, monkeypatch):
    args, calls, exports = launch_fixture(tmp_path, monkeypatch, 'failed-preflight')
    assert m.launch(args) == 2 and calls == ['preflight']
    assert len(exports) == 1


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
    sites = [i for i, n in enumerate(region.body) if isinstance(n, ast.Assign)
             and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
             and n.targets[0].id == 'stopped_snapshot' and isinstance(n.value, ast.Constant)
             and n.value.value is False]
    assert len(sites) == 1
    region.body.pop(sites[0])
    namespace = dict(vars(m))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-unknown-writer-fence>', 'exec'), namespace)
    assert namespace['launch'](args) == 2
    with pytest.raises(AssertionError): assert exports == []


def test_unknown_reviewer_preserves_only_positively_stopped_financial_output(tmp_path, monkeypatch):
    args, calls, exports = launch_fixture(tmp_path, monkeypatch, 'unknown-review')
    assert m.launch(args) == 2 and calls == ['preflight', 'economic', 'review']
    assert len(exports) == 1 and not (exports[0] / 'stopped-review').exists()
    assert json.loads(args.output.read_bytes())['status'] == 'REVIEW_UNKNOWN_STOPPED_FINANCIAL_PRESERVED'


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
def test_actual_inspector_fences_and_entrypoint(tmp_path, monkeypatch, bad):
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setattr(m.os, 'getuid', lambda: 1000, raising=False)
    monkeypatch.setattr(m.os, 'getgid', lambda: 1000, raising=False)
    name = 'capital-system-resume-p03-worker-123-1'
    value = dict(Name='/' + name, Image=m.EXECUTION_IMAGE, Id='a' * 64,
        HostConfig=dict(NetworkMode='none', Memory=8*1024**3, MemorySwap=8*1024**3,
            NanoCpus=2000000000, PidsLimit=64, ReadonlyRootfs=True, CapDrop=['ALL'],
            SecurityOpt=['no-new-privileges']),
        Mounts=[dict(Type='bind', Destination=p, RW=p=='/out')
                for p in ['/variant', '/frozen', '/driver', '/old', '/out']],
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

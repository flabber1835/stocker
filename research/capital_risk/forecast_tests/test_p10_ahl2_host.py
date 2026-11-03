"""Pure/stub CFG, source fences, real synthetic marker and export tests."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import system_campaign_p10_ahl2_contract as contract
import system_campaign_p10_ahl2_job as job
import system_campaign_p10_ahl2_export as export
from system_campaign_p10_ahl2_gate import STATUS


def receipt():
    return dict(schema=export.RECEIPT_SCHEMA, authority=contract.TAINT, arm='P10', stage=export.STAGE,
        run_id='123', head='a'*40, request_sha256='b'*64, protocol_sha256='c'*64,
        financial_authority=False, account_performance_computed=False, production_contacted=False,
        status='SYNTHETIC_TEST_ONLY')


def summary(spec):
    return dict(schema='research.p10-ahl2-changed-qualification/1', status=STATUS,
        financial_authority=False, qualifier_state_adopted=False,
        original_diagnostic_file_sha256=spec['diagnostic_checkpoint_sha256'], candidate_transitions=10,
        qualified_through='2019-02-15', first_session='2019-02-04',
        full_FAST_REFERENCE_publication_runtime_event_proof_equal=True, actual_old_refusal_reproduced=True,
        all21_guard_preserved=True, successor_input_sha256='f'*64,
        actual_new_canonical_roundtrips=[dict(mode=m,session=d,checkpoint_sha256='c'*64,state_sha256='d'*64,full_state_equal=True)
            for m in ('FAST','REFERENCE') for d in ('2019-02-04','2019-02-05','2019-02-06','2019-02-07','2019-02-08',
                '2019-02-11','2019-02-12','2019-02-13','2019-02-14','2019-02-15')])


def qualifier_receipt():
    return dict(qualification_exported=True, qualification_encrypted_output={'synthetic':True},
        qualification_worker=dict(stopped=True, exit_code=0, oom_killed=False, wait_error=None))


def test_mechanical_nested_budgets_and_workflow_match():
    value = job.budget_contract()
    assert value['internal_envelope_seconds'] == 285*60
    assert value['orchestration_headroom_minutes'] == 15 and value['outer_headroom_minutes'] == 18
    text = (HERE.parents[1] / '.github/workflows' / job.WORKFLOW).read_text()
    timeouts = [int(line.partition(':')[2].strip()) for line in text.splitlines() if 'timeout-minutes:' in line]
    assert timeouts == [job.JOB_MINUTES, *job.STEP_MINUTES]
    assert text.index('ephemeral_runner_capacity.py') < text.index('/stage.py')
    assert 'retention-days: 7' in text and 'cancel-in-progress: false' in text
    assert 'worker.log' not in text and 'verified' not in text


def test_outer_headroom_loss_refuses(monkeypatch):
    monkeypatch.setattr(job, 'JOB_MINUTES', sum(job.STEP_MINUTES))
    with pytest.raises(ValueError, match='P10_MECHANICAL_NESTED_WAITS_STOP_EXPORT_AND_OUTER_HEADROOM'):
        job.budget_contract()


def test_exact_source_closure_retains_all427_and_excludes_iac():
    value = job.expected_request()
    old = json.loads((HERE / job.PRIOR).read_bytes())['sources']
    assert all(value['sources'][n] == h for n,h in old.items())
    assert set(job.MODULES) <= set(value['sources'])
    assert not any(n.startswith('p01_iac_unit') for n in value['sources'])
    assert value['request_serialization'] == 'COPY_EXACT_SOURCE_BYTES'
    assert value['candidate_document_raw_sha256'] != value['candidate_document_model_sha256']
    assert value['expected_successor_input_sha256'] != contract.specification()['input_sha256']


def test_explicit_root_copies_preserve_whole_raw_lf_request(tmp_path):
    request = tmp_path / 'request-source.json'
    request.write_bytes(b'{"unusual_order":2, "all_fields":1}\n')
    previous = tmp_path / 'previous'
    previous.mkdir()
    (previous / 'source-bindings.json').write_bytes(b'{"source":"synthetic-only"}\n')
    out = tmp_path / 'out'
    job.roots(out, request, previous)
    assert (out / 'request.json').read_bytes() == request.read_bytes()
    assert (out / 'spec.json').read_bytes() == (HERE / job.SPEC).read_bytes()
    assert (out / 'source-map.json').read_bytes() == (previous / 'source-bindings.json').read_bytes()


@pytest.mark.parametrize('role', ['qualify','worker','review'])
def test_worker_command_new_entrypoint_mounts_limits(monkeypatch, role):
    import os
    monkeypatch.setattr(os, 'getuid', lambda:1001, raising=False)
    monkeypatch.setattr(os, 'getgid', lambda:1001, raising=False)
    value = job.worker_command('SYNTHETIC', role, '/source', '/frozen', '/out', '/old', '/previous', evidence='/evidence')
    assert value[value.index('-B'):] == job.entrypoint(role)
    assert value[value.index('--cpus')+1] == '2'
    assert value[value.index('--memory')+1] == value[value.index('--memory-swap')+1] == '8g'
    assert value[value.index('--network')+1] == 'none'
    assert 'type=bind,source=/previous,target=/previous,readonly' in value
    assert ('type=bind,source=/evidence,target=/evidence,readonly' in value) == (role == 'review')


@pytest.mark.parametrize('field,bad', [('qualification_exported',False), ('stopped',False),('exit_code',1),
    ('exit_code',False),('oom_killed',True),('wait_error','TimeoutExpired'),('candidate_transitions',9),
    ('all21_guard_preserved',False),('successor_input_sha256','0'*64)])
def test_suffix_cannot_launch_without_exact_actual_q_export_and_proof(field, bad):
    spec = contract.specification()
    r, proof = qualifier_receipt(), summary(spec)
    if field == 'qualification_exported': r[field] = bad
    elif field in r['qualification_worker']: r['qualification_worker'][field] = bad
    else: proof[field] = bad
    with pytest.raises(ValueError):
        job.qualified_for_suffix(r, proof, spec, {'expected_successor_input_sha256':'f'*64})


def test_actual_host_gate_removal_falsifier():
    spec = contract.specification()
    proof = summary(spec)
    proof['candidate_transitions'] = 9
    r = qualifier_receipt()
    request = {'expected_successor_input_sha256':'f'*64}
    with pytest.raises(ValueError): job.qualified_for_suffix(r, proof, spec, request)
    fn = contract.function((HERE / 'system_campaign_p10_ahl2_job.py').read_bytes(), 'qualified_for_suffix')
    sites = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
             and ast.unparse(n.value.func) == 'qualification_valid']
    assert len(sites) == 1
    fn.body.remove(sites[0])
    scope = dict(vars(job))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-actual-gate>', 'exec'), scope)
    assert scope['qualified_for_suffix'](r, proof, spec, request) == proof


def test_actual_main_cfg_marker_and_q_cipher_precede_fetch_and_suffix():
    fn = contract.function((HERE / 'system_campaign_p10_ahl2_job.py').read_bytes(), 'main')
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    one = lambda name: next(n.lineno for n in calls if ast.unparse(n.func) == name)
    assert one('qualify_export') < one('admit_strict') < one('admit_own')
    qseal, = [n for n in calls if ast.unparse(n.func) == 'preserve' and
              any(k.arg == 'qualification' and ast.literal_eval(k.value) is True for k in n.keywords)]
    worker, = [n for n in calls if ast.unparse(n.func) == 'worker_command' and ast.literal_eval(n.args[1]) == 'worker']
    assert qseal.lineno < one('qualified_for_suffix') < worker.lineno
    text = ast.unparse(fn)
    assert 'unknown_preservation(active_role, known)' in text
    assert "known=known and dout is not None" in text


def test_unknown_never_calls_seal(tmp_path, monkeypatch):
    r = receipt()
    r['status'] = 'UNKNOWN_NO_MUTABLE_SNAPSHOT'
    calls = []
    monkeypatch.setattr(export, 'sealed', lambda *a,**kw:calls.append(a))
    export.preserve(r, None, tmp_path / 'receipt.json', b'x'*32, tmp_path / 'request.json', known=False)
    assert calls == [] and r['encrypted_output_exported'] is False
    with pytest.raises(ValueError, match='P10_UNKNOWN_WRITER_NO_SNAPSHOT'):
        export.preserve(r, None, tmp_path / 'receipt.json', b'x'*32, tmp_path / 'request.json', known=True)


def test_known_export_failure_preserves_static_receipt_no_payload(tmp_path, monkeypatch):
    def fail(*_,**__): raise RuntimeError('SECRET_PRICE_999')
    monkeypatch.setattr(export, 'sealed', fail)
    r = receipt()
    path = tmp_path / 'receipt.json'
    export.preserve(r, tmp_path, path, b'x'*32, tmp_path / 'request.json', known=True)
    assert r['status'] == 'KNOWN_STOP_EXPORT_FAILED_NO_PLAINTEXT_FALLBACK'
    assert r['export_error'] == dict(type='RuntimeError', code='EXPORT_OPERATION_FAILED')
    assert 'SECRET_PRICE_999' not in path.read_text()


def test_real_actual_new_scope_synthetic_marker_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_SHA', 'a'*40)
    request = tmp_path / 'synthetic-request.json'
    request.write_text(json.dumps({'protocol_sha256':'c'*64}) + '\n')
    result = export.qualify_export(tmp_path / 'marker', request)
    assert result['status'] == 'P10_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'
    assert result['synthetic_marker_only'] is True and result['market_or_financial_state_processed'] is False
    assert result['source_adapter_sha256'] == contract.sha((HERE / 'system_campaign_p10_ahl2_export.py').read_bytes())
    with tarfile.open(tmp_path / 'marker/probe.tar.gz', mode='r:gz') as tar:
        manifest = json.loads(tar.extractfile('manifest.json').read())
        assert manifest['arm'] == 'P10' and manifest['stage'] == export.STAGE
        assert set(manifest['members']) == {'marker.txt'}


def test_retained_q_never_copies_qualifier_book_or_old_lineage(tmp_path):
    source, target = tmp_path / 'q', tmp_path / 'retained'
    for name in ('qualification-summary.json','fast/actual-runtime-path/day.json.gz',
                 'fast/lineage/old.json','fast/book/repairs/old.json','fast/diagnostic-book/current.json.gz'):
        p = source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(name.encode())
    job.retain_qualification(source, target)
    assert {p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()} == {
        'qualification-summary.json','fast/actual-runtime-path/day.json.gz'}


def current_inspection(role):
    name = 'capital-system-p10-ahl2-' + role + '-123-1'
    destinations = ['/variant','/frozen','/driver','/out','/old','/previous'] + (['/evidence'] if role == 'review' else [])
    return dict(Name='/'+name, Id='f'*64,
        Image='sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d',
        State=dict(Running=True, OOMKilled=False, ExitCode=0),
        HostConfig=dict(NetworkMode='none', Memory=8*1024**3, MemorySwap=8*1024**3, NanoCpus=2000000000,
            ReadonlyRootfs=True, PidsLimit=64, CapDrop=['ALL'], SecurityOpt=['no-new-privileges']),
        Config=dict(WorkingDir='/variant', User='1001:1001', Env=[], Cmd=job.entrypoint(role),
            Labels={'research.study':'full-system-search-20261029','research.role':'review' if role=='review' else 'worker'}),
        Mounts=[dict(Type='bind',Destination=x,RW=x=='/out') for x in destinations])


@pytest.mark.parametrize('role', ['qualify','worker','review'])
def test_actual_current_inspector_accepts_running_fences_and_new_cli(monkeypatch, role):
    import system_campaign_p02_continue_job as original
    monkeypatch.setattr(original.os, 'getuid', lambda:1001, raising=False)
    monkeypatch.setattr(original.os, 'getgid', lambda:1001, raising=False)
    value = current_inspection(role)
    monkeypatch.setattr(original.subprocess, 'run', lambda *a,**kw:SimpleNamespace(stdout=json.dumps([value]).encode()))
    assert job.inspect(value['Name'][1:], 'f'*64) == value
    value['Config']['Cmd'][2] = '/driver/system_campaign_volatility_native_run.py'
    with pytest.raises(ValueError, match='P10_CURRENT_EXACT_ENTRYPOINT_NO_OLD_NAMESPACE_FALLBACK'):
        job.inspect(value['Name'][1:], 'f'*64)


@pytest.mark.parametrize('field', ['swap','mount','credential'])
def test_current_inspector_refuses_actual_fence_changes(monkeypatch, field):
    import system_campaign_p02_continue_job as original
    monkeypatch.setattr(original.os, 'getuid', lambda:1001, raising=False)
    monkeypatch.setattr(original.os, 'getgid', lambda:1001, raising=False)
    value = current_inspection('worker')
    if field == 'swap': value['HostConfig']['MemorySwap'] *= 2
    elif field == 'mount': value['Mounts'][0]['RW'] = True
    else: value['Config']['Env'] = ['GH_TOKEN=bad']
    monkeypatch.setattr(original.subprocess, 'run', lambda *a,**kw:SimpleNamespace(stdout=json.dumps([value]).encode()))
    with pytest.raises(ValueError): job.inspect(value['Name'][1:], 'f'*64)


@pytest.mark.parametrize('field', ['root','duplicate_bind'])
def test_explicit_root_and_duplicate_bind_falsifiers(monkeypatch, field):
    import system_campaign_p02_continue_job as original
    uid = 0 if field == 'root' else 1001
    monkeypatch.setattr(original.os, 'getuid', lambda:uid, raising=False)
    monkeypatch.setattr(original.os, 'getgid', lambda:uid, raising=False)
    value = current_inspection('worker')
    if field == 'root': value['Config']['User'] = '0:0'
    else: value['Mounts'].append(deepcopy(value['Mounts'][0]))
    monkeypatch.setattr(original.subprocess, 'run', lambda *a,**kw:SimpleNamespace(stdout=json.dumps([value]).encode()))
    with pytest.raises(ValueError, match='P10_EXPLICIT_POSITIVE_NONROOT_UID_AND_GID|P10_EXACT_UNIQUE_BIND_DESTINATIONS'):
        job.inspect(value['Name'][1:], 'f'*64)


def test_matching_client_actual_stopped_record_not_public_boolean():
    value = current_inspection('worker')
    metadata = dict(stopped=True, exit_code=0, oom_killed=False, wait_error=None)
    with pytest.raises(ValueError, match='P10_ACTUAL_INSPECTION_REQUIRED_NOT_RECEIPT_STOP_BOOLEAN'):
        job.stopped_record(value, metadata, 'worker', '123')
    value['State']['Running'] = False
    job.stopped_record(value, metadata, 'worker', '123')
    for change in ('root','duplicate','bool_exit'):
        bad, m = deepcopy(value), deepcopy(metadata)
        if change == 'root': bad['Config']['User'] = '0:0'
        elif change == 'duplicate': bad['Mounts'].append(deepcopy(bad['Mounts'][0]))
        else: m['exit_code'] = False
        with pytest.raises(ValueError): job.stopped_record(bad,m,'worker','123')


@pytest.mark.parametrize('role,worker_known,expected', [('review',True,True),('review',False,False),
    ('worker',True,False),('worker',False,False),('qualify',False,False)])
def test_role_specific_unknown_preservation(role, worker_known, expected):
    value = job.unknown_preservation(role, worker_known)
    assert value['known'] is expected
    assert (value['status'] == 'REVIEW_UNKNOWN_STOPPED_WORKER_PRESERVED') is expected


def test_unknown_reviewer_preserves_stopped_worker_not_mutable_scratch(tmp_path, monkeypatch):
    dout, rout = tmp_path/'stopped-worker', tmp_path/'unknown-reviewer'
    dout.mkdir();rout.mkdir()
    (dout/'actual-stopped-evidence.json').write_text('{}')
    (rout/'MUTABLE-REVIEW-SCRATCH').write_text('never snapshot')
    r = receipt()
    decision = job.unknown_preservation('review',True)
    r.update(status=decision['status'],review_stop_unknown=decision['review_stop_unknown'])
    calls = []
    def seal(root,*_,**__):
        calls.append({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()})
        return dict(name='synthetic.crseal',bytes=1,sha256='a'*64,manifest_sha256='b'*64,compression='TAR_GZIP_V1')
    monkeypatch.setattr(export,'sealed',seal)
    export.preserve(r,dout,tmp_path/'receipt.json',b'x'*32,tmp_path/'request.json',known=decision['known'])
    assert calls == [{'actual-stopped-evidence.json'}]
    assert r['encrypted_output_exported'] is True and r['review_stop_unknown'] is True
    assert (rout/'MUTABLE-REVIEW-SCRATCH').exists()


def test_unknown_actual_worker_never_snapshots_its_mutable_output(tmp_path, monkeypatch):
    root=tmp_path/'mutable-worker';root.mkdir();(root/'MUTABLE').write_text('not snapshot')
    r=receipt();decision=job.unknown_preservation('worker',False);r['status']=decision['status']
    calls=[];monkeypatch.setattr(export,'sealed',lambda *a,**kw:calls.append(a))
    export.preserve(r,root,tmp_path/'receipt.json',b'x'*32,tmp_path/'request.json',known=decision['known'])
    assert not calls and r['encrypted_output_exported'] is False


def test_unknown_writer_role_guard_removal_falsifier():
    assert job.unknown_preservation('worker',True)['known'] is False
    fn=contract.function((HERE/'system_campaign_p10_ahl2_job.py').read_bytes(),'unknown_preservation')
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Compare(self,node):
            if ast.unparse(node)=="role == 'review'" and self.count==0:
                self.count+=1
                return ast.copy_location(ast.Constant(True),node)
            return self.generic_visit(node)
    remove=Remove();fn=remove.visit(fn);assert remove.count==1
    ns=dict(vars(job));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-unknown-role-guard>','exec'),ns)
    assert ns['unknown_preservation']('worker',True)['known'] is True


def descriptor():
    return dict(name='p10-ahl2-discovery.tar.crseal',bytes=37,sha256='a'*64,manifest_sha256='b'*64,compression='TAR_GZIP_V1')


@pytest.mark.parametrize('field,bad', [('name',{}),('name','../private'),('name','C:private'),('name','x\\private'),
    ('bytes',True),('bytes',0),('bytes',-1),('bytes',{}),('sha256',[]),('sha256','A'*64),
    ('manifest_sha256',{}),('compression',{}),('compression','NOT_DECLARED')])
def test_public_asset_values_are_closed_scalars(field,bad):
    value=descriptor();value[field]=bad
    with pytest.raises(ValueError,match='P10_PUBLIC_ASSET_EXACT_BASENAME_POSITIVE_BYTE_INT_SHA_AND_COMPRESSION'):
        export.asset_valid(value)


@pytest.mark.parametrize('value', [{'type':{},'code':'EXPORT_OPERATION_FAILED'},
    {'type':'RuntimeError','code':{}},{'type':'RuntimeError','code':'PRIVATE_VALUE_999'},
    {'type':'Runtime Error','code':'EXPORT_OPERATION_FAILED'}])
def test_export_error_only_class_and_static_code(value):
    with pytest.raises(ValueError):export.export_error_valid(value)


def test_public_asset_nonbool_byte_predicate_removal_falsifier():
    value=descriptor();value['bytes']=True
    with pytest.raises(ValueError):export.asset_valid(value)
    fn=contract.function((HERE/'system_campaign_p10_ahl2_export.py').read_bytes(),'asset_valid')
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Compare(self,node):
            if ast.unparse(node)=="type(value['bytes']) is int":
                self.count+=1
                return ast.copy_location(ast.Constant(True),node)
            return self.generic_visit(node)
    remove=Remove();fn=remove.visit(fn);assert remove.count==1
    ns=dict(vars(export));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-nonbool-asset-byte-guard>','exec'),ns)
    assert ns['asset_valid'](value)==value

"""Actual read-only source DATA; no destination tree or checkpoint is staged."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
from forecast_tests.p06_BBIG11 import test_P06_BBIG11 as base
import system_campaign_p06_BBIG_retained_resources as resources
import system_campaign_p06_BBIG_runtime as runtime

D=Path(__file__).parent;R=base.R
def read(p):return Path(p).read_bytes() if str(p).startswith('\\\\?\\') else base.read(p)
@pytest.fixture(scope='module')
def source():
    capture=R/'financial330-source-snapshot/capture-P06-13482378564-001';root=base.ext(capture/'verified-output')
    mf=json.loads(read(capture/'authenticated-manifest.json'))['members'];plan=resources.plan()
    def member(n):
        raw=read(root/n);assert dict(bytes=len(raw),sha256=base.data.sha(raw))==mf[n];return raw
    fin=R/'financial337-source-snapshot/capture-P06-13520309373-001'
    failure=json.loads(read(D/'P06-FIN337-zero-session-provenance-failure-DATA.json'))
    cpraw=read(fin/'verified-output/book/checkpoint.json.gz')
    finmf=json.loads(read(fin/'authenticated-manifest.json'))['members'];assert dict(bytes=len(cpraw),sha256=base.data.sha(cpraw))==finmf['book/checkpoint.json.gz']
    cp=json.loads(gzip.decompress(cpraw));assert cp['sha256']==failure['financial_checkpoint_outer_sha256']
    rows=[json.loads(v) for v in member('uncertainty-certificate.jsonl').splitlines() if json.loads(v)['session']<=cp['source_cursor']]
    cache={n:member(n) for n in plan['whole_preserve_source_pins']}
    return root,cp,rows,cache,plan,finmf
def callbacks(source):
    """Source-backed byte callbacks only; no fake book or filesystem aliases."""
    root,cp,rows,cache,plan,finmf=source;prefix=runtime.PROVENANCE
    proof=dict(passed=True,parent_outer_sha256=base.data.OUTER,whole_old_proof_sha256=plan['raw147_proof_pin']['sha256'],
        whole_old_proof_rows=147,active_committed_seed_rows=130,active_committed_seed_sha256=plan['committed130_prefix_pin']['sha256'],
        unadmitted_tail_rows_used=0,prior_transition_reexecuted=False)
    receipts={prefix+'/prefix-preservation.json':base.data.encoded(proof),
        prefix+'/actual-prior-metadata-preservation.json':base.data.encoded(resources.preservation_receipt({n:cache[n] for n in plan['resources']}))}
    def destination(n):return receipts[n] if n in receipts else cache[plan['whole_preserve_destination_to_actual_source'][n]]
    return cache.__getitem__,destination,rows,plan['prior_ABMD_resolution']
def test_actual_failure_unchanged_full10_no_overlay_no_neutral(source):
    root,cp,rows,cache,plan,finmf=source
    assert (cp['completed'],cp['source_cursor'],len(cp['repairs']))==(1383,'2023-06-30',10)
    assert not any(n.startswith('p06-BBIG-ordinary11-adoption/') or n=='p06-BBIG-source-only-ordinary11-overlay.json' for n in finmf)
    assert len(rows)==130 and len(plan['whole_preserve_source_pins'])==48 and len(plan['whole_preserve_destination_to_actual_source'])==57
def test_all_actual_preserve_source_locations_not_just_missing_log(source):
    root,cp,rows,cache,plan,finmf=source;inventory=resources.inventory(root,cp)
    assert len(inventory)==13
    assert len(inventory['uncertainty-capture.json'])==280
    assert len(inventory['p06-point-retained-origin/uncertainty-capture.json'])==279
    assert inventory['uncertainty-capture.json']!=inventory['p06-point-retained-origin/uncertainty-capture.json']
    assert resources.provenance_member(root,'actual-future-event-2022-12-16.json')==cache['p06-point-retained-origin/actual-future-event-2022-12-16.json']
    assert not (root/'actual-future-event-2022-12-16.json').exists()
def test_actual_resolution_full10_old_producer_exact(source):
    root,cp,rows,cache,plan,finmf=source;r=plan['prior_ABMD_resolution'];archive=json.loads(gzip.decompress(cache[r['actual']]))
    assert r['actual']=='book/pre-event/2022-12-22-'+archive['sha256']+'.json.gz'
    assert archive['run']['input_sha256']==r['input_sha256']==cp['run']['input_sha256']==rows[0]['input_sha256']
    assert len(archive['repairs'])==10 and archive['repairs']==cp['repairs']
    assert archive['run']['state_sha256']==r['state_sha256']==rows[0]['prior_state_sha256']
def test_whole_original_preserve_read_lift_and_label_undo():
    raw=Path(runtime.retained.__file__).read_bytes();tree=runtime.retained_tree(raw,'preserve')
    site=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and ast.unparse(n)=='provenance_member(root, name)')
    replacement=ast.parse('(root/name).read_bytes()',mode='eval').body;site.func,site.args,site.keywords=replacement.func,replacement.args,replacement.keywords
    for n in ast.walk(tree):
        if isinstance(n,ast.Constant) and type(n.value)is int and n.value==147:n.value=18
    assert base.dump(tree)==base.dump(base.function(raw,'preserve'))
def test_complete_inventory_precedes_any_preservation_write():
    tree=base.function(Path(runtime.__file__).read_bytes(),'preserve')
    assert ast.unparse(tree.body[0])=='inventory = resources.inventory(root, parent)'
    assert all('exact(' not in ast.unparse(n) for n in tree.body[:1])
    assert 'resources.verify_preserved' in ast.unparse(base.function(Path(runtime.__file__).read_bytes(),'bind_retained'))
def test_readonly_complete_destination_relation_contract(source):
    a,b,rows,resolution=callbacks(source)
    assert resources.verify_preserved(a,b,rows,resolution,provenance=runtime.PROVENANCE)
@pytest.mark.parametrize('name',[
    'p06-point-retained-origin/actual-future-event-2022-12-16.json',
    'p06-point-retained-origin/uncertainty-capture.json','uncertainty-capture.json',
    'p06-retained-ordinary-observation/actual-future-event-2023-03-10.json'])
def test_changed_metadata_member_refuses(source,monkeypatch,name):
    root,cp,rows,cache,plan,finmf=source;original=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda p:cache[name]+b'ALTERED' if p==root/name else original(p))
    with pytest.raises(ValueError,match='EXACT_ACTUAL_METADATA_MEMBER_BYTES'):resources.checked_member(root,name)
@pytest.mark.parametrize('name',[
    'p06-point-retained-origin/actual-future-event-2022-12-16.json',
    'uncertainty-capture.json','p06-abmd-initial-synthetic-gateway.json'])
def test_missing_provenance_member_refuses_without_fallback(source,monkeypatch,name):
    root,cp,rows,cache,plan,finmf=source;original=Path.read_bytes
    def missing(p):
        if p==root/name:raise FileNotFoundError('EXPLICIT_MISSING_ACTUAL_MEMBER')
        return original(p)
    monkeypatch.setattr(Path,'read_bytes',missing)
    logical=next(k for k,v in plan['old_preserve_read_map'].items() if v==name)
    with pytest.raises(FileNotFoundError,match='EXPLICIT_MISSING'):resources.provenance_member(root,logical)
@pytest.mark.parametrize('field',['actual','gzip_sha256','state_sha256','input_sha256'])
def test_changed_already_preserved_resolution_refuses(source,field):
    a,b,rows,resolution=callbacks(source);bad=deepcopy(resolution);bad[field]='WRONG'
    with pytest.raises(ValueError,match='GENUINE130_AND_ACTUAL_FULL10'):resources.verify_preserved(a,b,rows,bad,provenance=runtime.PROVENANCE)
@pytest.mark.parametrize('destination',[
    runtime.PROVENANCE+'/actual-future-event-2022-12-16.json',runtime.PROVENANCE+'/uncertainty-capture.json',
    'abmd-initial-origin/typed-neutral-checkpoint.json.gz',
    'book/pre-event/2022-12-22-822efb532f74793c44319f45cbe40f0956d98eaa43401eb78e6b8c35c4c8187a.json.gz'])
def test_changed_preserved_destination_bytes_refuse(source,destination):
    a,b,rows,resolution=callbacks(source)
    with pytest.raises(ValueError,match='ALL57_PRESERVED_DESTINATIONS'):resources.verify_preserved(a,lambda n:b(n)+b'ALTERED' if n==destination else b(n),rows,resolution,provenance=runtime.PROVENANCE)
def test_meaningful_member_byte_guard_removal(source,monkeypatch):
    root,cp,rows,cache,plan,finmf=source;name='uncertainty-capture.json';original=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda p:cache[name]+b'ALTERED' if p==root/name else original(p))
    with pytest.raises(ValueError):resources.checked_member(root,name)
    # Exact label is dynamic; substitute only that call's whole guard in the original AST.
    tree=base.function(Path(resources.__file__).read_bytes(),'checked_member')
    stmt=next(n for n in tree.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and 'P06_BBIG_EXACT_ACTUAL_METADATA_MEMBER_BYTES:' in ast.unparse(n))
    tree.body[tree.body.index(stmt)]=ast.Pass();scope=dict(vars(resources))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[tree],type_ignores=[])),'<removed-member-byte-guard>','exec'),scope)
    assert scope['checked_member'](root,name)==cache[name]+b'ALTERED'
def test_meaningful_resolution_guard_removal(source):
    a,b,rows,resolution=callbacks(source);resolution=deepcopy(resolution);resolution['actual']='WRONG'
    with pytest.raises(ValueError):resources.verify_preserved(a,b,rows,resolution,provenance=runtime.PROVENANCE)
    mutant=base.removed(base.function(Path(resources.__file__).read_bytes(),'verify_preserved'),
        'P06_BBIG_ALREADY_PRESERVED_GENUINE130_AND_ACTUAL_FULL10_ABMD_RESOLUTION',vars(resources))
    assert mutant(a,b,rows,resolution,provenance=runtime.PROVENANCE)
def test_meaningful_complete_destination_guard_removal(source):
    a,b,rows,resolution=callbacks(source);target=runtime.PROVENANCE+'/uncertainty-capture.json'
    changed=lambda n:b(n)+b'ALTERED' if n==target else b(n)
    with pytest.raises(ValueError):resources.verify_preserved(a,changed,rows,resolution,provenance=runtime.PROVENANCE)
    tree=base.function(Path(resources.__file__).read_bytes(),'verify_preserved')
    stmt=next(n for n in ast.walk(tree) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and 'P06_BBIG_ALL57_PRESERVED_DESTINATIONS_EQUAL48_ACTUAL_PINNED_SOURCES:' in ast.unparse(n))
    for node in ast.walk(tree):
        for field,value in ast.iter_fields(node):
            if isinstance(value,list) and stmt in value:value[value.index(stmt)]=ast.Pass()
    scope=dict(vars(resources));exec(compile(ast.fix_missing_locations(ast.Module(body=[tree],type_ignores=[])),'<removed-whole-destination-byte-guard>','exec'),scope)
    assert scope['verify_preserved'](a,changed,rows,resolution,provenance=runtime.PROVENANCE)
def test_meaningful_ambiguous_root_alias_guard_removal(source,monkeypatch):
    root,cp,rows,cache,plan,finmf=source;original=Path.exists
    monkeypatch.setattr(Path,'exists',lambda p:True if p==root/'actual-future-event-2022-12-16.json' else original(p))
    with pytest.raises(ValueError,match='WITHOUT_AMBIGUOUS_ROOT_ALIAS'):resources.inventory(root,cp)
    mutant=base.removed(base.function(Path(resources.__file__).read_bytes(),'inventory'),
        'P06_BBIG_FULL_ACTUAL_METADATA_AXIS_WITHOUT_AMBIGUOUS_ROOT_ALIAS',vars(resources))
    assert len(mutant(root,cp))==13

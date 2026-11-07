"""Closed actual805 metadata and whole mature source undo; no canonical replay."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
from forecast_tests.p07_vivo25.test_VIVO25_data_models_api import actual,read,Fence,C,P
import system_campaign_p07_vivo_data as data
import system_campaign_p07_vivo_models as models
import system_campaign_p07_vivo_retained as retained
import system_campaign_p07_vivo_runtime as runtime
import system_campaign_p07_vivo_boundary as boundary

def functions(raw):return {n.name:n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)}

def test_whole_original_u805_seed_AST_undo():
    raw=Path(retained.uncertainty.__file__).read_bytes();old=functions(raw)['retained_seed'];new=retained.seed_tree(raw)
    imp,=[n for n in new.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_branches']
    imp.names.insert(0,ast.alias(name='validate_input'))
    assert ast.dump(new)==ast.dump(old)

def test_whole_original_neutral_adoption_AST_undo():
    raw=Path(runtime.uncertainty.__file__).read_bytes();old=functions(raw)['paused_own_adoption'];new=runtime.adoption_tree(raw)
    mapping,=[n.value for n in new.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
    assert mapping.keys[-1].value==boundary.DIRECTORY and mapping.values[-1].value==boundary.OVERLAY
    mapping.keys.pop();mapping.values.pop();assert ast.dump(new)==ast.dump(old)

def test_whole_legacy_full25_past_event_AST_undo():
    raw=Path(retained.legacy_original.__file__).read_bytes();old=functions(raw)
    for fn in retained.legacy_tree(raw).body:
        if fn.name=='suffix':models.replace_count(fn,'(23, 24, 25)','(23, 24)',1,'TEST_SUFFIX_UNDO')
        elif fn.name=='future_tree':
            n,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=="len(cp['repairs']) in (24,25) and entry==cp['repairs'][23]"]
            n.value="len(cp['repairs'])==24 and entry==cp['repairs'][23]"
        elif fn.name=='added_permissions':models.replace_count(fn,"actual_event_descriptors(where, current['repairs'])","current['repairs']",1,'TEST_EVENT_AXIS_UNDO')
        assert ast.dump(fn)==ast.dump(old[fn.name]),fn.name

def test_whole_lifecycle_past_event_preservation_AST_undo():
    raw=Path(retained.lifecycle_original.__file__).read_bytes();old=functions(raw)
    for fn in retained.lifecycle_tree(raw).body:
        if fn.name=='runtime_api':
            orig,=[n for n in old[fn.name].body if isinstance(n,ast.FunctionDef) and n.name=='preserve']
            new,=[n for n in fn.body if isinstance(n,ast.FunctionDef) and n.name=='preserve']
            ob,=[n for n in orig.body if isinstance(n,ast.If)];nb,=[n for n in new.body if isinstance(n,ast.If)]
            imp,=[n for n in ob.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_bounded_sensor_event_review']
            nb.body.insert(ob.body.index(imp),deepcopy(imp))
        assert ast.dump(fn)==ast.dump(old[fn.name]),fn.name

def test_whole_original_growth_context_AST_undo():
    raw=Path(retained.additional_runtime.__file__).read_bytes();old=functions(raw)['growth_scope'];new=retained.growth_tree(raw)
    imp,=[n for n in old.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_uncertainty']
    new.body.insert(old.body.index(imp),deepcopy(imp));assert ast.dump(new)==ast.dump(old)

def test_factory_all_original_postevent_function_AST_and_one_frozen_guard_undo():
    source=retained.certificate.source();old=functions(source);namespace=retained.certificate.factory_namespace()
    for name in old:
        fn=getattr(namespace,name)
        if name=='qualify_metadata':continue
        assert fn.__code__.co_filename=='<whole-admitted-postevent-ABMD-factory-functions>'
    raw=Path(retained.certificate.frozen.__file__).read_bytes();fn=namespace.factory_tree(raw)
    original=functions(raw)['extend_joint']
    guard,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(v,ast.Constant) and v.value=='P07_ABMD_ORIGINAL_COMMITTED_SEED_REQUIRED' for v in n.args)]
    assert ast.unparse(guard.args[0])=='qualified_retained_seed(self.seed, event, source, codec)'
    guard.args[0]=ast.parse("self.seed and self.seed[-1]['session']<NATIVE",mode='eval').body
    assert ast.dump(fn)==ast.dump(original)

def test_meaningful_past_event_exact24_axis_guard_removal(actual,monkeypatch):
    old,cp,spec=actual;metadata=deepcopy(cp['repairs']);metadata[0]['sha256']='0'*64
    with pytest.raises(ValueError,match='VIVO_PAST_EVENT_EXACT_ACTUAL_ADMITTED24'):retained.actual_event_descriptors(old,metadata)
    need=data.need
    def without(value,label):
        if label!='VIVO_PAST_EVENT_EXACT_ACTUAL_ADMITTED24_DESCRIPTOR_LIST':need(value,label)
    monkeypatch.setattr(data,'need',without)
    assert retained.actual_event_descriptors(old,metadata)==metadata

def test_actual805_factory_metadata_and_meaningful_prefix_guard_removal(actual,monkeypatch):
    old,cp,spec=actual;old=Path('\\\\?\\'+str(old.resolve()))
    life=retained.lifecycle_original;catalog=life.catalog()
    rows=[json.loads(v) for v in read(old/'uncertainty-certificate.jsonl').splitlines()][:805]
    from system_campaign_bounded_sensor_event_review import permissions
    allowed,resolutions=permissions(old,rows,catalog,through=cp['source_cursor'],input_descriptors=cp['repairs'])
    origin=json.loads(read(old/life.origin.ORIGIN));archive=read(old/resolutions[0]['actual'])
    source=retained.certificate.source();scope=dict(vars(retained.certificate.factory_namespace()))
    fn,=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='qualify_metadata']
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-metadata-test>','exec'),scope)
    original=scope['qualify_metadata']
    args=(cp,spec,catalog,origin,rows,rows,resolutions,allowed,archive)
    result=retained.certificate.exact_metadata(original,*args,source_plan=life.models.plan())
    assert result['committed_proof_rows']==805
    bad=deepcopy(rows);bad[790]['exhaustive_leaves']=-1
    args=(cp,spec,catalog,origin,bad,bad,resolutions,allowed,archive)
    with pytest.raises(ValueError,match='VIVO_FINITE_ACTUAL805'):retained.certificate.exact_metadata(original,*args,source_plan=life.models.plan())
    need=data.need
    def without(value,label):
        if label!='VIVO_FINITE_ACTUAL805_SEED_AND_REAL_ABMD_ORIGIN_NO_RAW_JANUARY_TAILS':need(value,label)
    monkeypatch.setattr(data,'need',without)
    assert retained.certificate.exact_metadata(original,*args,source_plan=life.models.plan())['passed']

def test_meaningful_full_current_commitment_guard_removal(actual,monkeypatch):
    _,cp,_=actual;bad=deepcopy(cp);bad['run']['state_sha256']='0'*64
    h=lambda b,r:data.digest(dict(base=b,repairs=r))
    with pytest.raises(ValueError,match='VIVO_FULL_CURRENT25_CANONICAL'):boundary.strict_current(bad,h)
    need=data.need
    def without(value,label):
        if label!='VIVO_FULL_CURRENT25_CANONICAL_INPUT_INNER_STATE_OUTER_COMMITMENTS':need(value,label)
    monkeypatch.setattr(data,'need',without);assert boundary.strict_current(bad,h) is None

def test_owned_view_permissions_complete_targets_before_chmod(tmp_path,monkeypatch):
    owner=tmp_path/'p07-vivo-owned-seed-view-metadata';view=owner/'view';(view/'book').mkdir(parents=True)
    (view/'book/watch.jsonl').write_bytes(b'noncanonical-mode-test-only\n');immutable=view/'source-metadata.txt';immutable.write_text('metadata')
    calls=[];monkeypatch.setattr(Path,'chmod',lambda p,mode:calls.append((p,mode)))
    result=runtime.owned_view_permissions(view,owner,tmp_path)
    assert result['original_source_permissions_changed'] is False
    assert {p for p,_ in calls}=={view,view/'book',view/'book/watch.jsonl'} and immutable not in {p for p,_ in calls}

def test_meaningful_owned_permission_root_guard_removal(tmp_path,monkeypatch):
    owner=tmp_path/'wrong-owned-prefix';view=owner/'view';(view/'book').mkdir(parents=True)
    (view/'book/watch.jsonl').write_bytes(b'noncanonical-mode-test-only\n');calls=[]
    monkeypatch.setattr(Path,'chmod',lambda p,mode:calls.append(p))
    with pytest.raises(ValueError,match='VIVO_PERMISSION_TARGET_ONLY'):runtime.owned_view_permissions(view,owner,tmp_path)
    assert calls==[]
    need=data.need
    def without(value,label):
        if label!='VIVO_PERMISSION_TARGET_ONLY_EXPLICIT_OWNED_OUTPUT_VIEW':need(value,label)
    monkeypatch.setattr(data,'need',without)
    assert runtime.owned_view_permissions(view,owner,tmp_path)['only_owner_write_search_added'] and calls

def test_whole_original_same_day_cash_review_AST_undo():
    raw=(ordinary_path:=Path(runtime.ordinary.__file__).parent/'system_campaign_ordinary_augmentation_cash_v1.py').read_bytes()
    old=runtime.ordinary.cash_tree(raw);new=runtime.cash_tree(raw)
    models.replace_count(new,"record['order'] == ['CASH:' + t['security_id'] for t in same_day_terms(term)]","record['order'] == ['CASH:' + sid]",1,'TEST_ORDER_UNDO')
    models.replace_count(new,"len(record['cash']) == len(same_day_terms(term))","len(record['cash']) == 1",1,'TEST_ARRAY_UNDO')
    c,=[n for n in new.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='(c,)']
    new.body[new.body.index(c)]=deepcopy(next(n for n in old.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='c'))
    assert ast.dump(new)==ast.dump(old)

def cash_metadata():
    from decimal import Decimal
    terms=sorted([t for t in data.catalog()['terms'] if t['added']['session']=='2023-02-22'],key=lambda t:(t['security_id'],t['added']['kind']))
    assert [t['ticker'] for t in terms]==['LHCG','ONEM']
    record=dict(passed=True,financial_source_changed=False,session='2023-02-22',source=[],stock=[],risk=[],engine_calls=0,
        order=['CASH:'+t['security_id'] for t in terms],cash=[dict(actual_context_call=True,source_only_noop=False,
            security_id=t['security_id'],session='2023-02-22',postcondition=dict(actual_held=False,quantity=0,nominal_cash=0.)) for t in terms])
    raw=(Path(runtime.ordinary.__file__).parent/'system_campaign_ordinary_augmentation_cash_v1.py').read_bytes()
    scope=dict(D=Decimal,need=lambda value,label:data.need(value,label),same_day_terms=lambda term:terms)
    exec(compile(ast.Module(body=[runtime.cash_tree(raw)],type_ignores=[]),'<whole-cash-review-noncanonical-metadata-falsifier>','exec'),scope)
    return terms,record,scope['verify_event']

def test_two_same_day_terms_use_complete_actual_record_without_projection():
    terms,record,verify=cash_metadata();before=deepcopy(record)
    for term in terms:
        proof=verify(record,term,dict(wealth_core=dict(episodes={})),dict(wealth_core=dict(episodes={}),pending=[]),[])
        assert proof['quantity']==0 and proof['session']=='2023-02-22'
    assert record==before

def test_meaningful_same_day_complete_order_guard_removal(monkeypatch):
    terms,record,verify=cash_metadata();record['order'].pop()
    args=(record,terms[0],dict(wealth_core=dict(episodes={})),dict(wealth_core=dict(episodes={}),pending=[]),[])
    with pytest.raises(ValueError,match='ACTUAL_ORDINARY_CASH_CONTEXT'):verify(*args)
    old=data.need
    def without(value,label):
        if label!='ACTUAL_ORDINARY_CASH_CONTEXT':old(value,label)
    monkeypatch.setattr(data,'need',without);assert verify(*args)['quantity']==0

def test_permission_inventory_symlink_refused_before_any_chmod(tmp_path,monkeypatch):
    owner=tmp_path/'p07-vivo-owned-seed-view-metadata';view=owner/'view';(view/'book').mkdir(parents=True)
    watch=view/'book/watch.jsonl';watch.write_bytes(b'noncanonical-mode-only\n');bad=view/'bad-metadata.txt';bad.write_bytes(b'not-a-real-link')
    actual=Path.is_symlink;calls=[]
    monkeypatch.setattr(Path,'is_symlink',lambda p:True if p==bad else actual(p))
    monkeypatch.setattr(Path,'chmod',lambda p,mode:calls.append(p))
    with pytest.raises(ValueError,match='ALL_PERMISSION_TARGETS_WITHIN_OWNED_VIEW_NO_SYMLINKS'):runtime.owned_view_permissions(view,owner,tmp_path)
    assert calls==[]

@pytest.mark.parametrize('method',['run','review','api'])
def test_no_local_canonical_entry(method):
    with pytest.raises(ValueError,match='HOSTED'):
        if method=='run':runtime.run(None,None,None,None,None,None,None,None)
        elif method=='review':runtime.review(None,None,None,None,None)
        else:runtime.api(None,None,None)

def test_inert_when_runtime_profile_qualification_missing(tmp_path,monkeypatch):
    monkeypatch.setattr(runtime,'HERE',tmp_path)
    with pytest.raises(FileNotFoundError):runtime.qualification()

def test_meaningful_profile_qualification_cannot_omit_runtime_sources(tmp_path,monkeypatch):
    value=dict(schema='research.P07-VIVO25-private-runtime-qualification/1',passed=True,root_admission_sha256=data.ROOT,
        source335_qualification_sha256=data.QUALIFICATION_SHA,local_canonical_runtime_executed=False,financial_authority=False,input_adopted=False,
        hosted_genuine_neutral_adoption_and_packet_qualification_required=True,tests=dict(passed=100,whole_source_undo=True,meaningful_guard_removals=10),files={})
    (tmp_path/runtime.QUALIFICATION).write_bytes(data.encoded(value));monkeypatch.setattr(runtime,'HERE',tmp_path)
    with pytest.raises(ValueError,match='CLOSED_PRIVATE_PROFILE_QUALIFICATION_REQUIRED'):runtime.qualification()
    old=data.need
    def without(value,label):
        if label!='VIVO_CLOSED_PRIVATE_PROFILE_QUALIFICATION_REQUIRED_BEFORE_REQUEST_OR_ACTIVATION':old(value,label)
    monkeypatch.setattr(data,'need',without)
    assert runtime.qualification()[1]==value

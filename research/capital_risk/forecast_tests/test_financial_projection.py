"""Own future projection data, source guards and synthetic codec lifecycle."""
import ast
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_projection as p
import system_campaign_future_amendment as original
import system_campaign_financial_partial as authority


def encoded(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def test_binding_selects_admitted817_and_keeps_original_global_scope_intact():
    saved={k:getattr(original,k)for k in p.binding().bindings}
    b=p.binding();parent=p.source_parent();logic=p.source_logic()
    assert parent['sha256']==b.bindings['OUTER']=='996fe19c4b3271aeb3f1af2d5e07e21cf879935fb8ba71701cc130ecc0dad2c9'
    assert logic['TARGET']=='634889bf285c8ece2333bb424dc2d5922eeecad940dcfc83b051f7181ce5e777'
    assert logic['CORRECT']=='8a43d7eba9a69a56941f74b5e10c48b27721a9a9239f5164ddbda50619ed4266'
    assert {k:getattr(original,k)for k in saved}==saved and original.OUTER!=logic['OUTER']
    tree=ast.parse(Path(original.__file__).read_bytes())
    for name in ('documents','validate_conflict','projection','effective_documents'):
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name==name)
        assert ast.dump(node,include_attributes=False)==ast.dump(ast.parse(__import__('inspect').getsource(getattr(original,name))).body[0],include_attributes=False)
        assert logic[name].__globals__ is logic and logic[name]is not getattr(original,name)


def fixture(tmp_path,monkeypatch):
    b=p.binding();logic=p.source_logic();root=tmp_path/'case';(root/'book/repairs').mkdir(parents=True)
    sid=b.bindings['SID'];suppression=dict(session='2021-04-30',security_id=sid,term_sha256='a'*64)
    good=dict(session='2021-05-03',security_id=sid,kind='CONVERSION',reference='earlier qualified',
              cash_per_share=None,exchange_ratio=.8381,cash_in_lieu_price_per_delivered_share=0.)
    bad=dict(good,reference='later duplicate',cash_in_lieu_price_per_delivered_share=18.56)
    correct=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='e'*64,source_evidence=[],suppress=[suppression],add=[good])
    target=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='f'*64,source_evidence=[],suppress=[deepcopy(suppression)],add=[bad])
    for i in range(5):
        day='2021-02-26'if i==0 else '2022-0'+str(i)+'-01'
        target['suppress'].append(dict(session=day,security_id='other'+str(i)))
        target['add'].append(dict(session=day,security_id='other'+str(i),cash_per_share=float(i)))
    descriptors=[]
    for name,doc in [('CORRECT',correct),('TARGET',target)]:
        raw=encoded(doc);h=p.sha(raw);logic[name]=h;logic[name+'_CONTENT']=p.digest(doc)
        (root/'book/repairs'/(h+'.json')).write_bytes(raw)
        descriptors.append(dict(filename=h+'.json',sha256=h,resume_session='2021-01-29',predecessor_checkpoint_sha256=doc['predecessor_checkpoint_sha256']))
    logic.update(RETIRED_SUPPRESS=p.digest(suppression),RETIRED_ADD=p.digest(bad),PRESERVED_ADD=p.digest(good))
    def row(sid,ticker,day):
        return dict(session=day,security_id=sid,ticker=ticker,issuer_id='ISSUER:'+sid,listing_first_session='2000-01-01',security_type_eligible='1',raw_open='20.0',raw_close='21.0')
    child=row('653423826172679659','TLRY','2021-05-03');cashrow=row('cash','CASH','2021-04-12')
    def witness(r):return {k:r[k]for k in ('session','security_id','ticker','issuer_id','listing_first_session','security_type_eligible')}|dict(source_observation_sha256=p.digest(r))
    b=b.model_copy(update=dict(bindings={k:logic[k]for k in b.bindings},delivered_identity_witness=witness(child)))
    parent=dict(sha256=b.bindings['OUTER'],source_cursor=b.bindings['CUTOVER'],base={'synthetic':True},repairs=descriptors,
                run=dict(checkpoint_sha256=b.bindings['INNER'],input_sha256=b.bindings['INPUT']))
    monkeypatch.setattr(p,'binding',lambda:b);monkeypatch.setattr(p,'source_parent',lambda:deepcopy(parent));monkeypatch.setattr(p,'source_logic',lambda:logic)
    import system_campaign_cash_batch as cashmodule
    class Cash:
        def __init__(self,catalog):self.catalog=dict(terms=[dict(security_id='cash',identity_witness=witness(cashrow))]);self.rows={}
        def hydrate(self,*args,**kwargs):
            assert kwargs['extra_witnesses']==(b.delivered_identity_witness,)
            return dict(witnesses=[cashrow,child],schema='research.factual-cash-batch-private-witnesses/1',source_metadata_unchanged=True,annual_scans=1,requested_events=1,auxiliary_witnesses=1)
    monkeypatch.setattr(cashmodule,'CashBatch',Cash)
    monkeypatch.setattr(p,'cash_hydration_function',lambda:Cash.hydrate)
    document=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=b.bindings['INNER'],source_evidence=[],
                  suppress=[dict(session='2021-04-13',security_id='cash',term_sha256='c'*64)],
                  add=[dict(session='2021-04-14',security_id='cash',kind='CASH_MERGER',cash_per_share=10.)])
    return root,parent,b,logic,document


def prepared(tmp_path,monkeypatch):
    root,parent,b,logic,doc=fixture(tmp_path,monkeypatch)
    activated=p.prepare_overlay(parent,root,'P07',doc);(root/'future-financial-overlay.json').write_bytes(encoded(activated))
    return root,parent,b,logic,doc,activated


def test_projection_prepares_neutral_activation_and_independent_reconstruction(tmp_path,monkeypatch):
    root,parent,b,logic,doc,activated=prepared(tmp_path,monkeypatch);saved=deepcopy((parent,doc))
    payload,raw,_,_,docs,_=p.verify_payload(root)
    assert activated==p.review_overlay(parent,root,'P07',doc)
    assert activated['suppress']==doc['suppress']and activated['add']==doc['add']and(parent,doc)==saved
    assert len(payload['derived_projection']['add'])==len(payload['derived_projection']['suppress'])==4
    assert docs[logic['CORRECT']]['add'][0]['cash_in_lieu_price_per_delivered_share']==0.
    assert docs[logic['TARGET']]['add'][0]['cash_in_lieu_price_per_delivered_share']==18.56
    assert p.OwnProjection(root).activation_sha==p.sha(encoded(activated))


def commit_activation(root,parent,b,activated):
    raw=encoded(activated);h=p.sha(raw);(root/'book/repairs'/(h+'.json')).write_bytes(raw)
    current=deepcopy(parent);current['source_cursor']='2021-04-30'
    current['repairs'].append(dict(filename=h+'.json',sha256=h,resume_session=b.bindings['CUTOVER'],predecessor_checkpoint_sha256=b.bindings['INNER']))
    return current


def test_retention_preserves_payload_view_and_activation_before_descendant_restore(tmp_path,monkeypatch):
    root,parent,b,logic,doc,activated=prepared(tmp_path,monkeypatch);current=commit_activation(root,parent,b,activated)
    out=tmp_path/'out';out.mkdir();before=deepcopy(current)
    p.preserve(root,current,out)
    assert current==before and all((root/n).read_bytes()==(out/n).read_bytes()for n in (p.PAYLOAD,p.VIEW))
    assert isinstance(p.retained_context(root,current),p.OwnProjection)


@pytest.mark.parametrize('change,code',[
    ('flag','OWN_PROJECTION_EXACT_PAYLOAD_AUTHORITY_AND_SOURCE_REFERENCES'),
    ('policy','OWN_PROJECTION_EXACT_POLICY_AND_DERIVED_VIEW'),
    ('metadata','OWN_PROJECTION_UNCHANGED_WITNESS_SCOPE_AND_METADATA'),
    ('witness','OWN_PROJECTION_EXACT_CASH_AND_DELIVERED_WITNESSES')])
def test_payload_guard_removal_falsifiers(tmp_path,monkeypatch,change,code):
    root,*_=prepared(tmp_path,monkeypatch);path=root/p.PAYLOAD;value=json.loads(path.read_bytes())
    if change=='flag':value['production_contacted']=True
    elif change=='policy':value['policy']['base_sha256']='0'*64
    elif change=='metadata':value['cash_witnesses']['source_metadata_unchanged']=False
    else:value['cash_witnesses']['witnesses'][1]=deepcopy(value['cash_witnesses']['witnesses'][0])
    path.write_bytes(encoded(value))
    with pytest.raises(ValueError,match=code):p.verify_payload(root)
    fn=drop_guard(p.verify_payload,code)
    assert fn(root)[0]==value


def drop_guard(function,code):
    import inspect,textwrap
    try:source=inspect.getsource(function)
    except OSError:source=inspect.getsource(getattr(original,function.__name__))
    node=ast.parse(textwrap.dedent(source)).body[0]
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call)and any(isinstance(a,ast.Constant)and a.value==code for a in node.value.args):
                self.count+=1;return ast.Pass()
            return self.generic_visit(node)
    transform=Remove();node=transform.visit(node);assert transform.count==1
    scope=dict(function.__globals__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<projection-guard-removed>','exec'),scope)
    return scope[function.__name__]


def test_preparation_history_guard_has_removal_falsifier(tmp_path,monkeypatch):
    root,parent,b,logic,doc=fixture(tmp_path,monkeypatch);actual=deepcopy(parent)
    actual['base']['changed']=True;code='OWN_PROJECTION_EXACT_ORIGINAL_INPUT_HISTORY'
    with pytest.raises(ValueError,match=code):p.prepare_overlay(actual,root,'P07',doc)
    assert drop_guard(p.prepare_overlay,code)(actual,root,'P07',doc)['add']==doc['add']


def test_new_boundary_uses_the_existing_exclusive_writer(tmp_path,monkeypatch):
    root,parent,b,logic,doc=fixture(tmp_path,monkeypatch);(root/p.PAYLOAD).write_bytes(b'old bytes')
    with pytest.raises(FileExistsError):p.prepare_overlay(parent,root,'P07',doc)
    assert(root/p.PAYLOAD).read_bytes()==b'old bytes'


def test_activation_reference_guard_removal_detects_preexisting_claim(tmp_path,monkeypatch):
    root,parent,b,logic,doc=fixture(tmp_path,monkeypatch);doc['source_evidence']=[dict(reference=p.CATALOG,sha256='0'*64)]
    code='OWN_PROJECTION_ACTIVATION_REFERENCES_NOT_PREEXISTING'
    with pytest.raises(ValueError,match=code):p.activate_document(doc,b'payload')
    assert len(drop_guard(p.activate_document,code)(doc,b'payload')['source_evidence'])==4


def test_initial_and_retained_contexts_do_not_accept_an_uncommitted_payload(tmp_path,monkeypatch):
    root,parent,b,logic,doc,activated=prepared(tmp_path,monkeypatch)
    code='OWN_PROJECTION_PAYLOAD_REQUIRES_COMMITTED_ACTIVATION'
    with pytest.raises(ValueError,match=code):p.retained_activation(root,parent)
    assert drop_guard(p.retained_activation,code)(root,parent)is None


@pytest.mark.parametrize('change,code',[
    ('raw','OWN_PROJECTION_RETAINED_INPUT_BYTES'),
    ('cursor','OWN_PROJECTION_ONE_COMMITTED_UNCONSUMED_POLICY'),
    ('boundary','OWN_PROJECTION_RETAINED_ACTIVATION_BOUNDARY')])
def test_retained_policy_guard_removal_falsifiers(tmp_path,monkeypatch,change,code):
    root,parent,b,logic,doc,activated=prepared(tmp_path,monkeypatch);current=commit_activation(root,parent,b,activated)
    entry=current['repairs'][-1]
    if change=='raw':
        path=root/'book/repairs'/entry['filename'];path.write_bytes(path.read_bytes()+b' ')
    elif change=='cursor':current['source_cursor']='2021-03-30'
    else:entry['resume_session']='2021-04-01'
    with pytest.raises(ValueError,match=code):p.retained_activation(root,current)
    assert isinstance(drop_guard(p.retained_activation,code)(root,current),p.OwnProjection)


def test_constructor_and_review_guard_removal_falsifiers(tmp_path,monkeypatch):
    root,parent,b,logic,doc,activated=prepared(tmp_path,monkeypatch)
    altered=deepcopy(activated);altered['predecessor_checkpoint_sha256']='0'*64
    (root/'future-financial-overlay.json').write_bytes(encoded(altered));code='OWN_PROJECTION_EXACT_CANONICAL_ACTIVATION_DOCUMENT'
    with pytest.raises(ValueError,match=code):p.OwnProjection(root)
    obj=p.OwnProjection.__new__(p.OwnProjection);drop_guard(p.OwnProjection.__init__,code)(obj,root)
    assert obj.activation_sha==p.sha(encoded(altered))
    wrong=deepcopy(doc);wrong['add']=[];code='OWN_PROJECTION_REVIEW_RECONSTRUCTS_ORIGINAL_NEW_PATCH'
    with pytest.raises(ValueError,match=code):p.review_overlay(parent,root,'P07',wrong)
    assert drop_guard(p.review_overlay,code)(parent,root,'P07',wrong)['add']==[]


def test_retained_output_bytes_guard_removal_falsifier(tmp_path,monkeypatch):
    root,parent,b,logic,doc,activated=prepared(tmp_path,monkeypatch);current=commit_activation(root,parent,b,activated)
    out=tmp_path/'out';out.mkdir();(out/p.PAYLOAD).write_bytes(b'changed')
    code='OWN_PROJECTION_RETAINED_PAYLOAD_AND_VIEW_BYTES'
    with pytest.raises(ValueError,match=code):p.preserve(root,current,out)
    drop_guard(p.preserve,code)(root,current,out);assert(out/p.PAYLOAD).read_bytes()==b'changed'


def test_original_boundary_and_retirement_guards_remain_active_under_new_binding(tmp_path,monkeypatch):
    root,parent,b,logic,doc=fixture(tmp_path,monkeypatch);docs=logic['documents'](root,parent)
    wrong=deepcopy(parent);wrong['source_cursor']='2021-04-30'
    code='AMENDMENT_EXACT_OWN_UNCONSUMED_PREDECESSOR'
    with pytest.raises(ValueError,match=code):logic['validate_conflict'](wrong,docs)
    assert drop_guard(logic['validate_conflict'],code)(wrong,docs)
    changed=deepcopy(docs);changed[logic['CORRECT']]['add'][0]['cash_in_lieu_price_per_delivered_share']=1.
    with pytest.raises(ValueError):logic['validate_conflict'](parent,changed)


def test_synthetic_canonical_lifecycle_delegates_only_the_derived_view_and_restores_hooks(tmp_path,monkeypatch):
    root,parent,b,logic,doc,activated=prepared(tmp_path,monkeypatch);projection=p.OwnProjection(root);objects=[];calls=[]
    class Loaded:
        def __init__(self,path):self.raw=path.read_bytes();self.sha256=p.sha(self.raw);self.doc=json.loads(self.raw)
        def model_dump(self,**kwargs):return deepcopy(self.doc)
    class Branch:
        def load(self,path,**kwargs):obj=Loaded(Path(path));objects.append(obj);return obj
        def apply(self,packet,obj):calls.append((packet,obj));return packet
    branch=Branch();backtest=SimpleNamespace(load_repair=branch.load,apply_repair=branch.apply)
    repair=SimpleNamespace(load_repair=branch.load,_loaded=lambda obj:None if any(obj is x for x in objects)else (_ for _ in()).throw(ValueError('unregistered')))
    module=ModuleType('research.pooled_vacancy_funding');module.backtest=backtest;module.repair=repair
    monkeypatch.setitem(sys.modules,module.__name__,module)
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    before=(repair.load_repair,backtest.load_repair,backtest.apply_repair)
    with projection:
        target=backtest.load_repair(root/'book/repairs'/(logic['TARGET']+'.json'),resume_session='2021-01-29',predecessor_checkpoint_sha256='f'*64)
        packet=SimpleNamespace(day='2021-04-30')
        with pytest.raises(ValueError,match='ONLY_ACTIVATED'):backtest.apply_repair(packet,target)
        with pytest.raises(ValueError,match='EXACT_CANONICAL_ACTIVATION_BOUNDARY'):
            backtest.load_repair(projection.overlay,resume_session=b.bindings['CUTOVER'],predecessor_checkpoint_sha256='0'*64)
        backtest.load_repair(projection.overlay,resume_session=b.bindings['CUTOVER'],predecessor_checkpoint_sha256=b.bindings['INNER'])
        assert p.branch_loader_owner(backtest.load_repair)is branch
        backtest.apply_repair(packet,target);assert calls[-1][1]is projection.derived and calls[-1][0]is packet
        historical=SimpleNamespace(day='2021-02-26');backtest.apply_repair(historical,target);assert calls[-1][1]is target
        projection.active=False;code='OWN_PROJECTION_BRANCH_CODEC_ONLY_AFTER_ACTIVATION'
        with pytest.raises(ValueError,match=code):p.branch_loader_owner(backtest.load_repair)
        assert drop_guard(p.branch_loader_owner,code)(backtest.load_repair)is branch
    assert(repair.load_repair,backtest.load_repair,backtest.apply_repair)==before


@pytest.mark.parametrize('change,code',[
    ('bytes','OWN_PROJECTION_EXACT_REVIEWED_BINDING_BYTES'),
    ('fields','OWN_PROJECTION_EXACT_BINDING_FIELDS')])
def test_binding_guard_removal_falsifiers(tmp_path,monkeypatch,change,code):
    value=json.loads((p.HERE/p.BINDING).read_bytes())
    if change=='bytes':value['bindings']['OUTER']='0'*64
    else:value['bindings']['UNEXPECTED']='value'
    raw=encoded(value);(tmp_path/p.BINDING).write_bytes(raw);monkeypatch.setattr(p,'HERE',tmp_path)
    if change=='fields':monkeypatch.setattr(p,'BINDING_SHA',p.sha(raw))
    with pytest.raises(ValueError,match=code):p.binding()
    assert drop_guard(p.binding,code)().bindings==value['bindings']


def test_source_parent_admission_guard_removal_falsifier(monkeypatch):
    actual=authority.root_spec
    def changed(*args,**kwargs):return dict(actual(*args,**kwargs),outer_sha256='0'*64)
    monkeypatch.setattr(authority,'root_spec',changed);code='OWN_PROJECTION_SEPARATELY_ADMITTED_SOURCE_PARENT'
    with pytest.raises(ValueError,match=code):p.source_parent()
    assert drop_guard(p.source_parent,code)()['sha256']=='0'*64


@pytest.mark.parametrize('change,code',[
    ('bytes','OWN_PROJECTION_UNCHANGED_ORIGINAL_ADAPTER'),
    ('surface','OWN_PROJECTION_EXACT_REUSED_SOURCE_SURFACE')])
def test_original_source_guard_removal_falsifiers(tmp_path,monkeypatch,change,code):
    b=p.binding();raw=(p.HERE/'system_campaign_future_amendment.py').read_bytes()
    if change=='bytes':raw+=b'\n# changed immutable source\n'
    else:
        tree=ast.parse(raw);owner=next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='FutureProjection')
        owner.body=[n for n in owner.body if not isinstance(n,ast.FunctionDef)or n.name!='__exit__']
        raw=ast.unparse(tree).encode()
        b=b.model_copy(update=dict(original_adapter_sha256=p.sha(raw)))
    (tmp_path/'system_campaign_future_amendment.py').write_bytes(raw)
    monkeypatch.setattr(p,'HERE',tmp_path);monkeypatch.setattr(p,'binding',lambda:b)
    with pytest.raises(ValueError,match=code):p.source_logic()
    assert drop_guard(p.source_logic,code)()['validate_conflict']


@pytest.mark.parametrize('change,code',[
    ('bytes','OWN_PROJECTION_UNCHANGED_ORIGINAL_CANONICAL_GATE'),
    ('surface','OWN_PROJECTION_EXACT_GATE_SURFACE'),
    ('activation','OWN_PROJECTION_ACTUAL_QUALIFIED_CANONICAL_ACTIVATION')])
def test_canonical_gate_source_and_observation_guards_have_removal_falsifiers(tmp_path,monkeypatch,change,code):
    b=p.binding();raw=b'def expect_refusal(fn,code): pass\ndef qualify(cp,root,cash,amendment,packet_source_sha256): return amendment.synthetic_loaded\n'
    if change=='surface':raw=raw.split(b'\n',1)[1]
    if change!='bytes':b=b.model_copy(update=dict(original_gate_sha256=p.sha(raw)))
    (tmp_path/'system_campaign_amendment_gate.py').write_bytes(raw)
    monkeypatch.setattr(p,'HERE',tmp_path);monkeypatch.setattr(p,'binding',lambda:b)
    projection=p.OwnProjection.__new__(p.OwnProjection);projection.activation_sha='a'*64;projection.projected_packets=0 if change=='activation'else 1
    projection.cash=object();projection.synthetic_loaded=SimpleNamespace(sha256=projection.activation_sha)
    projection.logic=dict(validate_conflict=lambda *args:None,projection=lambda *args:None)
    from system_campaign_sprint_facts import PACKET_SOURCE_PATH
    cp=dict(base=dict(sources={PACKET_SOURCE_PATH:'b'*64}))
    with pytest.raises(ValueError,match=code):p.qualify_initial(projection,tmp_path,cp)
    assert drop_guard(p.qualify_initial,code)(projection,tmp_path,cp)is None


def test_ordinary_preflight_excludes_only_validated_branch_and_keeps_every_ordinary_guard(tmp_path):
    from research.capital_risk.forecast_tests.test_financial_retention import typed_book
    root,cp,_=typed_book(tmp_path);cp.update(sha256=p.binding().bindings['OUTER'],source_cursor='2021-03-31',run=dict(input_sha256='a'*64))
    ordinary=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='b'*64,source_evidence=[],suppress=[],add=[])
    raw=encoded(ordinary);h=p.sha(raw);(root/'book/repairs'/(h+'.json')).write_bytes(raw)
    cp['repairs'].append(dict(filename=h+'.json',sha256=h,resume_session='2021-03-31',predecessor_checkpoint_sha256='b'*64))
    catalog=dict(terms=[dict(ticker='NEW',security_id='new',native_session='2021-04-12',added=dict(session='2021-04-13',security_id='new'))])
    before=deepcopy(cp);report=p.ordinary_preflight(cp,root,catalog)
    assert cp==before and report['status']=='DISJOINT_UNCONSUMED'and report['retained_ordinary_repairs']==1
    assert report['retained_branch_input_sha256']==cp['repairs'][0]['sha256']
    code='OWN_PROJECTION_PREFLIGHT_ONLY_EXACT_RETAINED_BRANCH_INPUT';cp['sha256']='0'*64
    with pytest.raises(ValueError,match=code):p.ordinary_preflight(cp,root,catalog)
    assert drop_guard(p.ordinary_preflight,code)(cp,root,catalog)['status']=='DISJOINT_UNCONSUMED'
    cp['sha256']=before['sha256'];(root/'book/repairs'/(h+'.json')).write_bytes(raw+b' ')
    with pytest.raises(ValueError,match='RETAINED.*BYTES'):p.ordinary_preflight(cp,root,catalog)


def test_original_cash_hydration_source_guard_has_removal_falsifier(tmp_path,monkeypatch):
    source=p.HERE;raw=(source/'system_campaign_cash_batch.py').read_bytes()+b'\n# modified immutable adapter\n'
    (tmp_path/'system_campaign_cash_batch.py').write_bytes(raw)
    (tmp_path/'system-campaign-parallel-discovery-request-001.json').write_bytes((source/'system-campaign-parallel-discovery-request-001.json').read_bytes())
    monkeypatch.setattr(p,'HERE',tmp_path);code='OWN_PROJECTION_UNCHANGED_ORIGINAL_CASH_HYDRATION'
    with pytest.raises(ValueError,match=code):p.cash_hydration_function()
    assert drop_guard(p.cash_hydration_function,code)().__name__=='hydrate'

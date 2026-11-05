"""Original parser/loader AST composition, never canonical replay or restore."""
import ast,builtins,copy,json
from contextlib import contextmanager
from dataclasses import asdict,replace,make_dataclass
from pathlib import Path
from types import SimpleNamespace
import pytest
import sys
sys.path.insert(0,str(Path(__file__).parent))
from test_additional_sensor import C,DEP,data,runtime,env,fixture,fence,full_input

def execute(nodes,ns):
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<immutable-loader-AST-synthetic-input-API>','exec'),ns)
    return ns

def original_chain_images(e,monkeypatch):
    import system_campaign_financial_branches as b
    import system_campaign_zogenix_input as z
    import system_campaign_uncertainty_input as original_input
    cp,origin=full_input(e,monkeypatch)
    loads=[]
    def canonical_loader(path,*,resume_session,predecessor_checkpoint_sha256):
        raw=Path(path).read_bytes();doc=json.loads(raw)
        if doc['schema']!='terminal-repair/1':raise ValueError('ORIGINAL_CANONICAL_REFUSES_TYPED_MODEL')
        loads.append((str(path),resume_session,predecessor_checkpoint_sha256))
        return SimpleNamespace(sha256=data.sha(raw),_resume_session=resume_session,
            predecessor_checkpoint_sha256=predecessor_checkpoint_sha256,model_dump=lambda **k:doc)
    original_apply=lambda packet,obj:packet
    api=SimpleNamespace(load_repair=canonical_loader,apply_repair=original_apply)
    repair=SimpleNamespace(load_repair=canonical_loader)
    projection_module=SimpleNamespace()
    codec_module=SimpleNamespace()
    def imports(name,globals=None,locals=None,fromlist=(),level=0):
        if name=='full_system_core':return SimpleNamespace(hosted=lambda:None)
        if name=='research.pooled_vacancy_funding':return SimpleNamespace(backtest=api,repair=repair)
        if name=='system_campaign_financial_projection':return projection_module
        if name=='system_campaign_zogenix_input':return codec_module
        return builtins.__import__(name,globals,locals,fromlist,level)
    builtins_image=dict(vars(builtins),__import__=imports)
    ns=dict(vars(original_input),__builtins__=builtins_image)
    base,=[n for n in ast.parse((DEP/'system_campaign_uncertainty_input.py').read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='InputCodec']
    execute([base],ns)
    # Original B19 method/super closure with the exact original parent class image.
    ns.update(parse=b.parse,INPUT=b.INPUT)
    branch,=[n for n in ast.parse(data.source('system_campaign_financial_branches.py')).body if isinstance(n,ast.ClassDef) and n.name=='Codec']
    execute([branch],ns);Branch=ns['Codec']
    binding=json.loads((DEP/'system-campaign-own-future-projection.json').read_bytes())['bindings']
    scope=dict(PAYLOAD_NAME='hydrated-future-input-projection.json',OVERLAY_NAME='future-input-amendment.json',Path=Path,json=json,need=data.need,sha=data.sha,save=lambda path,value:path.write_bytes(data.encoded(value)),
        __builtins__=builtins_image,**binding)
    frozen,=[n for n in ast.parse((DEP/'system_campaign_future_amendment.py').read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='FutureProjection']
    execute([frozen],scope)
    own,=[n for n in ast.parse((DEP/'system_campaign_financial_projection.py').read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='OwnProjection']
    owner,=[n for n in ast.parse((DEP/'system_campaign_financial_projection.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='branch_loader_owner']
    execute([own,owner],scope)
    projection_module.OwnProjection=scope['OwnProjection'];projection_module.branch_loader_owner=scope['branch_loader_owner']
    zns=dict(vars(z),__builtins__=builtins_image)
    zcls,=[n for n in ast.parse(data.source('system_campaign_zogenix_input.py')).body if isinstance(n,ast.ClassDef) and n.name=='InputCodec']
    execute([zcls],zns);codec_module.InputCodec=zns['InputCodec']
    q=data.function(Path(runtime.__file__).read_bytes(),'qualified_zcodec')
    qns=dict(vars(runtime),__builtins__=builtins_image,hosted=lambda:None)
    execute([q],qns)
    activation=e.root/'activation.json';activation.write_bytes(data.encoded(dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=binding['INNER'])))
    view=e.root/'derived.json';view.write_bytes(data.encoded(dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=binding['INNER'],synthetic_derived=True)))
    p=scope['OwnProjection'].__new__(scope['OwnProjection']);p.logic={'FutureProjection':scope['FutureProjection']}
    p.projection_path=view;p.overlay_raw=activation.read_bytes();p.activation_sha=data.sha(p.overlay_raw)
    p.active=False;p.loaded_target=[];p.projected_packets=0
    Native=make_dataclass('SyntheticNative',[(k,object) for k in e.p['event']['native_term']])
    native=Native(**e.p['event']['native_term'])
    from system_campaign_zogenix_facts import evidence as original_evidence
    evidence=original_evidence(e.root)
    return SimpleNamespace(api=api,repair=repair,Branch=Branch,projection=p,activation=activation,binding=binding,
        q=qns['qualified_zcodec'],canonical=canonical_loader,original_apply=original_apply,native=native,evidence=evidence,
        cp=cp,origin=origin,loads=loads)

def test_original_b19_apha_activation_then_z_codec_capture_and_old_origin(env,monkeypatch):
    s=original_chain_images(env,monkeypatch)
    with s.Branch(env.fixture['original_branch_document']['source_evidence']) as branch:
        with s.projection as own:
            assert own.active is False
            s.api.load_repair(s.activation,resume_session=s.binding['CUTOVER'],predecessor_checkpoint_sha256=s.binding['INNER'])
            assert own.active is True
            with s.q(branch,own,s.evidence,s.native) as z:
                d=s.origin['sensor_descriptor']
                obj=s.api.load_repair(env.root/'book/repairs'/d['filename'],resume_session=d['resume_session'],predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
                assert any(obj is v for v in z.objects) and z.original_load.__self__ is own
                old=env.p['original_branch_descriptor']
                original=s.api.load_repair(env.root/'book/repairs'/old['filename'],resume_session=old['resume_session'],predecessor_checkpoint_sha256=old['predecessor_checkpoint_sha256'])
                assert any(original is v for v in branch.objects)
                assert original._resume_session=='2019-09-30'
                assert s.api.load_repair.__self__ is z and s.repair.load_repair.__self__ is z
            assert s.api.load_repair==own.load and s.repair.load_repair==own.load
    assert s.api.load_repair is s.canonical and s.repair.load_repair is s.canonical
    assert s.api.apply_repair is s.original_apply

@pytest.mark.parametrize('wrong',['inactive','repair_surface','branch_owner','backtest_owner'])
def test_full_installed_chain_identity_refusals(env,monkeypatch,wrong):
    s=original_chain_images(env,monkeypatch)
    with s.Branch(env.fixture['original_branch_document']['source_evidence']) as branch,s.projection as own:
        if wrong!='inactive':s.api.load_repair(s.activation,resume_session=s.binding['CUTOVER'],predecessor_checkpoint_sha256=s.binding['INNER'])
        if wrong=='repair_surface':s.repair.load_repair=s.canonical
        if wrong=='backtest_owner':s.api.load_repair=branch.load
        selected=object() if wrong=='branch_owner' else branch
        with pytest.raises(ValueError,match='INSTALLED_ACTIVE_APHA_B19'):
            with s.q(selected,own,s.evidence,s.native):pass

@pytest.mark.parametrize('wrong',['clock','predecessor'])
def test_original_activation_loader_rejects_changed_original_clock(env,monkeypatch,wrong):
    s=original_chain_images(env,monkeypatch)
    with s.Branch(env.fixture['original_branch_document']['source_evidence']),s.projection as own:
        with pytest.raises(ValueError,match='ACTIVATION_BOUNDARY'):
            s.api.load_repair(s.activation,resume_session='2022-02-28' if wrong=='clock' else s.binding['CUTOVER'],
                predecessor_checkpoint_sha256='0'*64 if wrong=='predecessor' else s.binding['INNER'])
        assert own.active is False

def test_z_codec_exception_restores_exact_original_both_surfaces(env,monkeypatch):
    s=original_chain_images(env,monkeypatch)
    with s.Branch(env.fixture['original_branch_document']['source_evidence']) as branch,s.projection as own:
        s.api.load_repair(s.activation,resume_session=s.binding['CUTOVER'],predecessor_checkpoint_sha256=s.binding['INNER'])
        with pytest.raises(RuntimeError):
            with s.q(branch,own,s.evidence,s.native):raise RuntimeError('synthetic body exception')
        assert s.api.load_repair==own.load and s.repair.load_repair==own.load
    assert s.api.load_repair is s.canonical and s.repair.load_repair is s.canonical

@pytest.mark.parametrize('field,value',[('schema','other/1'),('source_identity_qualified_for_separate_future_input_review',False),
    ('source_value_or_settlement_timing_qualified',True),('financial_authority',True),('input_adopted',True),
    ('local_canonical_runtime_executed',True),('financial_workers_launched',True),('financial_workers_launched',1),
    ('fresh_archive_and2022_raw_scan_verified',False)])
def test_actual_source279_qualification_schema_wrong_flags_refuse(env,field,value):
    source=json.loads((env.overlay/env.u.OWN_SOURCE_CATALOG).read_bytes())['sources'][env.p['source_payload_sha256']]
    q=copy.deepcopy(source['qualification']);assert data.qualified_source_identity_only(q) is True
    q[field]=value
    with pytest.raises(ValueError,match='CLOSED_IDENTITY_ONLY_QUALIFICATION_SCHEMA'):data.qualified_source_identity_only(q)

def test_qualification_compatibility_changes_only_one_original_field_read(env,monkeypatch):
    old=data.function(Path(env.u.__file__).read_bytes(),'own_source_binding');original=copy.deepcopy(old)
    index,=[i for i,n in enumerate(original.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='event']
    original.body=original.body[:index]+[ast.Return(ast.Name(id='payload',ctx=ast.Load()))]
    saved=data.function;captured=[]
    def capture(raw,name):
        fn=saved(raw,name)
        if name=='own_source_binding':captured.append(fn)
        return fn
    monkeypatch.setattr(data,'function',capture);data.common_source_binding(env.cp,env.p)
    changed=captured[-1]
    class Inverse(ast.NodeTransformer):
        count=0
        def visit_Call(self,n):
            if isinstance(n.func,ast.Name) and n.func.id=='qualified_source_identity_only':
                self.count+=1;return ast.parse("qualification['source_identity_only']",mode='eval').body
            return self.generic_visit(n)
    inv=Inverse();restored=inv.visit(changed)
    assert inv.count==1 and ast.dump(restored,include_attributes=False)==ast.dump(original,include_attributes=False)

def test_wrong_declared_branch_owner_guard_removal_is_detected(env,monkeypatch):
    s=original_chain_images(env,monkeypatch)
    fn=data.function(Path(runtime.__file__).read_bytes(),'qualified_zcodec')
    guard,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='need'
        and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='ADDITIONAL_EXACT_INSTALLED_ACTIVE_APHA_B19_LOADER_IDENTITIES']
    # Reuse only the original test import images, not any canonical module.
    scope=dict(s.q.__wrapped__.__globals__)
    guard.args[0]=ast.Constant(True);execute([fn],scope)
    with s.Branch(env.fixture['original_branch_document']['source_evidence']) as branch,s.projection as own:
        s.api.load_repair(s.activation,resume_session=s.binding['CUTOVER'],predecessor_checkpoint_sha256=s.binding['INNER'])
        with pytest.raises(ValueError):
            with s.q(object(),own,s.evidence,s.native):pass
        with scope['qualified_zcodec'](object(),own,s.evidence,s.native) as loaded:
            assert loaded.original_load.__self__ is own

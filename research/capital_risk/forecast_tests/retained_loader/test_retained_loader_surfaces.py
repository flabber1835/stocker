"""Original loader ASTs with synthetic objects; no financial engine execution."""
import ast
import builtins
from contextlib import contextmanager,nullcontext,ExitStack
from copy import deepcopy
import hashlib,importlib.abc,json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

C=Path(__file__).resolve().parents[2]
if not (C/'system_campaign_financial_compound_dispatch.py').exists():C=C.parent
FIXTURE=Path(__file__).parent/'fixtures/P07-own986-input-only.json'
FIXTURE_SHA='6ad69f4d529268a54377a0bd9c969b09e9c07e707176ed36c177172d00ee1b21'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def need(value,code):
    if not value:raise ValueError(code)
def source(name):return(C/name).read_bytes()
def node(name,kind,selected):return next(n for n in ast.parse(source(name)).body if isinstance(n,kind)and n.name==selected)
def run_nodes(nodes,namespace):
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<exact-original-input-loader-AST-synthetic-API>','exec'),namespace)
    return namespace

class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise AssertionError('NO_FINANCIAL_IMPORT:'+fullname)
@pytest.fixture(autouse=True)
def fenced():
    fence=Fence();sys.meta_path.insert(0,fence);yield;sys.meta_path.remove(fence)

def data():
    raw=FIXTURE.read_bytes();assert sha(raw)==FIXTURE_SHA
    value=json.loads(raw)
    assert value['financial_state_included']is False
    for name,h in value['immutable_sources'].items():assert sha(source(name))==h
    assert value['immutable_sources']['system_campaign_financial_compound_runtime_v2.py']=='0b4ade1d380b395098f057dd9a8b65cd73ae8697f364640f05118326da25bd74'
    return value

class SyntheticRepair:
    """Minimal pure parsed-object API; no book, financial math or serialization."""
    def __init__(self,document):
        self.document=deepcopy(document);self.source_evidence=[SimpleNamespace(**e)for e in document['source_evidence']]
        self.predecessor_checkpoint_sha256=document['predecessor_checkpoint_sha256'];self.__pydantic_private__={}
    @classmethod
    def model_validate(cls,value):return cls(value)
    def model_dump(self,**kwargs):return deepcopy(self.document)
    @property
    def earliest_affected_session(self):return min(v['session']for v in self.document['suppress']+self.document['add'])
    @property
    def sha256(self):return self.__pydantic_private__['_file_sha256']
    @property
    def _resume_session(self):return self.__pydantic_private__['_resume_session']
    @property
    def _document_sha256(self):return self.__pydantic_private__['_document_sha256']

def setup(tmp_path):
    d=data();calls=[]
    def parser(path,*,resume_session,predecessor_checkpoint_sha256):
        raw=Path(path).read_bytes();doc=json.loads(raw)
        need(doc['predecessor_checkpoint_sha256']==predecessor_checkpoint_sha256,'SYNTHETIC_PARSER_EXACT_ORIGINAL_PREDECESSOR')
        need(doc['schema']=='terminal-repair/1'and(doc['suppress']or doc['add']),'SYNTHETIC_PARSER_NONEMPTY_TERMINAL_DOCUMENT')
        result=SyntheticRepair(doc);result.__pydantic_private__.update(_file_sha256=sha(raw),_resume_session=resume_session,_document_sha256=digest(doc))
        calls.append((Path(path).name,resume_session,predecessor_checkpoint_sha256,result));return result
    backtest=SimpleNamespace(load_repair=parser,apply_repair=lambda packet,obj:packet)
    repair=SimpleNamespace(load_repair=parser,__file__=str(C/'system_campaign_financial_compound_runtime_v2.py'))
    def imports(name,globals=None,locals=None,fromlist=(),level=0):
        if name=='research.pooled_vacancy_funding':return SimpleNamespace(backtest=backtest,repair=repair)
        if name=='full_system_core':return SimpleNamespace(hosted=lambda:None)
        return builtins.__import__(name,globals,locals,fromlist,level)
    base=dict(__builtins__=dict(vars(builtins),__import__=imports),Path=Path,json=json,deepcopy=deepcopy,sha=sha,digest=digest,need=need,require=need,hosted=lambda:None,SimpleNamespace=SimpleNamespace)
    class BranchInput:pass
    # Preserve the actual B19/InputCodec superclass loader sequence.
    b19=dict(base,LeadershipUncertaintyInput=BranchInput,INPUT='research.leadership-branch-uncertainty-input/1')
    run_nodes([node('system_campaign_uncertainty_input.py',ast.ClassDef,'InputCodec'),node('system_campaign_financial_branches.py',ast.ClassDef,'Codec')],b19)
    support=run_nodes([node('system_campaign_financial_compound_v2_support.py',ast.FunctionDef,n)for n in('activation_descriptor','qualified_loaded_view')],dict(base,hash_value=lambda v:isinstance(v,str)and len(v)==64))
    class SyntheticPacketProjection:
        def __init__(self,*args,**kwargs):self.descriptor={'test_only':'no_financial_arithmetic'};self.calls=[]
        def apply(self,packet,descriptor):self.calls.append((packet,descriptor));return packet
    ref='research.compound-distribution-input/catalog/2'
    doc=d['compound_document'];refs={e['reference']:e['sha256']for e in doc['source_evidence']}
    api=SimpleNamespace(backtest=backtest,repair=repair,vendor=lambda row:row,spin_factory=lambda **fields:fields)
    ns=dict(base,CATALOG_REF=ref,OVERLAY='future-financial-overlay.json',document=lambda payload,raw:doc,
        qualified_record=lambda arm:d['compound_record'],refs=lambda raw,record:refs,EventSessionProjection=SyntheticPacketProjection,
        activation_descriptor=support['activation_descriptor'],qualified_loaded_view=support['qualified_loaded_view'])
    run_nodes([node('system_campaign_financial_compound_runtime_v2.py',ast.ClassDef,'ProjectionContext')],ns)
    compound_path=tmp_path/d['compound_descriptor']['filename'];compound_path.write_text(d['compound_document_raw'],newline='')
    payload_raw=(json.dumps(d['compound_payload'],sort_keys=True,indent=2)+'\n').encode()
    # Raw payload bytes are not reparsed financially; only the source-bound binding is used.
    ctx=ns['ProjectionContext'](tmp_path,compound_path.name,payload=(d['compound_payload'],payload_raw),api=api)
    amendment=node('system_campaign_future_amendment.py',ast.ClassDef,'FutureProjection')
    amendment.body=[n for n in amendment.body if not isinstance(n,ast.FunctionDef)or n.name!='__init__']
    bindings=d['APHA_binding']['bindings'];aphans=dict(base,**bindings)
    run_nodes([amendment],aphans)
    apha_refs={e['reference']:e['sha256']for e in json.loads(d['APHA_document_raw'])['source_evidence']}
    catalog='research.own-future-projection/catalog/1';compiler='research.own-future-projection/adapter/1'
    hydrated='research.own-future-projection/payload/1';apha_payload_raw=(json.dumps(d['APHA_payload'],sort_keys=True,indent=2)+'\n').encode()
    assert sha(apha_payload_raw)==apha_refs[hydrated]
    apha_path=tmp_path/d['APHA_descriptor']['filename'];apha_path.write_text(d['APHA_document_raw'],newline='')
    original=dict(base={'synthetic':'unused'},source_cursor=bindings['CUTOVER'],run=dict(checkpoint_sha256=bindings['INNER']))
    own=dict(base,VIEW='derived-own-future-projection.json',HYDRATED=hydrated,
        binding=lambda:SimpleNamespace(bindings=bindings),references=lambda:{catalog:apha_refs[catalog],compiler:apha_refs[compiler]},
        verify_payload=lambda root:(d['APHA_payload'],apha_payload_raw,original,{'FutureProjection':aphans['FutureProjection']},{},None))
    run_nodes([node('system_campaign_financial_projection.py',ast.ClassDef,'OwnProjection'),node('system_campaign_financial_projection.py',ast.FunctionDef,'branch_loader_owner')],own)
    apha=own['OwnProjection'](tmp_path,apha_path.name)
    (tmp_path/'derived-own-future-projection.json').write_text(json.dumps(d['APHA_projection']))
    route=dict(base,contextmanager=contextmanager)
    run_nodes([node('system_campaign_financial_compound_dispatch.py',ast.FunctionDef,'retained_loader_surfaces')],route)
    return SimpleNamespace(data=d,ctx=ctx,codec=b19['Codec']([]),apha=apha,backtest=backtest,repair=repair,parser=parser,
        route=route['retained_loader_surfaces'],module=SimpleNamespace(ProjectionContext=ns['ProjectionContext']),calls=calls,
        compound_path=compound_path,apha_path=apha_path,branch_loader_owner=own['branch_loader_owner'])

def exercise(s,bridge):
    d=s.data;descriptor=d['compound_descriptor']
    with s.ctx:
        with (s.route((s.module,))if bridge else nullcontext()):
            with s.codec,s.apha:
                # Original APHA activation establishes active=True through its loader.
                a=d['APHA_descriptor'];s.backtest.load_repair(s.apha_path,resume_session=a['resume_session'],predecessor_checkpoint_sha256=a['predecessor_checkpoint_sha256'])
                assert s.branch_loader_owner(s.backtest.load_repair)is s.codec
                loaded=s.backtest.load_repair(s.compound_path,resume_session=descriptor['resume_session'],predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'])
                packet=SimpleNamespace(day='2016-04-26')
                fixed=s.backtest.apply_repair(packet,loaded)
                assert fixed is packet
                assert loaded is s.ctx.bound_objects[-1]
                assert loaded.earliest_affected_session=='2021-05-25'
                assert loaded._resume_session=='2021-04-30'
                assert s.ctx.projection.calls==[(packet,s.ctx.projection.descriptor)]
                return loaded

def test_actual_loader_AST_before_bridge_reproduces_exact_hosted_refusal(tmp_path):
    s=setup(tmp_path)
    with pytest.raises(ValueError,match='COMPOUND_V2_APPLY_REQUIRES_ACTUAL_QUALIFIED_LOADED_OBJECT'):exercise(s,False)
    assert s.ctx.bound_objects==[]
    assert s.backtest.load_repair is s.parser and s.repair.load_repair is s.parser

def test_actual_loader_AST_after_bridge_binds_exact_object_preserves_branch_and_clocks(tmp_path):
    s=setup(tmp_path);loaded=exercise(s,True)
    assert loaded is s.ctx.bound_objects[-1]
    assert s.backtest.load_repair is s.parser and s.repair.load_repair is s.parser

def test_actual_loaded_identity_guard_still_refuses_forged_copy(tmp_path):
    s=setup(tmp_path)
    with s.ctx,s.route((s.module,)),s.codec,s.apha:
        d=s.data['compound_descriptor'];loaded=s.backtest.load_repair(s.compound_path,resume_session=d['resume_session'],predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
        with pytest.raises(ValueError,match='ACTUAL_QUALIFIED_LOADED_OBJECT'):s.ctx.apply(SimpleNamespace(day='2016-04-26'),deepcopy(loaded))

def test_scoped_bridge_restores_both_surfaces_after_nested_and_exception(tmp_path):
    s=setup(tmp_path)
    with s.ctx:
        installed=s.backtest.load_repair
        with s.route((s.module,)):
            assert s.repair.load_repair is installed
            with pytest.raises(RuntimeError):
                with s.route((s.module,)),s.codec,s.apha:raise RuntimeError('synthetic body failure')
            assert s.repair.load_repair is installed and s.backtest.load_repair==installed
        assert s.repair.load_repair is s.parser and s.backtest.load_repair==installed
    assert s.backtest.load_repair is s.parser and s.repair.load_repair is s.parser

def test_no_retained_activation_leaves_unrelated_surfaces_untouched(tmp_path):
    s=setup(tmp_path);foreign=lambda *a,**k:None;s.backtest.load_repair=foreign
    with s.route(()):assert s.backtest.load_repair is foreign and s.repair.load_repair is s.parser
    assert s.backtest.load_repair is foreign and s.repair.load_repair is s.parser

@pytest.mark.parametrize('kind',['unowned','inactive','wrong_backtest','wrong_repair'])
def test_unknown_or_inactive_installed_owner_refused(tmp_path,kind):
    s=setup(tmp_path)
    with s.ctx:
        original_api=s.ctx.api
        if kind=='unowned':s.backtest.load_repair=s.parser
        elif kind=='inactive':s.ctx.active=False
        elif kind=='wrong_backtest':s.ctx.api=SimpleNamespace(backtest=object(),repair=s.repair)
        else:s.ctx.api=SimpleNamespace(backtest=s.backtest,repair=object())
        with pytest.raises(ValueError,match='EXACT_ACTIVE_INSTALLED_LOADER_OWNER'):
            with s.route((s.module,)):pass
        assert s.repair.load_repair is s.parser
        s.ctx.api=original_api

def test_owner_guard_removal_falsifier_really_allows_unknown_loader(tmp_path):
    s=setup(tmp_path);fn=node('system_campaign_financial_compound_dispatch.py',ast.FunctionDef,'retained_loader_surfaces')
    call,=[n for n in ast.walk(fn)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='need']
    call.args[0]=ast.Constant(True)
    scope=dict(s.route.__wrapped__.__globals__);run_nodes([fn],scope)
    with pytest.raises(ValueError):
        with s.route((s.module,)):pass
    with scope['retained_loader_surfaces']((s.module,)):assert s.repair.load_repair is s.parser

def test_actual_noncompound_new_December_input_delegates_without_own_object_binding(tmp_path):
    s=setup(tmp_path);p=tmp_path/'December.json';p.write_text(s.data['December_document_raw'],newline='')
    with s.ctx,s.route((s.module,)),s.codec,s.apha:
        doc=json.loads(p.read_bytes());loaded=s.backtest.load_repair(p,resume_session='2021-11-30',predecessor_checkpoint_sha256=doc['predecessor_checkpoint_sha256'])
        packet=SimpleNamespace(day='2021-12-01');assert s.backtest.apply_repair(packet,loaded)is packet
        assert s.ctx.bound_objects==[]

def test_actual_dispatcher_enters_bridge_after_retained_context_before_inner_codecs(tmp_path):
    s=setup(tmp_path);order=[]
    @contextmanager
    def retained(root,cp,out):
        with s.ctx:
            order.append('retained-entered');yield
            order.append('retained-exiting')
    s.module.retained_context=retained
    fn=node('system_campaign_financial_compound_dispatch.py',ast.FunctionDef,'retained_context')
    scope=dict(s.route.__wrapped__.__globals__,ExitStack=ExitStack,versions=lambda:(s.module,),retained_versions=lambda root,cp:(s.module,),retained_loader_surfaces=s.route)
    run_nodes([fn],scope)
    with scope['retained_context'](tmp_path,{},tmp_path):
        assert order==['retained-entered']and s.repair.load_repair==s.ctx.load
        with s.codec,s.apha:
            d=s.data['compound_descriptor'];obj=s.backtest.load_repair(s.compound_path,resume_session=d['resume_session'],predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
            assert obj is s.ctx.bound_objects[-1]
            assert s.backtest.apply_repair(SimpleNamespace(day='2016-04-26'),obj)
    assert order==['retained-entered','retained-exiting']
    assert s.repair.load_repair is s.parser and s.backtest.load_repair is s.parser

@pytest.mark.parametrize('name',['stock_strategy_shared','sentinel','research.pooled_vacancy_funding','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(AssertionError):__import__(name)

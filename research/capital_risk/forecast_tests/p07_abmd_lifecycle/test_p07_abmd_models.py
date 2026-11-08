"""Read-only actual23 sources and noncanonical24-input metadata DTOs."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path,PurePosixPath
from types import FunctionType
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P07_ABMD_MODELS_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(1,'C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
sys.path.insert(2,'C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
import system_campaign_p07_abmd_models as data
import system_campaign_abmd_bounded_catalog as common

class MemberPath:
    def __init__(self,member,name=''):self.member,self.relative=member,name
    def __truediv__(self,name):return MemberPath(self.member,(PurePosixPath(self.relative)/name).as_posix())
    def read_bytes(self):return self.member(self.relative)
    def read_text(self,*args,**kw):return self.read_bytes().decode()
    @property
    def name(self):return PurePosixPath(self.relative).name
    def exists(self):return self.relative in self.member.names

def smart(value):return value if isinstance(value,MemberPath) else Path(value)

@pytest.fixture(scope='module')
def actual():
    from system_campaign_financial_partial import root_spec
    R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
    F=R/'financial306-source-snapshot/capture-P07-13451345162-001';F=Path('\\\\?\\'+str(F.resolve()))
    pins=json.loads((F/'authenticated-manifest.json').read_bytes())['members']
    def member(name):
        raw=(F/'verified-output'/name).read_bytes();assert dict(bytes=len(raw),sha256=data.sha(raw))==pins[name];return raw
    member.names=set(pins)
    catalog=json.loads(Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk/P07-own1238-ABMD-bounded-catalog-v2.json').read_bytes())
    return dict(cp=json.loads(gzip.decompress(member('book/checkpoint.json.gz'))),member=member,catalog=catalog,
                evidence=common.evidence(catalog),metadata=root_spec('P07'))

@pytest.fixture
def virtual(actual,monkeypatch):
    import system_campaign_financial_branches as b
    import system_campaign_zogenix_input as z
    import system_campaign_zogenix_facts as zf
    import system_campaign_uncertainty_facts as uf
    monkeypatch.setattr(data,'Path',smart)
    monkeypatch.setattr(data,'parse',data.bound(data.parse,Path=smart))
    for module,name in ((b,'parse'),(b,'evidence'),(z,'parse'),(zf,'evidence'),(uf,'evidence')):
        monkeypatch.setattr(module,name,data.bound(getattr(module,name),Path=smart))
    return dict(actual,root=MemberPath(actual['member']))

def check(a,cp=None):
    return data.validate_full(a['root'],a['cp'] if cp is None else cp,a['catalog'],a['evidence'],
        input_hash=lambda base,repairs:data.digest(dict(base=base,repairs=repairs)),root_metadata=a['metadata'])

def synthetic24(a):
    # No state, journals, checkpoint schema or financial serialization API exists.
    cp=dict(noncanonical_input_metadata_DTO=True,base=a['metadata']['base'],repairs=deepcopy(a['cp']['repairs']),run={})
    raw=common.encoded(common.document(a['catalog']));h=data.sha(raw)
    cp['repairs'].append(dict(filename=h+'.json',sha256=h,resume_session=a['catalog']['parent_cursor'],
        predecessor_checkpoint_sha256=a['catalog']['parent_inner_sha256']))
    cp['run']['input_sha256']=data.digest(dict(base=cp['base'],repairs=cp['repairs']))
    original=a['member'];name='book/repairs/'+h+'.json'
    def member(key):return raw if key==name else original(key)
    member.names=original.names|{name}
    return dict(a,cp=cp,root=MemberPath(member)),raw

def test_actual_current23_model_origin_and_ordinary_receipt_are_all_checked(virtual):
    result=check(virtual)
    assert result['full_input_count']==23 and result['bounded_descriptor'] is None and len(result['legacy_models'])==1

def test_noncanonical24_metadata_preserves_all23_and_exact_new_typed_object(virtual):
    a,raw=synthetic24(virtual);result=check(a)
    assert result['full_input_count']==24 and result['bounded_descriptor']==a['cp']['repairs'][23]
    assert a['cp']['repairs'][:23]==virtual['cp']['repairs'] and data.sha(raw)==result['bounded_descriptor']['sha256']

@pytest.mark.parametrize('change',['hash','old_descriptor','new_predecessor','new_clock','extra_descriptor','event','evidence'])
def test_wrong_current_epoch_old_origin_or_extra_model_refuses(virtual,change):
    a,_=synthetic24(virtual);cp=deepcopy(a['cp'])
    if change=='hash':cp['run']['input_sha256']='0'*64
    elif change=='old_descriptor':cp['repairs'][0]['sha256']='0'*64
    elif change=='new_predecessor':cp['repairs'][-1]['predecessor_checkpoint_sha256']='0'*64
    elif change=='new_clock':cp['repairs'][-1]['resume_session']='2022-12-21'
    elif change=='extra_descriptor':cp['repairs'].append(deepcopy(cp['repairs'][-1]))
    elif change=='event':a=dict(a,catalog=deepcopy(a['catalog']));a['catalog']['event']['right_upper_per_share']='36.00'
    else:a=dict(a,evidence=deepcopy(a['evidence']));a['evidence'][0]['sha256']='0'*64
    if change not in ('hash','old_descriptor'):cp['run']['input_sha256']=data.digest(dict(base=cp['base'],repairs=cp['repairs']))
    with pytest.raises(ValueError):check(a,cp)

def test_entire_ordinary_receipt_AST_undo_and_dual_hash_semantics():
    raw=Path(data.legacy.__file__).read_bytes();before=data.legacy.original.function(raw,'validated_receipt');after=data.receipt_tree(raw)
    after=data.replace(after,"value['adopted_descriptors'] == cp['repairs'][:23]","value['adopted_descriptors'] == cp['repairs']",'undo1')
    after=data.replace(after,'values[22]','values[-1]','undo2')
    class Undo(ast.NodeTransformer):
        hits=0
        def visit_Call(self,n):
            if isinstance(n.func,ast.Name) and n.func.id=='receipt_input_hashes':
                self.hits+=1;return ast.parse("cp['run']['input_sha256'] == value['adopted_input_sha256'] == input_hash(cp['base'], cp['repairs'])",mode='eval').body
            return self.generic_visit(n)
    undo=Undo();after=undo.visit(after)
    assert undo.hits==1 and ast.dump(after,include_attributes=False)==ast.dump(before,include_attributes=False)
    cp=dict(base={'synthetic':True},repairs=list(range(24)),run={});value=dict(adopted_descriptors=list(range(23)))
    ih=lambda base,repairs:data.digest(dict(base=base,repairs=repairs));cp['run']['input_sha256']=ih(cp['base'],cp['repairs']);value['adopted_input_sha256']=ih(cp['base'],value['adopted_descriptors'])
    assert data.receipt_input_hashes(value,cp,ih) and cp['run']['input_sha256']!=value['adopted_input_sha256']
    value['adopted_input_sha256']=cp['run']['input_sha256'];assert not data.receipt_input_hashes(value,cp,ih)

def test_full_legacy_model_and_B19_visitor_AST_undo():
    raw=Path(data.legacy.original.__file__).read_bytes();before=data.legacy.model_tree(raw);after=data.model_tree(raw)
    guard=next(n for n in ast.walk(after) if isinstance(n,ast.Compare) and ast.unparse(n)=="doc['schema'] in ('terminal-repair/1', *MODELS, BOUNDED_SCHEMA)")
    assert guard.comparators[0].elts.pop().id=='BOUNDED_SCHEMA'
    ns=next(n.value for n in ast.walk(after) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='namespace')
    assert [v.arg for v in ns.keywords[-2:]]==['BOUNDED_SCHEMA','validated_bounded_descriptor'];ns.keywords=ns.keywords[:-2]
    assert ast.dump(after,include_attributes=False)==ast.dump(before,include_attributes=False)
    raw=data.legacy.original.source('system_campaign_financial_branches.py');before=data.legacy.original.function(raw,'validate_input');after=data.branch_tree(raw)
    loop=next(n for n in after.body if isinstance(n,ast.For));skip=next(n for n in loop.body if isinstance(n,ast.If) and ast.unparse(n.test)=='schema == BOUNDED_SCHEMA');loop.body.remove(skip)
    assert ast.dump(after,include_attributes=False)==ast.dump(before,include_attributes=False)

def test_removing_full_current_hash_guard_really_accepts_wrong_epoch(actual):
    cp=deepcopy(actual['cp']);cp['run']['input_sha256']='0'*64
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='typed_descriptor')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value=='P07_ABMD_FULL_CURRENT_INPUT_IDENTITY' for v in n.value.args))
    fn.body.remove(guard);scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-hash-guard-DATA-only>','exec'),scope)
    args=(MemberPath(actual['member']),cp,actual['catalog'],actual['evidence'])
    kw=dict(input_hash=lambda base,repairs:data.digest(dict(base=base,repairs=repairs)),root_metadata=actual['metadata'])
    with pytest.raises(ValueError):data.typed_descriptor(*args,**kw)
    assert scope['typed_descriptor'](*args,**kw) is None

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)

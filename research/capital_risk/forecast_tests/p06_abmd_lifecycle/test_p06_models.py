"""Actual original8 inputs and TRQ document metadata; no neutral book fabricated."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P06_MODELS_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path[:0]=[str(Path(__file__).parent),'C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk']
import system_campaign_p06_abmd_models as data
from system_campaign_abmd_bounded_catalog import encoded
from system_campaign_financial_partial import root_spec

@pytest.fixture(scope='module')
def actual():
    F=Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/financial-runs-20261104-281/capture-P06-13413225228-001')
    F=Path('\\\\?\\'+str(F.resolve()));pins=json.loads((F/'authenticated-manifest.json').read_bytes())['members']
    def member(name):
        raw=(F/'verified-output'/name).read_bytes();assert dict(bytes=len(raw),sha256=data.sha(raw))==pins[name];return raw
    cp=json.loads(gzip.decompress(member('book/checkpoint.json.gz')))
    c=json.loads((Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')/'P06-own1238-ABMD-bounded-catalog-v2.json').read_bytes())
    return cp,c,root_spec('P06','947662b7b86089285e5d7360221ff3a6d931173bccbce6ac8884341d396c763e'),member

def test_actual_all_eight_original_inputs_and_full_hash_qualify_without_staging(actual):
    cp,c,metadata,member=actual
    result=data.history('unused',cp,c,root_metadata=metadata,input_hash=lambda b,r:data.digest(dict(base=b,repairs=r)),member=member)
    assert result==dict(ordinary_descriptor=None,bounded_descriptor=None,full_inputs=8)

@pytest.mark.parametrize('change',['hash','prefix','extra9','extra10','outer','file'])
def test_foreign_or_unproved_added_input_identity_refuses(actual,change):
    cp,c,m,member=actual;cp=deepcopy(cp);original=member;alter=None
    if change=='hash':cp['run']['input_sha256']='0'*64
    elif change=='prefix':cp['repairs']=cp['repairs'][:-1]
    elif change in ('extra9','extra10'):
        cp['repairs']+=[{'sha256':'SYNTHETIC_NOT_A_DESCRIPTOR'}]*(1 if change=='extra9' else 2)
        cp['run']['input_sha256']=data.digest(dict(base=cp['base'],repairs=cp['repairs']))
    elif change=='outer':cp['sha256']='0'*64
    else:alter='book/repairs/'+cp['repairs'][0]['filename']
    def member(name):return original(name)+b' ' if name==alter else original(name)
    with pytest.raises(ValueError):data.history('unused',cp,c,root_metadata=m,input_hash=lambda b,r:data.digest(dict(base=b,repairs=r)),member=member)

def material_input(actual):
    cp,c,m,member=actual;codec,name,terms=data.ordinary.selected('P06',cursor='2022-11-30')
    material=dict(schema=data.ordinary.REFERENCE,arm='P06',catalog=name,catalog_sha256=codec.catalog_sha,
        original_validator_sha256=codec.compiler_sha,selector_sha256=data.FUTURE_SHA,parent_outer_sha256=cp['sha256'],
        terms=terms,cil_convention=None,native_and_delivery_witnesses_verified=1,consumed_native_preserved=[],
        financial_source_changed=False,provider_metadata_upgraded=False,original_validator_description=codec.validator_description)
    raw=encoded(material);doc=data.ordinary.document(cp,material,data.sha(raw));overlay=encoded(doc);descriptor=dict(sha256=data.sha(overlay),filename=data.sha(overlay)+'.json')
    values={data.ordinary.hydration_name(cp):raw,'book/repairs/'+descriptor['filename']:overlay}
    return cp,material,descriptor,values

def test_exact_TRQ_research_normalization_and_whole_document_reconstruct_without_adoption(actual):
    cp,material,descriptor,values=material_input(actual)
    doc,checked=data.ordinary_material('unused',cp,descriptor,values.__getitem__)
    assert checked==material and doc['add'][0]['cash_per_share']==31.575855485386988
    assert len(doc['suppress'])==len(doc['add'])==1
    assert material['terms'][0]['research_assumption']['schema']=='research.daily-normalized-usd-cash-assumption/1'

@pytest.mark.parametrize('change',['rounded_amount','source_clock','catalog','selector','held_quantity'])
def test_TRQ_terms_cannot_be_rounded_rebound_or_given_another_parent_role(actual,change):
    cp,material,descriptor,values=material_input(actual);material=deepcopy(material)
    if change=='rounded_amount':material['terms'][0]['added']['cash_per_share']=31.5
    elif change=='source_clock':material['terms'][0]['source_capture']['run_id']-=1
    elif change=='catalog':material['catalog_sha256']='0'*64
    elif change=='selector':material['selector_sha256']='0'*64
    else:material['terms'][0]['parent_positions'][0]['quantity']=81
    raw=encoded(material);overlay=encoded(data.ordinary.document(cp,material,data.sha(raw)))
    descriptor=dict(sha256=data.sha(overlay),filename=data.sha(overlay)+'.json')
    values={data.ordinary.hydration_name(cp):raw,'book/repairs/'+descriptor['filename']:overlay}
    with pytest.raises(ValueError):data.ordinary_material('unused',cp,descriptor,values.__getitem__)

def test_hosted_visitor_refuses_before_financial_import(monkeypatch):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):data.validate_full(None,{}, {})

def test_removing_full_input_guard_accepts_wrong_hash_and_is_detected(actual):
    cp,c,m,member=actual;cp=deepcopy(cp);cp['run']['input_sha256']='0'*64
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='history')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,n):
            if isinstance(n.value,ast.Call) and any(isinstance(x,ast.Constant) and x.value=='P06_MODELS_FULL_ACTUAL_EIGHT_PREFIX_AND_CANONICAL_HASH' for x in n.value.args):self.hits+=1;return None
            return self.generic_visit(n)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-input-guard-DATA-only>','exec'),scope)
    kwargs=dict(root_metadata=m,input_hash=lambda b,r:data.digest(dict(base=b,repairs=r)),member=member)
    with pytest.raises(ValueError):data.history('unused',cp,c,**kwargs)
    assert scope['history']('unused',cp,c,**kwargs)['full_inputs']==8

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)

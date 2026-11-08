"""Actual24 readers, metadata DTO refusals and whole-source undo; no replay."""
import ast,gzip,hashlib,importlib,sys
from copy import deepcopy
from pathlib import Path
import pytest

C=Path(__file__).resolve().parents[2]
P=C
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('VIVO25_METADATA_TEST_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path[:0]=[str(P),str(C)]
import system_campaign_p07_vivo_data as data
import system_campaign_p07_vivo_api as api
import system_campaign_p07_vivo_models as models
import system_campaign_p07_vivo_boundary as boundary
from system_campaign_financial_partial import root_spec
import json

def read(path):
    path=str(Path(path).resolve())
    return Path(path if path.startswith('\\\\?\\') else '\\\\?\\'+path).read_bytes()

@pytest.fixture(scope='module')
def actual():
    old=R/'financial326-source-snapshot/capture-P07-13480122074-001/verified-output'
    cp=json.loads(gzip.decompress(read(old/'book/checkpoint.json.gz')))
    return old,cp,root_spec('P07',data.ROOT)

def test_actual_full24_parent805_and23_term_batch(actual):
    old,cp,spec=actual
    assert data.parent_contract(cp,spec)
    catalog=data.catalog();assert len(catalog['terms'])==23
    assert catalog['selected_source_indices']==[12,15,25,27,30,48,51,66,68,69,71,72,80,84,85,87,88,93,94,104,116,118,125]
    v,=[t for t in catalog['terms'] if t['security_id']==data.SID]
    assert v['parent_positions']==[dict(slot_id=1,ticker='VIVO1',quantity=84,entry_date='2022-07-11')]
    sgfy,=[t for t in catalog['terms'] if t['ticker']=='SGFY']
    assert sgfy['parent_positions']==[dict(slot_id=5,ticker='SGFY',quantity=103,entry_date='2022-11-07')]
    assert v['identity_witness']['issuer_id']=='SEC_UNKNOWN:'+data.SID and v['identity_witness']['security_type_eligible']=='0'

@pytest.mark.parametrize('mutation',range(24))
def test_catalog_metadata_refusals(mutation):
    c=deepcopy(data.catalog());v,=[t for t in c['terms'] if t['security_id']==data.SID]
    if mutation==0:c['arm']='P06'
    elif mutation==1:c['parent_cursor']='2023-01-30'
    elif mutation==2:c['parent_root_admission_sha256']='0'*64
    elif mutation==3:c['loader_sha256']='0'*64
    elif mutation==4:c['canonical_financial_source_changed']=True
    elif mutation==5:c['provider_metadata_upgraded']=True
    elif mutation==6:c['selected_source_indices'].reverse()
    elif mutation==7:c['terms'].pop()
    elif mutation==8:v['added']['cash_per_share']=35.0;v['primary_extraction']['cash_per_share']='35.00'
    elif mutation==9:v['identity_witness']['issuer_id']='SEC_CIK:794172'
    elif mutation==10:v['identity_witness']['security_type_eligible']='1'
    elif mutation==11:v['parent_positions'][0]['quantity']=83
    elif mutation==12:v['native']['cash_per_share']=34.0
    elif mutation==13:v['source_capture']['artifact_id']=13517523263
    elif mutation==14:v['added']['session']='2023-01-30'
    elif mutation==15:v['recognition_rule']='RESEARCH_COMPLETION_DATE_OPEN_AVAILABILITY'
    elif mutation==16:v['preopen_completion_confirmed']=False
    elif mutation==17:v['primary_extraction']['qualified_common_cash_fact_sha256']='0'*64
    elif mutation==18:v['primary_extraction']['no_stock_or_contingent_rights_in_common_consideration']=False
    elif mutation==19:v['added']['exchange_ratio']=1.0
    elif mutation==20:c['source_data']['qualification']['financial_authority']=True
    elif mutation==21:c['terms'][1]['timing_source']='https://example.invalid'
    elif mutation==22:c['terms'][1]['added']['cash_per_share']=0.01
    else:c['terms'][1]['retained_qualified_legal_term']['term_sha256']='0'*64
    with pytest.raises((ValueError,KeyError,AssertionError)):data.validate(c)

def test_meaningful_new_common34_guard_removal(monkeypatch):
    c=deepcopy(data.catalog());v,=[t for t in c['terms'] if t['security_id']==data.SID]
    v['added']['cash_per_share']=35.0;v['primary_extraction']['cash_per_share']='35.00'
    with pytest.raises(ValueError,match='VIVO_ONE_GENUINE_HELD84_COMMON34_INPUT'):data.validate(c)
    old=data.need
    def without(value,label):
        if label!='VIVO_ONE_GENUINE_HELD84_COMMON34_INPUT_NO_IDENTITY_OR_RIGHTS_UPGRADE':old(value,label)
    monkeypatch.setattr(data,'need',without)
    assert data.validate(c)

def test_meaningful_complete23_guard_removal(monkeypatch):
    c=deepcopy(data.catalog());c['terms'].pop();c['selected_source_indices'].pop()
    with pytest.raises(ValueError,match='VIVO_EXACT_ONE_NEW_AND22'):data.validate(c)
    old=data.need
    def without(value,label):
        if label!='VIVO_EXACT_ONE_NEW_AND22_ORIGINAL_LEGAL_TERMS_IN_SINGLE_ORDINARY_INPUT':old(value,label)
    monkeypatch.setattr(data,'need',without)
    assert data.validate(c)

def functions(raw):return {n.name:n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)}

def test_whole_original_cash_source_binding_AST_undo():
    raw=Path(data.cash.__file__).read_bytes();old=functions(raw)['source_binding'];new=data.source_tree(raw)
    imp=next(n for n in old.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_future')
    new.body.insert(old.body.index(imp),deepcopy(imp))
    for n in ast.walk(new):
        if isinstance(n,ast.Constant) and n.value=='research.independent-forward-source-DATA-validation/2':n.value='research.independent-frozen-source-data-validation/1'
    assert ast.dump(new)==ast.dump(old)

def test_whole_original_primary_amount_date_extraction_AST():
    old=functions(Path(data.cash.__file__).read_bytes())['validate'];loop,=[n for n in old.body if isinstance(n,ast.For)]
    index,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='extraction']
    assert [ast.dump(n) for n in data.original_primary_tree().body]==[ast.dump(n) for n in loop.body[index:index+2]]

def test_all_original_model_functions_whole_AST_undo():
    raw=Path(models.original.__file__).read_bytes();old=functions(raw);new={n.name:n for n in models.model_tree(raw).body}
    for name,fn in new.items():
        if name in ('typed_descriptor','receipt_reader'):
            models.replace_count(fn,'(23, 24, 25)','(23, 24)',1,'TEST_ONE_TUPLE_UNDO')
        if name=='typed_descriptor':
            fn.body=[n for n in fn.body if not (isinstance(n,ast.If) and ast.unparse(n.test)=="len(cp['repairs']) == 25")]
        assert ast.dump(fn)==ast.dump(old[name]),name

def test_all_original_ABMD_origin_functions_whole_AST_undo():
    raw=Path(models.origin_original.__file__).read_bytes();old=functions(raw);new={n.name:n for n in models.origin_tree(raw).body}
    for name,fn in new.items():
        if name=='validate':
            models.replace_count(fn,"current['repairs'][:24] == adopted['repairs']","current['repairs'] == adopted['repairs']",1,'TEST_PREFIX_UNDO')
            models.replace_count(fn,"len(current['repairs']) in (24, 25)","len(current['repairs']) == 24",1,'TEST_COUNT_UNDO')
            models.replace_count(fn,"adopted['run']['input_sha256'] == input_hash(adopted['base'], adopted['repairs']) and current['run']['input_sha256'] == input_hash(current['base'], current['repairs'])",
                "current['run']['input_sha256'] == adopted['run']['input_sha256'] == input_hash(current['base'], current['repairs'])",1,'TEST_HASH_UNDO')
            fn.body=[n for n in fn.body if not (isinstance(n,ast.If) and ast.unparse(n.test)=="len(current['repairs']) == 25")]
        assert ast.dump(fn)==ast.dump(old[name]),name

def test_actual24_typed_ABMD_and_original_models_metadata_reader(actual):
    old,cp,spec=actual
    from system_campaign_abmd_bounded_catalog import evidence
    old=Path('\\\\?\\'+str(old.resolve()))
    c=api.lifecycle.catalog();m=models.models()
    result=m.validate_full(old,cp,c,evidence(c),input_hash=lambda b,r:data.digest(dict(base=b,repairs=r)),root_metadata=api.lifecycle.initial_spec())
    assert result['full_input_count']==24 and result['bounded_descriptor']==cp['repairs'][23] and len(result['legacy_models'])==1

def test_whole_original_API_code_objects_and_safe_local_fence(actual):
    old,cp,spec=actual;bound=api.api(cp,spec)
    for name in api.FUNCTIONS:
        fn=getattr(bound,name);fn=getattr(fn,'__wrapped__',fn)
        assert fn.__code__ is getattr(api.original,name).__code__
    with pytest.raises(ValueError,match='HOSTED'):bound.hydrate(cp,'P07',source_root=old)

@pytest.mark.parametrize('prefix',['research.pooled_forbidden','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)

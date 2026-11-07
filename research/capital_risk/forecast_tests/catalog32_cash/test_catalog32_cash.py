"""Inactive input-only catalog qualification; canonical finance imports forbidden."""
import ast
from copy import deepcopy
import json,os
from pathlib import Path
import sys
import pytest
Q=Path(__file__).parent;C=Path(os.environ.get('QUALIFIED_CATALOG32_TEST_SOURCE_DIR',str(Q.parents[1])))
sys.path.insert(0,str(C))
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas')):raise ImportError('CATALOG32_INPUT_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
import system_campaign_financial_future as f

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    catalog=json.loads((C/f.OWN_CASH_CATALOG).read_bytes())
    catalog['terms']=catalog['terms'][:32]
    historical=(json.dumps(catalog,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    assert f.sha(historical)=='3640674e7049db653200c8c888e70fe9f645b6dfba7110b49295a0645f318304'
    assert catalog['terms'][-1]==json.loads((Q/'fixtures/TERN-source282-catalog32-record.json').read_bytes())
    (tmp_path/f.OWN_CASH_CATALOG).write_bytes(historical)
    monkeypatch.setattr(f,'OWN_CASH_SHA',f.sha(historical))
    monkeypatch.setattr(f,'CLOSED_CASH_GENERATIONS',{k:v for k,v in f.CLOSED_CASH_GENERATIONS.items()if v<32})
    names={t[field][key]for t in catalog['terms']for field,key in(('retained_primary_catalog','filename'),('retained_original_legal_record','catalog_file'))if field in t}
    for name in names:(tmp_path/name).write_bytes((C/name).read_bytes())
    monkeypatch.setattr(f,'HERE',tmp_path)
    return catalog,tmp_path

def selected():return f.own_cash_selection('P11','2026-04-30')
def write(catalog,path,*,repin=False,monkeypatch=None):
    raw=(json.dumps(catalog,sort_keys=True,indent=2,allow_nan=False)+'\n').encode();(path/f.OWN_CASH_CATALOG).write_bytes(raw)
    if repin:monkeypatch.setattr(f,'OWN_CASH_SHA',f.sha(raw))

def test_new_term_exact_source_root_primary_and_original_validator(prepared):
    codec,name,terms=selected();term,=terms
    assert name==f.OWN_CASH_CATALOG and len(codec.catalog['terms'])==32
    assert codec.catalog_sha=='3640674e7049db653200c8c888e70fe9f645b6dfba7110b49295a0645f318304'
    assert codec.compiler_sha=='183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f'
    assert term['ticker']=='TERN'and term['added']['cash_per_share']==53. and term['added']['session']=='2026-05-05'
    assert term['native_session']==term['last_trading_session']=='2026-05-04'and term['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION'
    assert term['parent_positions']==[dict(slot_id=19,ticker='TERN',quantity=157,entry_date='2026-04-29')]
    assert term['source_capture']['payload_sha256']=='e925c5e196e853784f870342c86ec831f9a85014749bcc6e5a4bccdbb608c673'
    assert all(term['primary_extraction'][k]is False for k in('updated_alert_publication_time_observed','exact_legal_effective_minute_observed','actual_cash_payment_or_settlement_observed','actual_opening_cash_availability_proved'))

def test_original31_generation_and_every_previous_generation_stay_exact(prepared):
    codec,_,_=f.own_cash_selection('P06','2022-04-29')
    assert len(codec.catalog['terms'])==31 and codec.catalog_sha=='7e497c722993513994326293e7703abb54161ed952ed0b99e3d8043a51475c9b'
    assert f.sha((json.dumps(codec.catalog,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())=='7e497c722993513994326293e7703abb54161ed952ed0b99e3d8043a51475c9b'

@pytest.mark.parametrize('kind',['source_clock','source_scope','root','quantity','identity_day','native_hash'])
def test_foreign_source_root_role_and_native_rejected(prepared,monkeypatch,kind):
    catalog,path=prepared;t=catalog['terms'][-1]
    if kind=='source_clock':t['source_capture']['artifact_id']+=1
    elif kind=='source_scope':t['source_capture']['scope_sha256']='0'*64
    elif kind=='root':t['parent_outer_sha256']='0'*64
    elif kind=='quantity':t['parent_positions'][0]['quantity']=158
    elif kind=='identity_day':t['identity_witness']['session']='2026-05-04'
    else:t['native_term_sha256']='0'*64
    write(catalog,path,repin=True,monkeypatch=monkeypatch)
    with pytest.raises(ValueError):selected()

@pytest.mark.parametrize('kind',['cash','preopen','completion','ratio','lasttrade'])
def test_unchanged_original_cash_validator_rejects_bad_terms(prepared,kind):
    from system_campaign_cash_calendar import validate_term
    t=deepcopy(selected()[2][0])
    if kind=='cash':t['added']['cash_per_share']=0.
    elif kind=='preopen':t['preopen_completion_confirmed']=False
    elif kind=='completion':t['actual_completion_date']='2026-05-06'
    elif kind=='ratio':t['added']['exchange_ratio']=1.
    else:t['last_trading_session']='2026-05-05'
    with pytest.raises(ValueError):validate_term(t)

def remove_guard(label):
    fn=next(n for n in ast.parse((C/'system_campaign_financial_future.py').read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name=='own_cash_selection')
    node=next(n for n in ast.walk(fn)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='need'and len(n.args)==2 and isinstance(n.args[1],ast.Constant)and n.args[1].value==label)
    node.args[0]=ast.Constant(True);ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<single-removed-input-guard>','exec'),ns)
    return ns['own_cash_selection']

def test_literal_guard_removal_really_accepts_changed_payload(prepared):
    catalog,path=prepared;catalog['terms'][-1]['source_capture']['payload_sha256']='0'*64;write(catalog,path)
    with pytest.raises(ValueError,match='EXACT_REVIEWED_LITERAL'):selected()
    assert remove_guard('OWN_CASH_EXACT_REVIEWED_LITERAL_CATALOG')('P11','2026-04-30')[2][0]['source_capture']['payload_sha256']=='0'*64

def test_original31_guard_removal_really_accepts_rewritten_prior_term(prepared,monkeypatch):
    catalog,path=prepared;t=next(t for t in catalog['terms']if(t['arm'],t['parent_cursor'])==('P11','2026-02-27'))
    t['description']+=' retained note';t['added']['reference']=t['primary_source']+' | '+t['description'];write(catalog,path,repin=True,monkeypatch=monkeypatch)
    with pytest.raises(ValueError,match='CLOSED_CATALOG_GENERATION'):selected()
    assert remove_guard('OWN_CASH_CLOSED_CATALOG_GENERATION_BYTES')('P11','2026-04-30')[2][0]['ticker']=='TERN'

def test_ordinary_document_has_only_exact_native_and_cash_term(prepared):
    codec,_,terms=selected();t,=terms
    cp=dict(source_cursor='2026-04-30',run=dict(checkpoint_sha256='a'*64))
    material=dict(terms=terms,catalog_sha256=codec.catalog_sha,original_validator_sha256=codec.compiler_sha,selector_sha256='b'*64,original_validator_description=codec.validator_description)
    doc=f.document(cp,material,'c'*64)
    assert doc['add']==[t['added']]and doc['suppress']==[dict(session='2026-05-04',security_id=t['security_id'],term_sha256=t['native_term_sha256'])]
    hashes={v['sha256']for v in doc['source_evidence']}
    assert t['source_capture']['payload_sha256']in hashes and t['source_capture']['independent_data_review_sha256']in hashes

@pytest.mark.parametrize('name',['stock_strategy_shared','sentinel','research.pooled_vacancy_funding','numpy','pandas'])
def test_no_canonical_financial_import(name):
    with pytest.raises(ImportError):Fence().find_spec(name)

def test_actual_original_nonempty_Repair_and_loaded_identity(prepared):
    """Original Repair/_loaded AST with input-field models; no financial engine."""
    from pydantic import BaseModel,ConfigDict,Field,PrivateAttr,model_validator
    from typing import Literal
    import hashlib
    source=(C/'forecast_tests/standard_distribution/fixtures/pure-original-nonempty-input-codec.json').read_bytes()
    assert f.sha(source)=='fb5b4da4b84afcc9985000723efcee5b4ab2e9884e8bebbca4f0c670d487533e'
    fixture=json.loads(source)
    assert fixture['original_module_sha256']=='1112f91ab01c6b633fd6e7b2c089aa02367d2fc7fbc152a654da6620d753b152'
    class Strict(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)
    class Evidence(Strict):
        reference:str;description:str;sha256:str|None=None
    class Suppression(Strict):
        session:str;security_id:str;term_sha256:str
    class Added(BaseModel):
        model_config=ConfigDict(extra='allow',strict=True)
        session:str;security_id:str
    ns=dict(__name__=__name__,_Strict=Strict,Literal=Literal,Field=Field,PrivateAttr=PrivateAttr,model_validator=model_validator,
        Digest=str,SourceEvidence=Evidence,Suppression=Suppression,AddedTerm=Added,json=json,hashlib=hashlib)
    for name in ('_digest','Repair','_loaded'):
        item=fixture['functions'][name]
        assert f.sha(item['source'].encode())==item['source_sha256']
        node=ast.parse(item['source']).body[0]
        assert f.sha(ast.dump(node,include_attributes=False).encode())==item['ast_sha256']
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<unchanged-original-pure-input-codec>','exec'),ns)
    cls=ns['Repair'];cls.model_rebuild(_types_namespace=ns)
    codec,_,terms=selected();cp=dict(source_cursor='2026-04-30',run=dict(checkpoint_sha256='a'*64))
    doc=f.document(cp,dict(terms=terms,catalog_sha256=codec.catalog_sha,original_validator_sha256=codec.compiler_sha,selector_sha256='b'*64,original_validator_description=codec.validator_description),'c'*64)
    loaded=cls.model_validate(doc);assert loaded.earliest_affected_session=='2026-05-04'
    loaded._file_sha256=f.sha((json.dumps(doc,sort_keys=True,indent=2)+'\n').encode())
    loaded._resume_session='2026-04-30';loaded._document_sha256=ns['_digest'](loaded.model_dump(mode='json',by_alias=True))
    ns['_loaded'](loaded)
    empty=dict(doc,suppress=[],add=[])
    with pytest.raises(ValueError,match='empty terminal repair'):cls.model_validate(empty)
    with pytest.raises(ValueError,match='duplicate terminal repair identity'):cls.model_validate(dict(doc,add=doc['add']*2))
    loaded.add[0].session='2026-05-06'
    with pytest.raises(ValueError,match='unchanged source-bound'):ns['_loaded'](loaded)

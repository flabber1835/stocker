"""New primary cash evidence and unchanged original guards; DATA only."""
import ast
from copy import deepcopy
import importlib,json
from pathlib import Path
import sys
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('EXPLICIT_CASH_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_qualified_explicit_cash as data
CATALOG=Path(data.__file__).parent/'system-campaign-p05-own1111-msp-explicit-cash-input-v3.json'

def catalog():return json.loads(CATALOG.read_bytes())

def repin(v):
    payload,review,q=(v['source_data'][k] for k in ('payload','review','qualification'))
    review['payload_sha256']=data.sha(data.encoded(payload));review['scope_sha256']=payload['scope_sha256']=data.digest(payload['scope'])
    q['payload_sha256']=review['payload_sha256'];q['review_sha256']=data.sha(data.encoded(review))
    for term in v['terms']:
        term['source_capture'].update(payload_sha256=review['payload_sha256'],scope_sha256=review['scope_sha256'],
            independent_data_review_sha256=data.sha(data.encoded(review)),independent_qualification_sha256=data.sha(data.encoded(q)))

def test_actual_source2_with_additional_row_and_separate_new_primary_cash_passes():
    v=catalog();before=deepcopy(v)
    assert data.validate(v) and v==before
    obj=data.QualifiedExplicitCash(CATALOG)
    assert obj.catalog==v and obj.catalog_sha==data.sha(CATALOG.read_bytes())
    assert v['source_data']['payload']['schema']=='research.own-parent-frozen-source-witnesses/2'
    assert len(v['source_data']['payload']['additional_rows'])==1 and v['terms'][0]['added']['cash_per_share']==35.50
    assert v['terms'][0]['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION'

@pytest.mark.parametrize('change',['source_schema','missing_extra','extra_price','extra_identity','scope','root','primary_price',
 'primary_source','primary_day','preopen','native_cash','native_hash','held_role','cash_only','q_authority','review_authority','replay','input_adopted'])
def test_semantic_mutations_refuse_even_with_updated_data_digests(change):
    v=catalog();p=v['source_data']['payload'];r=v['source_data']['review'];q=v['source_data']['qualification'];t=v['terms'][0]
    if change=='source_schema':p['schema']='research.own-parent-frozen-source-witnesses/1'
    elif change=='missing_extra':p['additional_rows']=[];r['additional_rows']=[]
    elif change=='extra_price':
        p['additional_rows'][0]['source_row']['raw_close']='1';r['additional_rows']=deepcopy(p['additional_rows'])
    elif change=='extra_identity':
        p['additional_rows'][0]['identity_witness']['issuer_id']='WRONG';r['additional_rows']=deepcopy(p['additional_rows'])
    elif change=='scope':p['scope']['foreign_scope']=True
    elif change=='root':v['parent_root_admission_sha256']='0'*64
    elif change=='primary_price':t['added']['cash_per_share']=36.;t['primary_extraction']['cash_per_share']='36.00'
    elif change=='primary_source':t['primary_source']='https://example.invalid/';t['primary_extraction']['source']=t['primary_source'];t['added']['reference']=t['primary_source']+' | '+t['description']
    elif change=='primary_day':t['actual_completion_date']=t['added']['session']='2022-06-24';t['primary_extraction']['completion_date']='2022-06-24'
    elif change=='preopen':t['preopen_completion_confirmed']=t['primary_extraction']['preopen_completion_confirmed']=False
    elif change=='native_cash':t['native']['cash_per_share']=35.5
    elif change=='native_hash':t['native_term_sha256']='0'*64
    elif change=='held_role':t['parent_positions']=[dict(quantity=1)]
    elif change=='cash_only':t['primary_extraction']['no_stock_or_contingent_rights_in_common_consideration']=False
    elif change=='q_authority':q['financial_authority']=True
    elif change=='review_authority':r['source_value_or_settlement_timing_qualified']=True
    elif change=='replay':p['financial_sessions_advanced']=False
    else:p['input_adopted']=True
    repin(v)
    with pytest.raises((ValueError,KeyError)):data.validate(v)

def test_original_validate_and_dictionary_constructor_code_objects_are_preserved():
    assert data.QualifiedExplicitCash._dict_init.__code__ is data.original.QualifiedCashBatch.__init__.__code__
    original_binding=data.original.source_binding;data.validate(catalog())
    assert data.original.source_binding is original_binding
    assert data.sha(Path(data.original.__file__).read_bytes())==data.ORIGINAL_SHA

def test_undo_exact_source_version_sites_restores_whole_original_source_binding_AST():
    fn=data.source_binding_tree()
    fn.body.insert(0,ast.ImportFrom(module='system_campaign_financial_future',names=[ast.alias(name='registered_scope')],level=0))
    class Undo(ast.NodeTransformer):
        schemas=rows=0
        def visit_Constant(self,node):
            if node.value=='research.own-parent-frozen-source-witnesses/2':self.schemas+=1;return ast.copy_location(ast.Constant('research.own-parent-frozen-source-witnesses/1'),node)
            return node
        def visit_Call(self,node):
            if isinstance(node.func,ast.Name) and node.func.id=='additional_rows_match':
                self.rows+=1;return ast.copy_location(ast.parse("payload.get('additional_rows', []) == review['additional_rows'] == []",mode='eval').body,node)
            return self.generic_visit(node)
    undo=Undo();fn=undo.visit(fn);assert undo.schemas==undo.rows==1
    old=next(n for n in ast.parse(data.original_source()).body if isinstance(n,ast.FunctionDef) and n.name=='source_binding')
    assert ast.dump(fn,include_attributes=False)==ast.dump(old,include_attributes=False)

def remove_binding_guard(label):
    fn=data.source_binding_tree()
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value==label for v in node.value.args):self.hits+=1;return None
            return self.generic_visit(node)
    adapter=Remove();fn=ast.fix_missing_locations(adapter.visit(fn));assert adapter.hits==1
    return fn

@pytest.mark.parametrize('label,change',[('CASH_BATCH_EXACT_CLOSED_SOURCE_DATA','scope'),('CASH_BATCH_SOURCE_IDENTITY_GRANTS_NO_FINANCIAL_AUTHORITY','authority')])
def test_removing_source_guard_really_admits_corresponding_unqualified_data(label,change,monkeypatch):
    v=catalog()
    if change=='scope':v['source_data']['payload']['scope']['unqualified_scope']=True
    else:v['source_data']['qualification']['financial_authority']=True
    repin(v)
    with pytest.raises(ValueError):data.validate(v)
    tree=remove_binding_guard(label);monkeypatch.setattr(data,'source_binding_tree',lambda:tree)
    assert data.validate(v)

def test_removing_new_primary_guard_would_upgrade_cash_without_the_qualified_primary_extraction():
    v=catalog();v['terms'][0]['primary_extraction']['no_stock_or_contingent_rights_in_common_consideration']=False
    with pytest.raises(ValueError,match='NEW_PRIMARY_FACT_NOT_UNHELD_RECORD_UPGRADE'):data.validate(v)
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate_primary')
    fn.body=[n for n in fn.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='EXPLICIT_CASH_NEW_PRIMARY_FACT_NOT_UNHELD_RECORD_UPGRADE' for v in n.value.args))]
    scope=dict(vars(data));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-new-primary-guard>','exec'),scope)
    assert scope['validate_primary'](v)

def test_noncanonical_path_json_is_refused_without_rewriting_it(tmp_path):
    p=tmp_path/'input.json';raw=CATALOG.read_bytes()+b' ';p.write_bytes(raw)
    with pytest.raises(ValueError,match='EXACT_CANONICAL_INPUT_CATALOG_BYTES'):data.QualifiedExplicitCash(p)
    assert p.read_bytes()==raw

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_runtime_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)

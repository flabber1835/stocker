"""Source metadata only; no canonical replay/restore or probability choice."""
import ast
from copy import deepcopy
import importlib,json
from pathlib import Path
import sys
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('EXPLICIT_SOURCE_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import system_campaign_explicit_source_queries as data
from system_campaign_financial_partial import root_spec

def actual():return json.loads((data.HERE/data.CATALOG).read_bytes())

def test_actual_scope_has_one_native_and_last_trading_day_without_financial_authority():
    original_root=lambda arm:root_spec(arm,'475af771e38bc5bb9600bdf0031fbb1036304a5e36348dc82cf8fbac4497098d')
    scope=data.selected_scopes({},['P07'],enabled=True,root_lookup=original_root)['P07']
    assert scope['parent_cursor']=='2022-11-30' and len(scope['terms'])==len(scope['additional_rows'])==1
    assert scope['terms'][0]['session']=='2022-12-20' and scope['terms'][0]['native_session']=='2022-12-21'
    assert scope['additional_rows'][0]['session']=='2022-12-21'
    assert scope['terms'][0]['parent_positions']==[]

def test_financial_mode_and_unselected_arm_keep_original_scopes_unchanged():
    old={'P07':{'original':True}}
    assert data.selected_scopes(old,['P07'],enabled=False,root_lookup=lambda arm:(_ for _ in ()).throw(AssertionError()))==old
    assert data.selected_scopes(old,['P09'],enabled=True,root_lookup=lambda arm:(_ for _ in ()).throw(AssertionError()))==old
    assert old=={'P07':{'original':True}}

def test_historical_root_keeps_its_original_scope():
    old={'P07':{'historical':True}}
    lookup=lambda arm:root_spec(arm,'75e0e1cfee3007e1ff47a638e62597ed49820c1ecc8a7c1cfc7675c9db800719')
    assert data.selected_scopes(old,['P07'],enabled=True,root_lookup=lookup)==old

@pytest.mark.parametrize('change',['authority','bool_authority','adoption','duplicate','duplicate_sid','bad_day','consumed',
 'held','native_hash','additional_hash','foreign_sid','extra_field'])
def test_malformed_or_financial_source_metadata_refuses(change):
    v=actual();q=v['queries'][0];t=q['scope']['terms'][0];a=q['scope']['additional_rows'][0]
    if change=='authority':v['financial_authority']=True
    elif change=='bool_authority':v['financial_authority']=0
    elif change=='adoption':v['input_adopted']=True
    elif change=='duplicate':v['queries'].append(deepcopy(q))
    elif change=='duplicate_sid':q['scope']['terms'].append(deepcopy(t))
    elif change=='bad_day':t['session']='2022-02-31'
    elif change=='consumed':t['native_session']=q['scope']['parent_cursor']
    elif change=='held':t['parent_positions']=[dict(quantity=1)]
    elif change=='native_hash':t['native_term_sha256']='wrong'
    elif change=='additional_hash':a['source_observation_sha256']='wrong'
    elif change=='foreign_sid':a['security_id']='1'
    else:t['financial_cash']=380
    with pytest.raises(ValueError):data.Registry.model_validate(v)

def test_catalog_byte_change_refuses(tmp_path,monkeypatch):
    (tmp_path/data.CATALOG).write_bytes((data.HERE/data.CATALOG).read_bytes()+b' ');monkeypatch.setattr(data,'HERE',tmp_path)
    with pytest.raises(ValueError,match='EXACT_DECLARED_QUERY_CATALOG_BYTES'):data.registry()

def test_current_axis_guard_removal_really_accepts_foreign_outer():
    root=root_spec('P07','475af771e38bc5bb9600bdf0031fbb1036304a5e36348dc82cf8fbac4497098d');root['outer_sha256']='0'*64;lookup=lambda arm:root
    with pytest.raises(ValueError,match='EXACT_CURRENT_OWN_ROOT_AXIS_AND_AUTHORITY'):
        data.selected_scopes({},['P07'],enabled=True,root_lookup=lookup)
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='selected_scopes')
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value=='EXACT_CURRENT_OWN_ROOT_AXIS_AND_AUTHORITY' for v in node.value.args):
                self.count+=1;return None
            return self.generic_visit(node)
    adapter=Remove();tree=ast.fix_missing_locations(adapter.visit(ast.Module(body=[fn],type_ignores=[])));assert adapter.count==1
    scope=dict(vars(data));exec(compile(tree,'<removed-exact-own-root-source-guard>','exec'),scope)
    assert scope['selected_scopes']({},['P07'],enabled=True,root_lookup=lookup)['P07']['parent_outer_sha256']!='0'*64

def test_source_query_selection_keeps_all_four_existing_worker_bodies_unchanged():
    import system_campaign_financial_resume as resume
    functions={n.name:n for n in ast.parse(Path(resume.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef)}
    expected={
        'preflight':'fa2f6f19d53137596c3cc96575f19e610c32bd93bdade3dc55a48c764e1ce2b2',
        'economic':'cb10dbe24ce57173da398097a359f5b3418c30c68618375db6e22a269e8250f9',
        'review':'1306cc4b8378c3c48332fbfd625fc6d36306f1211f4032bc394f609eddc5a734',
        'launch':'9e6c1f8b7841c58f7e4972299bc928d170c906e0b2a44d98ceb5b9872d387b94'}
    assert {name:data.sha(ast.dump(functions[name],include_attributes=False).encode()) for name in expected}==expected

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
    with pytest.raises(ImportError):importlib.import_module(name)

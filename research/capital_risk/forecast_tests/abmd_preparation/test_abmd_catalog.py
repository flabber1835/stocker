"""Full actual source generations and absent-quote evidence; DATA only."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('ABMD_SHARED_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_abmd_bounded_catalog as data
from system_campaign_financial_partial import root_spec

@pytest.fixture(scope='module',params=['P06','P07'])
def actual(request):return json.loads((Path(__file__).resolve().parents[2]/(request.param+'-own1238-ABMD-bounded-catalog-v2.json')).read_bytes())

def test_actual_full_source_schemas_and_missing_event_quote_remain_distinct(actual):
    result=data.validate(actual,root_lookup=root_spec)
    assert result['market_source']['source_quote_present'] is False and result['market_source']['raw_event_row'] is None
    assert result['event']['prior_session']==result['event']['native_session']=='2022-12-21'
    assert len(result['parent_descriptors'])==data.CASES[result['arm']]['inputs']
    assert result['source_data']['payload']['schema']==data.CASES[result['arm']]['source_schema']
    assert len(data.evidence(result))==8

@pytest.mark.parametrize('change',['root','descriptor','cursor','native','position','schema','source_row','primary','prep','quote',
    'prior_row','split','legal','authority','runtime_pin'])
def test_foreign_current_root_source_legal_or_absence_fact_refuses(actual,change):
    c=deepcopy(actual)
    if change=='root':c['parent_root_admission_sha256']='0'*64
    elif change=='descriptor':c['parent_descriptors']=c['parent_descriptors'][:-1]
    elif change=='cursor':c['parent_cursor']='2022-12-21'
    elif change=='native':c['native']['cash_per_share']=380.
    elif change=='position':c['source_data']['payload']['terms'][0]['parent_positions']=[dict(quantity=1)]
    elif change=='schema':c['source_data']['payload']['schema']='research.own-parent-frozen-source-witnesses/99'
    elif change=='source_row':
        source=next(t for t in c['source_data']['payload']['terms'] if t['native_term']['security_id']==data.SID)
        source['source_row']['raw_open']='1'
    elif change=='primary':c['primary_facts']['right_upper_per_share']='36.00'
    elif change=='prep':c['raw_quote_preparation']['actual_completion_quote_present']=True
    elif change=='quote':c['market_source']['source_quote_present']=True
    elif change=='prior_row':c['market_source']['raw_prior_row']['raw_close']='1'
    elif change=='split':c['market_source']['split_ratio']='2'
    elif change=='legal':c['event']['upfront_cash_per_share']='381.00'
    elif change=='authority':c['financial_authority']=True
    else:c['input_semantics_sources'][data.CASES[c['arm']]['binding']]='0'*64
    with pytest.raises(ValueError):data.validate(c,root_lookup=root_spec)

def remove_guard(label):
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,n):
            if isinstance(n.value,ast.Call) and any(isinstance(x,ast.Constant) and x.value==label for x in n.value.args):self.hits+=1;return None
            return self.generic_visit(n)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-ABMD-DATA-guard>','exec'),scope);return scope['validate']

def test_removed_full_source_guard_really_accepts_mutated_P06_source_row():
    c=json.loads((Path(__file__).resolve().parents[2]/'P06-own1238-ABMD-bounded-catalog-v2.json').read_bytes())
    t=next(t for t in c['source_data']['payload']['terms'] if t['native_term']['security_id']==data.SID);t['source_row']['raw_open']='1'
    with pytest.raises(ValueError):data.validate(c,root_lookup=root_spec)
    assert remove_guard('ABMD_ENTIRE_ORIGINAL_SOURCE_GENERATION_BYTES')(c,root_lookup=root_spec)['source_data']['payload']['terms']

def test_removed_absent_quote_guard_really_accepts_fabricated_completion_quote(actual):
    c=deepcopy(actual);c['market_source']['source_quote_present']=True
    c['market_source_sha256']=data.sha(data.encoded(c['market_source']))
    with pytest.raises(ValueError):data.validate(c,root_lookup=root_spec)
    assert remove_guard('ABMD_EXACT_ABSENT_EVENT_QUOTE_AND_ACTUAL_PRIOR_ANCHOR')(c,root_lookup=root_spec)['market_source']['source_quote_present'] is True

def test_provisional_missing_runtime_pin_is_unselectable(actual):
    c=deepcopy(actual);[c['input_semantics_sources'].pop(n) for n in data.CASES[c['arm']]['bindings']]
    with pytest.raises(ValueError):data.validate(c,root_lookup=root_spec)
    assert data.validate(c,root_lookup=root_spec,require_runtime=False)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)

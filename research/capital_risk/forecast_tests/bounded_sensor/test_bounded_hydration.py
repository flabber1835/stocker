"""Actual independently closed raw witness data, without the hosted reader."""
import ast,json,sys
from pathlib import Path
from copy import deepcopy
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('BOUNDED_HYDRATION_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_bounded_sensor_hydration as data

def fixture():
    c=json.loads((Path(data.__file__).parent/'P03-own462-DOVA-source-bound-input-catalog-v1.json').read_bytes())
    return c,deepcopy(c['native']),[deepcopy(c['market_source'][n]) for n in ('raw_prior_row','raw_event_row')]

def test_full_actual_source_rows_and_incomplete_native_are_preserved():
    c,n,rows=fixture();before=deepcopy((c,n,rows));v=data.witness(c,n,rows)
    assert v==c['market_source'] and (c,n,rows)==before
    assert v['raw_event_row']['raw_close']=='28.039999999999999'
    assert n['cash_per_share'] is None

@pytest.mark.parametrize('change',['cash_native','native_hash','event_close','prior_close','quote_missing','extra_row','missing_row','wrong_sid','split','source_hash'])
def test_changed_actual_native_or_raw_witness_refuses(change):
    c,n,rows=fixture()
    if change=='cash_native':n['cash_per_share']=27.5
    elif change=='native_hash':c['event']['native_term_sha256']='0'*64
    elif change=='event_close':rows[1]['raw_close']='27.50'
    elif change=='prior_close':rows[0]['raw_close']='1'
    elif change=='quote_missing':c['market_source']['source_quote_present']=False
    elif change=='extra_row':rows.append(deepcopy(rows[0]))
    elif change=='missing_row':rows.pop()
    elif change=='wrong_sid':rows[1]['security_id']='1'
    elif change=='split':c['market_source']['split_ratio']='2'
    else:c['market_source']['source_observation_sha256']='0'*64
    with pytest.raises(ValueError):data.witness(c,n,rows)

def test_removing_full_row_guard_really_accepts_a_changed_event_quote():
    c,n,rows=fixture();rows[1]['raw_close']='27.50'
    with pytest.raises(ValueError):data.witness(c,n,rows)
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='witness')
    before=len(fn.body);fn.body=[n for n in fn.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='BOUNDED_HYDRATE_COMPLETE_ACTUAL_FROZEN_PRIOR_AND_EVENT_ROWS' for v in n.value.args))]
    assert len(fn.body)==before-1
    scope=dict(vars(data));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-exact-frozen-rows-guard-DATA-only>','exec'),scope)
    assert scope['witness'](c,n,rows)==c['market_source']

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_runtime_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)

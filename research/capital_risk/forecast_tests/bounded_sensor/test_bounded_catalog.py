"""Source-only falsifiers for the actual own462 bounded contingent plan."""
import ast
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import pytest


class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('BOUNDED_CATALOG_DATA_ONLY:'+fullname)


sys.meta_path.insert(0,Fence())
sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,str(Path.cwd().parents[1]))
import system_campaign_bounded_sensor_catalog as data


def actual():
    return json.loads((Path(data.__file__).parent/'P03-own462-DOVA-source-bound-input-catalog-v1.json').read_bytes())


def root_lookup(value):
    from system_campaign_financial_partial import root_spec
    root=root_spec(value['arm'],value['parent_root_admission_sha256'])
    return lambda arm,root_id:root


def repin(value):
    source=value['source_data']
    source['payload_sha256']=data.sha(data.encoded(source['payload']))
    source['review']['payload_sha256']=source['payload_sha256']
    source['review_sha256']=data.sha(data.encoded(source['review']))
    source['qualification']['payload_sha256']=source['payload_sha256']
    source['qualification']['review_sha256']=source['review_sha256']
    source['qualification_sha256']=data.sha(data.encoded(source['qualification']))
    for field in ('market_source','raw_quote_preparation'):
        for key in ('payload','review','qualification'):value[field]['source290_'+key+'_sha256']=source[key+'_sha256']
    value['market_source']['event_contract_sha256']=data.digest(value['event'])
    for field in ('market_source','raw_quote_preparation','primary_facts'):value[field+'_sha256']=data.sha(data.encoded(value[field]))


def test_actual_catalog_has_full15_inputs_real_event_quote_and_no_adoption():
    value=actual();before=deepcopy(value)
    assert data.validate(value,root_lookup=root_lookup(value))==value and value==before
    assert len(value['parent_descriptors'])==15 and value['market_source']['source_quote_present'] is True
    assert value['event']['right_upper_per_share']=='1.50' and value['event']['cash_settlement_authorized'] is False


@pytest.mark.parametrize('mutation',['parent','descriptor','authority','endpoint','settlement','quote_absent',
    'quote_identity','quote_day','prior_day','owned','native_cash','native_hash','q_authority','q_economics',
    'q_inputs','review_clock','review_authority','primary_right_transfer','market_price_selected'])
def test_semantic_source_mutations_refused_even_after_repinning(mutation):
    value=actual();lookup=root_lookup(value)
    if mutation=='parent':value['parent_outer_sha256']='0'*64
    elif mutation=='descriptor':value['parent_descriptors'][0]['resume_session']='2018-01-03'
    elif mutation=='authority':value['financial_authority']=0
    elif mutation=='endpoint':value['event']['right_upper_per_share']='100.00'
    elif mutation=='settlement':value['event']['cash_settlement_authorized']=True
    elif mutation=='quote_absent':value['market_source']['source_quote_present']=False
    elif mutation=='quote_identity':value['market_source']['raw_event_row']['issuer_id']='WRONG'
    elif mutation=='quote_day':value['market_source']['raw_event_row']['session']='2019-11-13'
    elif mutation=='prior_day':value['market_source']['raw_prior_row']['session']='2019-11-08'
    elif mutation=='owned':value['source_data']['payload']['terms'][0]['parent_positions']=[dict(quantity=1)]
    elif mutation=='native_cash':value['native']['cash_per_share']=29.
    elif mutation=='native_hash':value['event']['native_term_sha256']='0'*64
    elif mutation=='q_authority':value['source_data']['qualification']['financial_authority']=True
    elif mutation=='q_economics':value['source_data']['qualification']['value_timing_or_unheld_source_policy_qualified']=True
    elif mutation=='q_inputs':value['source_data']['qualification']['own_inputs_preserved']=14
    elif mutation=='review_clock':value['source_data']['review']['parent_outer_sha256']='0'*64
    elif mutation=='review_authority':value['source_data']['review']['financial_sessions_advanced']=False
    elif mutation=='primary_right_transfer':value['primary_facts']['right_transferable']=True
    else:value['market_source']['right_price_selected']=True
    repin(value)
    with pytest.raises(ValueError):data.validate(value,root_lookup=lookup)


@pytest.mark.parametrize('mutation,label',[('owned','CATALOG_EXACT_INCOMPLETE_NATIVE_AND_UNOWNED_ROLE'),
    ('endpoint','CATALOG_EXACT_QUALIFIED_CONTINGENT_LEGAL_ENDPOINTS'),
    ('quote_absent','CATALOG_ACTUAL_PRESENT_EVENT_QUOTE_AND_IDENTITY')])
def test_new_guard_removals_admit_the_corresponding_bad_data(mutation,label):
    value=actual();lookup=root_lookup(value)
    if mutation=='owned':value['source_data']['payload']['terms'][0]['parent_positions']=[dict(quantity=1)]
    elif mutation=='endpoint':value['event']['right_upper_per_share']='100.00'
    else:value['market_source']['source_quote_present']=False
    repin(value)
    with pytest.raises(ValueError,match=label):data.validate(value,root_lookup=lookup)
    fn,=[n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate']
    guards=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
            and any(isinstance(a,ast.Constant) and a.value==label for a in n.value.args)]
    assert len(guards)==1;fn.body.remove(guards[0])
    namespace=dict(vars(data));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<bounded-catalog-guard-removal>','exec'),namespace)
    assert namespace['validate'](value,root_lookup=lookup)==value


@pytest.mark.parametrize('name',['research.pooled_vacancy_funding','stock_strategy_shared.wealth_core','sentinel.controller','numpy','pandas'])
def test_financial_runtime_import_fences(name):
    with pytest.raises(ImportError,match='DATA_ONLY'):importlib.import_module(name)

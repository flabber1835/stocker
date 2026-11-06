"""One original-cash subset bound to complete SOURCE327; no financial runtime."""
import ast,gzip,json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import FunctionType
import system_campaign_qualified_cash_batch as cash
import system_campaign_qualified_cash_subset as subset
from system_campaign_bounded_sensor_input import need,sha,digest

HERE=Path(__file__).parent
ROOT='4c56c4240f1e5f36c91e76f5033ba9748d1217879043885e415727894b67fad1'
OUTER='7bd2591e0e34b22e9800bd8df50a5773e26ddbc4052b015b7a9e17eaec7fe567'
SID='731910459224080858'
CATALOG='P03-own503-THOR2-preopen-ordinary17-catalog.json'
PRIMARY='P03-THOR2-qualified-preopen-fact-v2.json'
PRIMARY_SHA='09a99b90808f083d8a8cd6a50ad1d1efeb5687fb8aa4ff3a9ad2afa985236f69'
QUALIFICATION_SHA='aa802805042661ea6750915c947918cd0622b9364009a579fbcc889ea2381de1'
SUBSET_SHA='e0f7f8599032d6927a9fb84f156bcb60c8c0162b7abd37a47db5bdd1a7ae7ea2'
ORIGINAL_SHA='96c9763e021c72c784b04c7033dd32940b9809cff6b56ba0e394287e0cdd3f36'
SCOPE='f86015e954834bda3c8291e508cb25a57f02d44340d09727bd02ec3402886090'
def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def parent_contract(cp,spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec);run=cp['run']
    need(spec['arm']=='P03' and spec['root_admission_sha256']==ROOT
        and (cp['sha256'],cp['completed'],cp['source_cursor'],len(cp['repairs']))==(OUTER,503,'2019-12-31',16)
        and cp['sha256']==spec['outer_sha256']==digest({k:v for k,v in cp.items() if k!='sha256'})
        and cp['base']==spec['base'] and cp['repairs']==spec['repairs']
        and run['checkpoint_sha256']==spec['inner_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
        and run['state_sha256']==spec['state_sha256']==digest(run['state'])
        and run['input_sha256']==spec['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs']))
        and run['state']['last_processed_session']==cp['source_cursor'],
        'THOR_ONLY_ACTUAL_OWN503_FULL16_PARENT_ALL_COMMITMENTS')
    proof=spec['root_admission']['branch_uncertainty_proof']
    need(proof['passed'] is True and type(proof['rows']) is type(proof['retained_rows']) is int
        and (proof['rows'],proof['retained_rows'])==(41,8)
        and proof['all_comparisons_and_state_sets_verified'] is proof['all_math_watch_financial_chains_verified'] is True,
        'THOR_ONLY_ACTUAL_ADMITTED49_PROOFS_NO_RAW_TAIL_SEED')
    return True
def primary_fact():
    raw=(HERE/PRIMARY).read_bytes();need(sha(raw)==PRIMARY_SHA,'THOR_EXACT_INDEPENDENT_PRIMARY_PREOPEN_FACT')
    value=json.loads(raw)
    need(value['security_id']==SID and value['ticker']=='THOR2' and value['cash_per_share']=='68.00'
        and value['currency']=='USD' and value['mandatory_common_cash'] is True
        and value['completion_date']=='2020-01-23' and value['preopen_completion_confirmed'] is True
        and value['publication_completion_upper_bound']=='2020-01-23T08:52:00-05:00'
        and value['exact_legal_effective_timestamp'] is None and value['payment_timestamp_asserted'] is False
        and value['frozen_metadata_upgraded'] is False and value['stock_or_contingent_common_components']==[],
        'THOR_COMMON_CASH_AND_PAST_TENSE_ISSUER_PUBLICATION_BEFORE_OPEN_ONLY')
    return value
def scope(key):
    import system_campaign_p03_forward_source_queries as source
    query,=source.registry().queries;value=query.scope.model_dump()
    need(query.root_admission_sha256==ROOT and query.parent_completed==503 and query.parent_input_count==16
        and digest(value)==key==SCOPE and len(value['terms'])==128 and value['additional_rows']==[],
        'THOR_EXACT_IMMUTABLE_FIRST128_SOURCE327_SCOPE_NOT_LATER_ACTIVE_BATCH')
    return value
def source_tree(raw):
    need(sha(raw)==ORIGINAL_SHA,'THOR_WHOLE_ORIGINAL_CASH_SOURCE_BINDING')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='source_binding']
    imports=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_future']
    need(len(imports)==1 and [(n.name,n.asname) for n in imports[0].names]==[('registered_scope',None)],
        'THOR_ONE_ORIGINAL_REGISTERED_SCOPE_IMPORT')
    fn.body.remove(imports[0])
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='research.independent-frozen-source-data-validation/1']
    need(len(sites)==1,'THOR_ONE_ORIGINAL_QUALIFICATION_SCHEMA_SITE')
    sites[0].value='research.independent-forward-source-DATA-validation/2'
    return ast.fix_missing_locations(fn)
def source_binding(catalog):
    raw=Path(cash.__file__).read_bytes();namespace=dict(vars(cash),registered_scope=scope)
    exec(compile(ast.Module(body=[source_tree(raw)],type_ignores=[]),'<whole-original-cash-source-binding-closed-SOURCE327-generation>','exec'),namespace)
    result=namespace['source_binding'](catalog)
    need(sha(encoded(result[2]))==QUALIFICATION_SHA,'THOR_EXACT_INDEPENDENT_SOURCE327_QUALIFICATION_BYTES')
    return result
def validate(catalog):
    need(sha(Path(subset.__file__).read_bytes())==SUBSET_SHA,'THOR_WHOLE_ORIGINAL_CASH_SUBSET_SOURCE')
    original=subset.validator()
    fn=FunctionType(original.__code__,dict(original.__globals__,__file__=__file__,source_binding=source_binding),
        original.__name__,original.__defaults__)
    need(fn.__code__ is original.__code__,'THOR_WHOLE_ORIGINAL_SELECTED_CASH_VALIDATOR_CODE')
    result=fn(catalog);fact=primary_fact();term,=catalog['terms']
    need(catalog['arm']=='P03' and catalog['parent_root_admission_sha256']==ROOT and catalog['parent_outer_sha256']==OUTER
        and len(catalog['selected_source_indices'])==1 and catalog['retained_source_indices']==[]
        and term['security_id']==SID and term['ticker']=='THOR2' and term['native_session']=='2020-01-23'
        and term['last_trading_session']=='2020-01-22' and term['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION'
        and term['preopen_completion_confirmed'] is True and term['actual_completion_date']==fact['completion_date']
        and Decimal(str(term['added']['cash_per_share']))==Decimal(fact['cash_per_share'])
        and term['identity_witness']['issuer_id']=='SEC_UNKNOWN:'+SID and term['identity_witness']['security_type_eligible']=='0'
        and term['parent_positions']==[] and term['primary_extraction']['qualified_preopen_fact_sha256']==PRIMARY_SHA
        and term['primary_extraction']['no_stock_or_contingent_rights_in_common_consideration'] is True,
        'THOR_ONE_EXACT_COMMON_CASH_TERM_PRESERVE_UNKNOWN_SOURCE_METADATA')
    return result
class QualifiedThorCash:
    def __init__(self,value):
        if isinstance(value,Path):
            raw=value.read_bytes();value=json.loads(raw);need(raw==encoded(value),'THOR_EXACT_CANONICAL_CATALOG_BYTES')
        init=cash.QualifiedCashBatch.__init__
        need(init.__closure__ is None,'THOR_ORIGINAL_CASH_CONSTRUCTOR_NO_HIDDEN_CLOSURE')
        FunctionType(init.__code__,dict(init.__globals__,validate=validate),init.__name__,init.__defaults__)(self,value)
        self.catalog_sha=sha(encoded(value));self.compiler_sha=sha(Path(__file__).read_bytes())
def catalog():
    value=json.loads((HERE/CATALOG).read_bytes());validate(value);return value
def source_names():return (Path(__file__).name,CATALOG,PRIMARY)

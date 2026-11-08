"""Finite SOURCE335 cash batch and exact own1259 parent metadata; no engine."""
import ast,json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import FunctionType
import system_campaign_qualified_cash_batch as cash
import system_campaign_qualified_own_cash_literals as literals
from system_campaign_bounded_sensor_input import need,sha,digest

HERE=Path(__file__).parent
ROOT='d9c73a5ceebdc806feeae4338034626c0c3b4aef42309f3849d69c20cfbf8f7b'
OUTER='1e1e4dbce5a3b13c329bfb2c16a99e6f6043bcc8628a9852971f7100d9295a3a'
SID='219953444935140'
SCOPE='e3aec8e32e4b81259491681c69986a9dacfaf9af2beeccc40d30d22952f71ef6'
CATALOG='P07-own1259-VIVO1-preopen-ordinary25-catalog.json'
PRIMARY='P07-VIVO1-preopen-common-cash-primary-fact.json'
PRIMARY_SHA='74e24e486b3e189a0ce1097bfc1603203d28105ce1ab3b654c6737fb48e79c83'
IDENTITY='P07-own1259-805-proof-identity-DATA.json'
IDENTITY_SHA='6fd0bfdec695db375e09860422ea7374cbca31e69872c4417eb1247dc615ea06'
QUALIFICATION_SHA='8b65bebf761e39820ef9bc8aa0003f6f258b7c26821f1069b774317551380a1f'
BASE_SHA='96c9763e021c72c784b04c7033dd32940b9809cff6b56ba0e394287e0cdd3f36'
LITERALS_SHA='ff903349d5f91521087f45a0bba6fb493b1513f8d01be830c20a7d757e12ec45'
SUPPORTED='system-campaign-p05-own1070-supported-cash-inputs.json'
SUPPORTED_SHA='0215ae4293365f6327dfd38dce0493b05b67cb7cb400ff494876d835df61fb77'
PINS={'P07-VIVO-source-payload.json':'744bfb7807b1ba0e643e0a53cc867f6b9db7ca2b202202990892a5426ceac1d7',
      'P07-SOURCE335-independent-source-data-review.json':'0d4255c4591dadd8107b814b26b7a981110d12f5dae4fa70f312790d0c90391b',
      'P07-SOURCE335-independent-source-DATA-validation-v2.json':QUALIFICATION_SHA}
FRESH=literals.FRESH
encoded=cash.encoded

def identity_plan():
    raw=(HERE/IDENTITY).read_bytes();need(sha(raw)==IDENTITY_SHA,'VIVO_EXACT_CLOSED805_IDENTITY_DATA')
    value=json.loads(raw)
    need(value['passed'] is True and value['root_admission_sha256']==ROOT and value['actual_outer_sha256']==OUTER
         and (value['completed'],value['source_cursor'],value['full_inputs'],value['committed_proofs'],value['new_proofs'],value['retained_proofs'])
            ==(1259,'2022-12-30',24,805,21,784)
         and value['checkpoint_created'] is value['proof_seed_file_created'] is value['local_canonical_runtime_executed'] is False,
         'VIVO_ONLY_REAL1259_FULL24_805_PREFIX_NO_JANUARY_TAILS')
    return value

def parent_contract(cp,spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec);run=cp['run'];plan=identity_plan()
    need(spec['arm']=='P07' and spec['root_admission_sha256']==ROOT
         and (cp['sha256'],cp['completed'],cp['source_cursor'],len(cp['repairs']))==(OUTER,1259,'2022-12-30',24)
         and cp['sha256']==spec['outer_sha256']==digest({k:v for k,v in cp.items() if k!='sha256'})
         and cp['base']==spec['base'] and cp['repairs']==spec['repairs']
         and run['checkpoint_sha256']==spec['inner_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
         and run['state_sha256']==spec['state_sha256']==digest(run['state'])
         and run['input_sha256']==spec['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs']))
         and cp['repairs'][23]==plan['actual_ABMD_descriptor'] and run['state']['last_processed_session']==cp['source_cursor'],
         'VIVO_ACTUAL_OWN1259_FULL24_ALL_CANONICAL_JSON_COMMITMENTS')
    proof=spec['root_admission']['branch_uncertainty_proof']
    need(proof['passed'] is True and type(proof['rows']) is type(proof['retained_rows']) is int
         and (proof['rows'],proof['retained_rows'])==(21,784)
         and proof['all_comparisons_and_state_sets_verified'] is proof['all_math_watch_financial_chains_verified'] is True,
         'VIVO_EXACT_INDEPENDENT805_ADMITTED_PROOF_AXIS')
    return True

def primary_fact():
    raw=(HERE/PRIMARY).read_bytes();need(sha(raw)==PRIMARY_SHA,'VIVO_EXACT_INDEPENDENT_PRIMARY_COMMON_CASH_FACT')
    value=json.loads(raw)
    need(value['security_id']==SID and value['ticker']=='VIVO1' and value['cash_per_eligible_common_share']=='34.00'
         and value['mandatory_eligible_common_cash'] is value['preopen_completion_confirmed'] is True
         and (value['completion_date'],value['last_trading_session'],value['native_session'],value['source_identity_session'])
            ==('2023-01-31','2023-01-30','2023-01-30','2023-01-27')
         and value['provider_identity_upgraded'] is value['actual_broker_settlement_asserted'] is value['financial_authority'] is False
         and value['provider_SEC_UNKNOWN_retained'] is True and value['stock_or_contingent_rights_in_common_consideration']==[]
         and value['common_consideration_components']==[dict(kind='CASH',currency='USD',amount_per_share='34.00')],
         'VIVO_MANDATORY_COMMON34_PREOPEN_JAN31_KEEP_PROVIDER_UNKNOWN')
    return value

def records():
    values=[]
    for name,pin in PINS.items():
        raw=(HERE/name).read_bytes();need(sha(raw)==pin,'VIVO_WHOLE_REAL_SOURCE335_CLOSED_DATA_BYTES:'+name);values.append(json.loads(raw))
    payload,review,q=values
    need(payload['scope_sha256']==SCOPE==digest(payload['scope']) and len(payload['terms'])==len(payload['scope']['terms'])==128
         and q['root_admission_sha256']==ROOT and q['payload_sha256']==PINS['P07-VIVO-source-payload.json']
         and q['scope_sha256']==SCOPE and q['review_sha256']==PINS['P07-SOURCE335-independent-source-data-review.json']
         and q['schema']=='research.independent-forward-source-DATA-validation/2'
         and type(q['old_financial_rows_reaudited']) is int and q['old_financial_rows_reaudited']==0,
         'VIVO_EXACT_SOURCE335_COMPLETE128_GENERATION')
    return payload,review,q

def registered_scope(pin):
    need(pin==SCOPE,'VIVO_ONLY_CLOSED_SOURCE335_SCOPE');return deepcopy(records()[0]['scope'])

def source_tree(raw):
    need(sha(raw)==BASE_SHA,'VIVO_WHOLE_ORIGINAL_CASH_SOURCE_BINDING')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='source_binding']
    imports=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_future']
    need(len(imports)==1 and [(n.name,n.asname) for n in imports[0].names]==[('registered_scope',None)],'VIVO_ONE_ORIGINAL_SCOPE_IMPORT')
    fn.body.remove(imports[0])
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='research.independent-frozen-source-data-validation/1']
    need(len(sites)==1,'VIVO_ONE_SOURCE_DATA_GENERATION_SCHEMA');sites[0].value='research.independent-forward-source-DATA-validation/2'
    return ast.fix_missing_locations(fn)

def source_binding(catalog):
    payload,review,q=records()
    need(catalog['source_data']==dict(payload=payload,review=review,qualification=q),'VIVO_COMPLETE_SOURCE_DATA_NOT_FILTERED')
    namespace=dict(vars(cash),registered_scope=registered_scope)
    exec(compile(ast.Module(body=[source_tree(Path(cash.__file__).read_bytes())],type_ignores=[]),'<whole-cash-source-binding-actual-SOURCE335>','exec'),namespace)
    return namespace['source_binding'](catalog)

def original_primary_tree():
    raw=Path(cash.__file__).read_bytes();need(sha(raw)==BASE_SHA,'VIVO_WHOLE_ORIGINAL_PRIMARY_EXTRACTION_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate']
    loop,=[n for n in fn.body if isinstance(n,ast.For)]
    index,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='extraction']
    need('CASH_BATCH_EXACT_PRIMARY_AMOUNT_AND_DATE_EXTRACTION' in ast.unparse(loop.body[index+1]),'VIVO_ORIGINAL_PRIMARY_GUARD_SITE')
    wrapper=ast.parse('def validate_primary(term):\n pass').body[0];wrapper.body=deepcopy(loop.body[index:index+2])
    return ast.fix_missing_locations(wrapper)

def validate_vivo(term):
    fact=primary_fact();ns=dict(vars(cash))
    exec(compile(ast.Module(body=[original_primary_tree()],type_ignores=[]),'<whole-original-primary-amount-date-extraction>','exec'),ns)
    ns['validate_primary'](term)
    need(term['security_id']==SID and term['ticker']=='VIVO1' and term['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION'
         and term['native_session']==term['last_trading_session']==fact['native_session']
         and term['actual_completion_date']==term['added']['session']==fact['completion_date']
         and Decimal(str(term['added']['cash_per_share']))==Decimal(fact['cash_per_eligible_common_share'])
         and term['primary_source']==fact['source'] and term['timing_source']==fact['timing_source']
         and term['preopen_completion_confirmed'] is term['mandatory_common_share_completion_confirmed'] is True
         and term['identity_witness']['issuer_id']=='SEC_UNKNOWN:'+SID and term['identity_witness']['security_type_eligible']=='0'
         and term['identity_witness']['session']==fact['source_identity_session']
         and term['parent_positions']==[dict(slot_id=1,ticker='VIVO1',quantity=84,entry_date='2022-07-11')]
         and term['primary_extraction']['qualified_common_cash_fact_sha256']==PRIMARY_SHA
         and term['primary_extraction']['no_stock_or_contingent_rights_in_common_consideration'] is True
         and literals.REFERENCE not in term,
         'VIVO_ONE_GENUINE_HELD84_COMMON34_INPUT_NO_IDENTITY_OR_RIGHTS_UPGRADE')

def validate_original_literal(term):
    return validate_vivo(term) if term['security_id']==SID else literals.validate_original_literal(term)

def existing_cash_policy(term):
    return term['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION' if term['security_id']==SID else literals.existing_cash_policy(term)

def validate(catalog):
    need(sha(Path(literals.__file__).read_bytes())==LITERALS_SHA,'VIVO_WHOLE_ORIGINAL_CASH_LITERAL_COMPILER')
    namespace=dict(vars(cash),__file__=__file__,CashInputBatch=literals.OriginalCashLiterals,
        selected_members=literals.selected_members,source_binding=source_binding,existing_cash_policy=existing_cash_policy,
        validate_original_literal=validate_original_literal)
    exec(compile(ast.Module(body=[literals.validator_tree()],type_ignores=[]),'<whole-original-cash-literals-one-finite-new-VIVO-primary>','exec'),namespace)
    result=namespace['validate'](catalog)
    need(catalog['arm']=='P07' and catalog['parent_cursor']=='2022-12-30' and catalog['parent_outer_sha256']==OUTER
         and catalog['parent_root_admission_sha256']==ROOT and len(catalog['terms'])==23
         and sum(t['security_id']==SID for t in catalog['terms'])==1
         and len([t for t in catalog['terms'] if literals.REFERENCE in t])==22,
         'VIVO_EXACT_ONE_NEW_AND22_ORIGINAL_LEGAL_TERMS_IN_SINGLE_ORDINARY_INPUT')
    return result

class QualifiedVivoCash:
    def __init__(self,value):
        if isinstance(value,Path):
            raw=value.read_bytes();value=json.loads(raw);need(raw==encoded(value),'VIVO_CANONICAL_CATALOG_BYTES')
        init=cash.QualifiedCashBatch.__init__
        need(init.__closure__ is None,'VIVO_ORIGINAL_CASH_CONSTRUCTOR_NO_CLOSURE')
        FunctionType(init.__code__,dict(init.__globals__,validate=validate),init.__name__,init.__defaults__)(self,value)
        self.catalog_sha=sha(encoded(value));self.compiler_sha=sha(Path(__file__).read_bytes())

def catalog():
    value=json.loads((HERE/CATALOG).read_bytes());validate(value);return value

def source_names():return (Path(__file__).name,CATALOG,PRIMARY,IDENTITY,*PINS)

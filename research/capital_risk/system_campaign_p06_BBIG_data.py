"""Complete original selected-own catalog plus one source-only BBIG member."""
import ast,json
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import system_campaign_financial_future as original
import system_campaign_qualified_cash_batch as cash
from system_campaign_bounded_sensor_input import need,sha,digest

HERE=Path(__file__).parent
ROOT='28c768af0d50047f04ddd6924c1500bf768cc138f41808cd1c0a0b5321eb64b8'
OUTER='bd3e5c6b01942efedf344756dd2a52a7a616fbf81b4d76c73f1397b9498a3e08'
SID='1150551303615013770'
FUTURE_SHA='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'
CASH_SHA='96c9763e021c72c784b04c7033dd32940b9809cff6b56ba0e394287e0cdd3f36'
CATALOG='P06-own1383-BBIG-source-only-ordinary11-catalog.json'
CATALOG_SHA='2f87d2be007222865d2abaa93458b8b167a8eac7f4e990b290c0d99c6f9477b0'
SOURCE='P06-BBIG-SOURCE335-closed-source-DATA.json'
SOURCE_SHA='9973a607fd6bdc12ce962d3237c190c99ed59b65dcc9770baae8b95cb591cfb0'
FACT='P06-BBIG-source-exit-raw-quote-axis-DATA.json'
FACT_SHA='9387fc465d7eca0393eb47fd43af84bfc85c7bdec594551ee23a764cb1b98bb4'
SCOPE='0da5ffba814fec8d80d21eb390ca2f95169380e3457802683e15dd1b44189fd5'
QUALIFICATION_SHA='6ad113c2ef87b9e1db05e9122468b404b879d5eaa4c3c517450c0c32f016389a'
def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def pinned(name,pin):
    raw=(HERE/name).read_bytes();need(sha(raw)==pin,'P06_BBIG_EXACT_PRIVATE_DATA_BYTES:'+name)
    value=json.loads(raw);need(encoded(value)==raw,'P06_BBIG_CANONICAL_DATA_ENCODING');return value
def parent_contract(cp,spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec);run=cp['run'];proof=spec['root_admission']['branch_uncertainty_proof']
    need(spec['arm']=='P06' and spec['root_admission_sha256']==ROOT
        and (cp['sha256'],cp['completed'],cp['source_cursor'],len(cp['repairs']))==(OUTER,1383,'2023-06-30',10)
        and cp['sha256']==spec['outer_sha256']==digest({k:v for k,v in cp.items() if k!='sha256'})
        and cp['base']==spec['base'] and cp['repairs']==spec['repairs']
        and run['checkpoint_sha256']==spec['inner_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
        and run['state_sha256']==spec['state_sha256']==digest(run['state'])
        and run['input_sha256']==spec['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs']))
        and run['state']['last_processed_session']==cp['source_cursor'],
        'P06_BBIG_ONLY_ACTUAL_ADMITTED1383_FULL10_ALL_COMMITMENTS')
    need(proof['passed'] is True and type(proof['rows']) is type(proof['retained_rows']) is int
        and (proof['rows'],proof['retained_rows'])==(124,6)
        and proof['all_comparisons_and_state_sets_verified'] is proof['all_math_watch_financial_chains_verified'] is True,
        'P06_BBIG_ONLY_ACTUAL_ADMITTED130_PROOFS')
    return True
def registered_scope(key):
    if key!=SCOPE:return original.registered_scope(key)
    import system_campaign_p06_forward_source_queries as queries
    query,=queries.registry().queries;value=query.scope.model_dump()
    need(query.root_admission_sha256==ROOT and query.parent_completed==1383 and query.parent_input_count==10
        and digest(value)==key and len(value['terms'])==128 and value['additional_rows']==[],
        'P06_BBIG_EXACT_IMMUTABLE_SOURCE335_SCOPE')
    return value
def source_tree(raw):
    need(sha(raw)==CASH_SHA,'P06_BBIG_WHOLE_ORIGINAL_SOURCE_BINDING_BYTES')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='source_binding']
    imp,=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_future']
    need([(v.name,v.asname) for v in imp.names]==[('registered_scope',None)],'P06_BBIG_ONE_SCOPE_IMPORT')
    fn.body.remove(imp)
    site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='research.independent-frozen-source-data-validation/1']
    site.value='research.independent-forward-source-DATA-validation/2'
    return ast.fix_missing_locations(fn)
def source_member_tree(raw):
    need(sha(raw)==CASH_SHA,'P06_BBIG_WHOLE_ORIGINAL_SOURCE_MEMBER_BYTES')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate']
    statement,=[n for n in ast.walk(fn) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='CASH_BATCH_EXACT_SOURCE_NATIVE_ROLE_AND_CLOCK' for v in n.value.args)]
    result=ast.parse('def check(catalog,term,actual,scope,checked,expected_capture):\n row,native=actual["source_row"],actual["native_term"]\n witness={k:row[k] for k in ("session","security_id","ticker","issuer_id","listing_first_session","security_type_eligible")}\n witness["source_observation_sha256"]=digest(row)\n pass').body[0]
    result.body[-1]=deepcopy(statement)
    return ast.fix_missing_locations(result)
def source_binding(value=None):
    value=pinned(SOURCE,SOURCE_SHA) if value is None else value
    scope=dict(vars(cash),registered_scope=registered_scope)
    exec(compile(ast.Module(body=[source_tree(Path(cash.__file__).read_bytes())],type_ignores=[]),'<entire-original-source-binding-one-qualification-schema-and-scope>','exec'),scope)
    payload,review,q=scope['source_binding'](value)
    need(sha(encoded(q))==QUALIFICATION_SHA,'P06_BBIG_EXACT_SOURCE335_QUALIFICATION')
    return payload,review,q
def qualify_member(term,value=None):
    value=pinned(SOURCE,SOURCE_SHA) if value is None else value
    payload,review,q=source_binding(value)
    index,=[i for i,v in enumerate(payload['terms']) if v['native_term']['security_id']==SID]
    expected=dict(run_id=review['run_id'],head=review['head'],artifact_id=review['artifact_id'],
        payload_sha256=review['payload_sha256'],scope_sha256=review['scope_sha256'],
        independent_data_review_sha256=sha(encoded(review)),independent_qualification_sha256=sha(encoded(q)))
    namespace=dict(vars(cash));exec(compile(ast.Module(body=[source_member_tree(Path(cash.__file__).read_bytes())],type_ignores=[]),'<entire-original-source-member-role-clock-predicate>','exec'),namespace)
    namespace['check'](value,term,payload['terms'][index],payload['scope']['terms'][index],review['terms'][index],expected)
    original.research_source_exit_term(term);original.source_exit_quote(term,payload['terms'][index]['source_row'])
    fact=pinned(FACT,FACT_SHA)
    need(index==fact['selected_source_index']==15 and term['retained_quote']==fact['retained_quote']
        and term['native']==fact['native'] and term['identity_witness']==fact['identity_witness']
        and term['research_assumption']['retained_raw_close']==fact['original_float_parse_decimal']=='3.88'
        and fact['next_frozen_session']==term['added']['session']=='2023-07-27'
        and float(fact['source_row']['raw_close']).hex()==fact['original_float_parse_hex']
        and fact['financial_authority'] is fact['input_selected'] is fact['actual_settlement_claimed'] is False,
        'P06_BBIG_EXACT_RAW_QUOTE_NEXT_FROZEN_AXIS_WITHOUT_SETTLEMENT')
    return True
def catalog():
    value=pinned(CATALOG,CATALOG_SHA)
    old=(Path(original.__file__).parent/original.OWN_CASH_CATALOG).read_bytes()
    need(sha(old)==original.OWN_CASH_SHA and len(value['terms'])==35
        and encoded(dict(value,terms=value['terms'][:-1]))==old,
        'P06_BBIG_ALL34_ORIGINAL_LITERAL_MEMBERS_AND_GENERATIONS_UNCHANGED')
    qualify_member(value['terms'][-1]);return value
def selector():
    raw=Path(original.__file__).read_bytes();need(sha(raw)==FUTURE_SHA,'P06_BBIG_ENTIRE_ORIGINAL_OWN_SELECTOR_SOURCE')
    value=catalog();phase=('P06','2023-06-30')
    namespace=dict(vars(original),HERE=HERE,__file__=__file__,OWN_CASH_CATALOG=CATALOG,OWN_CASH_SHA=CATALOG_SHA,
        OWN_CASH_PHASES=dict(original.OWN_CASH_PHASES,**{}),CASH_GENERATION_LENGTHS=dict(original.CASH_GENERATION_LENGTHS),
        OWN_CASH_SOURCE_CLOCKS=dict(original.OWN_CASH_SOURCE_CLOCKS),CLOSED_CASH_GENERATIONS=dict(original.CLOSED_CASH_GENERATIONS),
        registered_scope=registered_scope)
    namespace['OWN_CASH_PHASES'][phase]='BBIG';namespace['CASH_GENERATION_LENGTHS'][phase]=35
    namespace['OWN_CASH_SOURCE_CLOCKS'][phase]=(42243416342,'25581e7a0b3e90c4351bc4f15d7e16ec409caab0',13516337974)
    namespace['CLOSED_CASH_GENERATIONS'][original.OWN_CASH_SHA]=34
    fn=original.own_cash_selection
    need(fn.__closure__ is None,'P06_BBIG_ORIGINAL_SELECTOR_NO_CLOSURE')
    bound=FunctionType(fn.__code__,namespace,fn.__name__,fn.__defaults__)
    need(bound.__code__ is fn.__code__,'P06_BBIG_WHOLE_SELECTOR_CODE_OBJECT')
    return bound
def selected(arm,*,cursor=None):
    need((arm,cursor)==('P06','2023-06-30'),'P06_BBIG_ONE_NEW_PHASE_ONLY')
    codec,name,terms=selector()(arm,cursor)
    need(terms==[catalog()['terms'][-1]] and name==CATALOG,'P06_BBIG_ONE_SOURCE_EXIT_SELECTED')
    return codec,name,terms
def source_names():return (Path(__file__).name,CATALOG,SOURCE,FACT)

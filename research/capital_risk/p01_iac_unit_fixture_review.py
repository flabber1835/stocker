"""Hosted review adapter for complete declared synthetic fixture feeds."""
import ast
from copy import deepcopy
from pathlib import Path

import p01_iac_unit_review as previous
from p01_iac_unit_contract import SOURCE,CHILD,OLD_MATCH,EVENT,FIRST,need,sha,digest,encoded

SOURCE_SHA='3e2782792ad3baaefbe481dabd047269771cce89f9fe1e8fcc74f9c7d27f4a2a'
ROLES=('HELD','CLOSE_PENDING','DOLLAR_BUY_PENDING','EXIT_FLAG_ONLY')
CASE_IDS=tuple(sid+'/'+role for sid in (CHILD,OLD_MATCH) for role in ROLES)+('POST_EVENT_SOURCE_BUY',)
EXTRAS={'actual_reference_boundary','fixture_source_files','fixture_contracts','fixture_contexts','fixture_aggregate'}
FIELDS=('wealth_core','ledger','pending','last_known','feed')
PHASE='ACTIONS_FILLS_CLOSE_PRE_DECISION_NOT_A_COMPLETE_SESSION'


def same(a,b):return encoded(a)==encoded(b)


def expected_plan(base,target,role):
    clock=sorted(base['feed']['seen_sessions'].items(),key=lambda x:x[1]);owned=base['last_processed_session']
    need(base['feed']['history_sessions']==260 and len(clock)>=3 and clock[-1]==(owned,base['feed']['session_index'])
         and all(clock[i][0]<clock[i+1][0] and clock[i][1]+1==clock[i+1][1] for i in range(len(clock)-1)),
         'FIXTURE_REVIEW_ACTUAL_OWNED_CALENDAR_AND_GLOBAL_INDEX')
    post=target==SOURCE
    need((post and owned==EVENT and role=='DOLLAR_BUY_PENDING') or (not post and owned=='2020-06-30'
         and target in (CHILD,OLD_MATCH) and role in ROLES),'FIXTURE_REVIEW_OWNED_ROLE_AND_EVENT_CLOCK')
    instruments={SOURCE:dict(ticker='SYNTHETIC_UNIT_SOURCE',issuer_id='SYNTHETIC_UNIT_SOURCE_ISSUER',
        raw_price=10. if post else 60.,volume=100000000.,unit_event=EVENT)}
    if not post:instruments[target]=dict(ticker='SYNTHETIC_TARGET',issuer_id='SYNTHETIC_TARGET_'+target,
        raw_price=10.,volume=100000000.,unit_event=None)
    return dict(schema='research.p01-iac-unit-synthetic-fixture-plan/1',base_state_sha256=digest(base),
        target_security_id=target,target_role=role,owned_session=owned,phase_session=FIRST[1] if post else EVENT,
        phase=PHASE,signal_session=owned,history_sessions=260,calendar=[[d,i] for d,i in clock],instruments=instruments,
        setup_session=clock[-2][0],setup_signal_session=clock[-3][0],replaced_fields=list(FIELDS),
        all_prices_and_histories_synthetic=True,market_observations_or_preIPO_evidence=False,complete_financial_transition=False)


def expected_feed(plan):
    days=[d for d,i in plan['calendar']];indices=[i for d,i in plan['calendar']];series={}
    for sid,domain in plan['instruments'].items():
        factor=1.;signals=[]
        for day in days:
            if day==domain['unit_event']:factor*=float('2.1584')
            signals.append(domain['raw_price']*factor);factor=signals[-1]/domain['raw_price']
        series[sid]=dict(security_id=sid,ticker=domain['ticker'],issuer_id=domain['issuer_id'],split_factor=factor,
            sessions=list(days),session_indices=list(indices),signal_closes=signals,
            raw_closes=[domain['raw_price']]*len(days),volumes=[domain['volume']]*len(days),
            signal_basis_anchor=[days[-1],domain['raw_price'],signals[-1]])
    return dict(history_sessions=260,session_index=indices[-1],seen_sessions=dict(plan['calendar']),series=series)


def validate_fixtures(value,contract,source_map,post_event_state,normalize_state,protected_ids,*,
                      input_zero_state,reference_components,qualifier_checkpoint,input_zero_checkpoint):
    need(value.get('schema')=='research.p01-iac-unit-synthetic-canonical-component/2' and EXTRAS<=set(value),
         'FIXTURE_REVIEW_EXACT_NEW_SCHEMA_AND_FIVE_DECLARED_FIELDS')
    expected=dict(schema='research.p01-iac-unit-fixture-aggregate/1',expected_case_ids=list(CASE_IDS),
        attempted_case_ids=list(CASE_IDS),passed_case_ids=list(CASE_IDS),failed_cases=[],complete=True,all_passed=True)
    need(same(value['fixture_aggregate'],expected),'FIXTURE_REVIEW_ALL_NINE_EXACT_ATTEMPTS_PASSED_NO_FAILURE')
    boundary=dict(schema='research.p01-iac-unit-unadmitted-reference-boundary/1',actual_components=reference_components,
        qualifier_checkpoint=qualifier_checkpoint,input_zero_checkpoint=input_zero_checkpoint,
        source_contract_sha256=digest(contract),actual_reference_records_preserved_before_fixtures=True,
        financial_authority=False,qualification_state_adopted=False)
    need(same(value['actual_reference_boundary'],boundary)
         and same(input_zero_checkpoint['run']['state'],input_zero_state)
         and same(reference_components[0]['checkpoint']['state'],post_event_state),
         'FIXTURE_REVIEW_ENTIRE_ACTUAL_REFERENCE_ZERO_PATH_AND_FINAL_BOUNDARY')
    names={'sentinel/core/session.py','shared/stock_strategy_shared/wealth_core/feed.py',
        'shared/stock_strategy_shared/wealth_core/adapter.py','shared/stock_strategy_shared/wealth_core/state.py',
        'shared/stock_strategy_shared/wealth_core/state_restore_validation.py','shared/stock_strategy_shared/wealth_core/shares.py'}
    pins=value['fixture_source_files']
    need(type(pins) is dict and set(pins)==names and all(source_map['successor_all_sources'].get(n)==h for n,h in pins.items()),
         'FIXTURE_REVIEW_ACTUAL516_COMPLETE_FIXTURE_SOURCE_PINS')
    need(set(value['fixture_contracts'])==set(value['fixture_contexts'])==set(CASE_IDS),
         'FIXTURE_REVIEW_EVERY_CONTRACT_AND_CONTEXT_PRESENT')
    for case in CASE_IDS:
        post=case=='POST_EVENT_SOURCE_BUY';target=SOURCE if post else case.split('/')[0]
        role='DOLLAR_BUY_PENDING' if post else case.split('/')[1];base=post_event_state if post else input_zero_state
        row=value['post_event_new_unit_case'] if post else value['target_cases'][case]
        before,after=row['before'],row['after'] if post else row['actual']
        plan=expected_plan(base,target,role);feed=expected_feed(plan);record=value['fixture_contracts'][case]
        need(same(before['feed'],feed) and same(after['feed'],feed),
             'FIXTURE_REVIEW_ENTIRE_DECLARED_FEED_ARRAYS_ANCHORS_AND_BASIS')
        protected=sorted(protected_ids(before['wealth_core'],before['pending']))
        following=sorted(protected_ids(after['wealth_core'],after['pending']))
        need(set(protected)|set(following)<=set(plan['instruments']),
             'FIXTURE_REVIEW_EVERY_PROTECTED_ID_HAS_DECLARED_SYNTHETIC_DOMAIN')
        for wire,ids,owned_base in ((before,protected,base),(after,following,before)):
            marks={sid:plan['instruments'][sid]['raw_price'] for sid in ids}
            projection=deepcopy(owned_base);projection.update({k:deepcopy(wire[k]) for k in FIELDS})
            need(same(wire['last_known'],marks) and same(wire,normalize_state(deepcopy(projection))),
                 'FIXTURE_REVIEW_ENTIRE_NORMALIZED_FIVE_FIELD_PROJECTION_AND_CURRENT_MARKS')
        expected_record=dict(plan=plan,protected_security_ids=protected,before_state_sha256=digest(before),
            before_feed_sha256=digest(before['feed']),canonical_roundtrip=True,financial_authority=False,
            after_state_sha256=digest(after),after_feed_sha256=digest(after['feed']),after_protected_security_ids=following,
            retained_current_marks=deepcopy(after['last_known']),canonical_after_roundtrip=True)
        need(same(record,expected_record),'FIXTURE_REVIEW_EXACT_FULL_BEFORE_AFTER_CONTRACT')
        context=dict(status='PASSED',phase=PHASE,before_state_sha256=digest(before),after_state_sha256=digest(after),financial_authority=False)
        need(same(value['fixture_contexts'][case],context),'FIXTURE_REVIEW_EXACT_DURABLE_PER_CASE_SUCCESS')
    return dict(cases=list(CASE_IDS),all_complete_feeds_and_normalized_projections_checked=True,
        entire_actual_reference_boundary_checked=True,synthetic_wires=18,financial_authority=False)


def opening_equity(before,sid,raw):
    """Exact frozen pre-fill scalar order, scoped to these synthetic books."""
    need(before['ledger']['receivables']==[],'FIXTURE_REVIEW_EMPTY_SYNTHETIC_OPEN_RECEIVABLES')
    value=float(before['wealth_core']['cash'])+0.0
    for key in sorted(before['wealth_core']['episodes'],key=int):
        episode=before['wealth_core']['episodes'][key]
        need(episode['security_id']==sid,'FIXTURE_REVIEW_OPEN_SYNTHETIC_TARGET_ONLY')
        value+=float(episode['current_shares'])*float(raw)
    return value


def _node(name):
    need(name in ('synthetic_component','review','review_loaded'),'FIXTURE_REVIEW_ONLY_DECLARED_FROZEN_FUNCTIONS')
    raw=Path(previous.__file__).read_bytes();need(sha(raw)==SOURCE_SHA,'FIXTURE_REVIEW_EXACT_WHOLE_490_VALIDATOR_SOURCE')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name];changes=[]
    class Scope(ast.NodeTransformer):
        def visit_ImportFrom(self,item):
            if item.module=='p01_iac_unit_export':
                need(name=='review_loaded' and [(n.name,n.asname) for n in item.names]==[('qualification',None)],
                     'FIXTURE_REVIEW_ONE_EXACT_EXPORT_GATE_IMPORT')
                item.module='p01_iac_unit_fixture_export';changes.append('export')
            return item
        def visit_BinOp(self,item):
            if name=='synthetic_component':
                target=ast.parse("after['wealth_core']['cash']+sum(e['current_shares']*10. for e in actual)",mode='eval').body
                post=ast.parse("after['wealth_core']['cash']+episodes[0]['current_shares']*post['raw_price']",mode='eval').body
                if ast.dump(item,include_attributes=False)==ast.dump(target,include_attributes=False):
                    changes.append('opening_target')
                    return ast.copy_location(ast.parse('opening_equity(before,sid,10.)',mode='eval').body,item)
                if ast.dump(item,include_attributes=False)==ast.dump(post,include_attributes=False):
                    changes.append('opening_post')
                    return ast.copy_location(ast.parse("opening_equity(before,sid,post['raw_price'])",mode='eval').body,item)
            return self.generic_visit(item)
        def visit_Tuple(self,item):
            if name=='synthetic_component' and all(isinstance(n,ast.Constant) for n in item.elts) and tuple(n.value for n in item.elts)==FIELDS[:4]:
                item.elts.append(ast.Constant('feed'));changes.append('projection')
            return self.generic_visit(item)
        def visit_Call(self,item):
            item=self.generic_visit(item)
            if isinstance(item.func,ast.Name) and item.func.id=='synthetic_component':
                need(name=='review_loaded' and not item.keywords,'FIXTURE_REVIEW_ONE_EXACT_SYNTHETIC_RECORD_CALL')
                item.keywords=ast.parse('f(input_zero_state=adopted["run"]["state"],reference_components=qrecord["reference_components"],qualifier_checkpoint=qrecord["qualifier_checkpoint"],input_zero_checkpoint=adopted)').body[0].value.keywords
                changes.append('boundaries')
            return item
    node=Scope().visit(node)
    need(changes=={'synthetic_component':['opening_target','projection','opening_post'],'review':[],'review_loaded':['export','boundaries']}[name],
         'FIXTURE_REVIEW_ONLY_EXPLICIT_IMPORT_PROJECTION_AND_CALLSITE_CHANGES')
    return node


def _body(name):
    node=_node(name);values=dict(vars(previous),**{k:v for k,v in globals().items() if not k.startswith('__')},__file__=__file__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<source-bound-fixture-review:'+name+'>','exec'),values)
    return values[name]


def synthetic_component(value,contract,origin,rows,configuration,source_map,post_event_state,normalize_state,*,
                        input_zero_state,reference_components,qualifier_checkpoint,input_zero_checkpoint):
    from full_system_core import hosted
    hosted()
    from sentinel.core.session import _path_dependent_security_ids
    validate_fixtures(value,contract,source_map,post_event_state,normalize_state,_path_dependent_security_ids,
        input_zero_state=input_zero_state,reference_components=reference_components,
        qualifier_checkpoint=qualifier_checkpoint,input_zero_checkpoint=input_zero_checkpoint)
    projected=deepcopy(value)
    for name in EXTRAS:projected.pop(name)
    projected['schema']='research.p01-iac-unit-synthetic-canonical-component/1'
    return _body('synthetic_component')(projected,contract,origin,rows,configuration,source_map,post_event_state,normalize_state)


def review(*a,**k):return _body('review')(*a,**k)


def review_loaded(*a,**k):
    result=_body('review_loaded')(*a,**k)
    result['fixture_review']=dict(schema='research.p01-iac-unit-fixture-review-binding/1',old_review_sha256=SOURCE_SHA,
        fixture_review_sha256=sha(Path(__file__).read_bytes()),cases=list(CASE_IDS),full_feed_projection_checked=True,
        actual_reference_boundary_checked=True,old_financial_arithmetic_unchanged=True)
    from full_system_benchmark import save
    out=Path(a[1] if len(a)>1 else k['out']);save(out/'iac-unit-financial-review.json',result)
    return result


main=review

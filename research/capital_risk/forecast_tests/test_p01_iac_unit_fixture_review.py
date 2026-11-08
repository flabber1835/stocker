"""Pure complete-fixture record and source-adapter falsifiers; no Core."""
import ast
from copy import deepcopy
from pathlib import Path
import sys

import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_unit_fixture_review as review


def protected(wealth,pending):return set(wealth['protected'])


def fixture():
    def base(post):
        days=['2020-06-26','2020-06-29','2020-06-30']+(['2020-07-01'] if post else [])
        return dict(last_processed_session=days[-1],feed=dict(history_sessions=260,session_index=99+len(days),
            seen_sessions={d:100+i for i,d in enumerate(days)},series={}),wealth_core={},ledger={},pending=[],
            last_known={},controller={'unchanged':'actual-clock-only'})
    zero,post=base(False),base(True);fullzero={'run':{'state':zero},'full_outer':'zero'}
    final={'full_outer':'qualified'};components=[{'checkpoint':{'state':post},'full_reference':'one'},
        {'full_reference':'two'}];contract={'source':'contract'}
    names={'sentinel/core/session.py','shared/stock_strategy_shared/wealth_core/feed.py',
        'shared/stock_strategy_shared/wealth_core/adapter.py','shared/stock_strategy_shared/wealth_core/state.py',
        'shared/stock_strategy_shared/wealth_core/state_restore_validation.py','shared/stock_strategy_shared/wealth_core/shares.py'}
    pins={n:'a'*64 for n in names}
    value=dict(schema='research.p01-iac-unit-synthetic-canonical-component/2',fixture_source_files=pins,
        fixture_contracts={},fixture_contexts={},target_cases={},post_event_new_unit_case=None,
        fixture_aggregate=dict(schema='research.p01-iac-unit-fixture-aggregate/1',expected_case_ids=list(review.CASE_IDS),
            attempted_case_ids=list(review.CASE_IDS),passed_case_ids=list(review.CASE_IDS),failed_cases=[],complete=True,all_passed=True),
        actual_reference_boundary=dict(schema='research.p01-iac-unit-unadmitted-reference-boundary/1',actual_components=components,
            qualifier_checkpoint=final,input_zero_checkpoint=fullzero,source_contract_sha256=review.digest(contract),
            actual_reference_records_preserved_before_fixtures=True,financial_authority=False,qualification_state_adopted=False))
    for case in review.CASE_IDS:
        ispost=case=='POST_EVENT_SOURCE_BUY';target=review.SOURCE if ispost else case.split('/')[0]
        role='DOLLAR_BUY_PENDING' if ispost else case.split('/')[1];b=post if ispost else zero
        plan=review.expected_plan(b,target,role);before=deepcopy(b);before.update(wealth_core={'protected':[target]},
            ledger={'synthetic':True},pending=[],last_known={target:10.},feed=review.expected_feed(plan));after=deepcopy(before)
        if ispost:value['post_event_new_unit_case']=dict(before=before,after=after)
        else:value['target_cases'][case]=dict(before=before,actual=after)
        value['fixture_contracts'][case]=dict(plan=plan,protected_security_ids=[target],before_state_sha256=review.digest(before),
            before_feed_sha256=review.digest(before['feed']),canonical_roundtrip=True,financial_authority=False,
            after_state_sha256=review.digest(after),after_feed_sha256=review.digest(after['feed']),after_protected_security_ids=[target],
            retained_current_marks=deepcopy(after['last_known']),canonical_after_roundtrip=True)
        value['fixture_contexts'][case]=dict(status='PASSED',phase=review.PHASE,before_state_sha256=review.digest(before),
            after_state_sha256=review.digest(after),financial_authority=False)
    kw=dict(input_zero_state=zero,reference_components=components,qualifier_checkpoint=final,input_zero_checkpoint=fullzero)
    return value,contract,{'successor_all_sources':deepcopy(pins)},post,kw


def run(data,validator=None,normalizer=deepcopy):
    value,contract,mapping,post,kw=data
    return (validator or review.validate_fixtures)(value,contract,mapping,post,normalizer,protected,**kw)


def refresh_case(data,case):
    value=data[0];post=case=='POST_EVENT_SOURCE_BUY';row=value['post_event_new_unit_case'] if post else value['target_cases'][case]
    before,after=row['before'],row['after'] if post else row['actual'];record=value['fixture_contracts'][case]
    record.update(before_state_sha256=review.digest(before),before_feed_sha256=review.digest(before['feed']),
        after_state_sha256=review.digest(after),after_feed_sha256=review.digest(after['feed']),retained_current_marks=deepcopy(after['last_known']))
    value['fixture_contexts'][case].update(before_state_sha256=review.digest(before),after_state_sha256=review.digest(after))


def test_all_nine_complete_feeds_boundaries_marks_and_normalized_envelopes():
    calls=[];data=fixture();before=deepcopy(data)
    def normalize(wire):calls.append(deepcopy(wire));return deepcopy(wire)
    result=run(data,normalizer=normalize)
    assert len(calls)==18 and result['synthetic_wires']==18 and data==before
    plan=review.expected_plan(data[3],review.SOURCE,'DOLLAR_BUY_PENDING');feed=review.expected_feed(plan)
    source=feed['series'][review.SOURCE]
    assert source['signal_closes'][-1]==10.*float('2.1584')
    assert source['signal_basis_anchor']==['2020-07-01',10.,source['signal_closes'][-1]]
    assert source['split_factor']==source['signal_closes'][-1]/10.


@pytest.mark.parametrize('kind',['anchor','array','clock','issuer','marks','unprotected','envelope','plan','contract','context','aggregate','boundary','zero','source'])
def test_mutated_complete_context_or_source_evidence_refuses(kind):
    data=fixture();value=data[0];case=review.CASE_IDS[0];row=value['target_cases'][case];before=row['before'];sid=case.split('/')[0]
    if kind=='anchor':before['feed']['series'][sid]['signal_basis_anchor'][-1]=99.
    if kind=='array':before['feed']['series'][sid]['raw_closes'].pop()
    if kind=='clock':before['feed']['session_index']+=1
    if kind=='issuer':before['feed']['series'][sid]['issuer_id']='wrong'
    if kind=='marks':before['last_known'][sid]=11.
    if kind=='unprotected':before['wealth_core']['protected'].append('absent-domain')
    if kind=='envelope':before['controller']['unchanged']='graft'
    if kind=='plan':value['fixture_contracts'][case]['plan']['instruments'][sid]['raw_price']=11.
    if kind=='contract':value['fixture_contracts'][case]['canonical_roundtrip']=False
    if kind=='context':value['fixture_contexts'][case]['status']='REFUSED'
    if kind=='aggregate':value['fixture_aggregate']['attempted_case_ids'].pop()
    if kind=='boundary':value['actual_reference_boundary']['qualifier_checkpoint']={'grafted':True}
    if kind=='zero':value['actual_reference_boundary']['input_zero_checkpoint']={'grafted':True}
    if kind=='source':value['fixture_source_files']['sentinel/core/session.py']='b'*64
    if kind in ('anchor','array','clock','issuer','marks','unprotected','envelope'):refresh_case(data,case)
    with pytest.raises((ValueError,KeyError)):run(data)


def modified_validator(label):
    fn=next(n for n in ast.parse(Path(review.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate_fixtures')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(v,ast.Constant) and v.value==label for v in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(review))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-fixture-record-predicate>','exec'),ns)
    return ns['validate_fixtures']


def test_complete_feed_guard_removal_accepts_mutated_anchor_falsifier():
    data=fixture();case=review.CASE_IDS[0];sid=case.split('/')[0];row=data[0]['target_cases'][case]
    for wire in (row['before'],row['actual']):wire['feed']['series'][sid]['signal_basis_anchor'][-1]=99.
    refresh_case(data,case)
    with pytest.raises(ValueError,match='ENTIRE_DECLARED_FEED'):run(data)
    assert run(data,modified_validator('FIXTURE_REVIEW_ENTIRE_DECLARED_FEED_ARRAYS_ANCHORS_AND_BASIS'))['synthetic_wires']==18


def test_nine_case_guard_removal_accepts_omitted_attempt_falsifier():
    data=fixture();data[0]['fixture_aggregate']['attempted_case_ids'].pop()
    with pytest.raises(ValueError,match='ALL_NINE_EXACT_ATTEMPTS'):run(data)
    assert run(data,modified_validator('FIXTURE_REVIEW_ALL_NINE_EXACT_ATTEMPTS_PASSED_NO_FAILURE'))['synthetic_wires']==18


def test_actual_frozen_function_adaptation_reverse_ast_and_no_financial_changes():
    raw=Path(review.previous.__file__).read_bytes();assert review.sha(raw)==review.SOURCE_SHA
    original={n.name:n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)}
    assert ast.dump(review._node('review'),include_attributes=False)==ast.dump(original['review'],include_attributes=False)
    synthetic=review._node('synthetic_component');changed=[]
    for node in ast.walk(synthetic):
        if isinstance(node,ast.Tuple) and all(isinstance(n,ast.Constant) for n in node.elts) and tuple(n.value for n in node.elts)==review.FIELDS:
            node.elts.pop();changed.append('projection')
    class UndoOpening(ast.NodeTransformer):
        def visit_Call(self,node):
            if isinstance(node.func,ast.Name) and node.func.id=='opening_equity':
                if isinstance(node.args[-1],ast.Constant):
                    return ast.parse("after['wealth_core']['cash']+sum(e['current_shares']*10. for e in actual)",mode='eval').body
                return ast.parse("after['wealth_core']['cash']+episodes[0]['current_shares']*post['raw_price']",mode='eval').body
            return self.generic_visit(node)
    synthetic=UndoOpening().visit(synthetic)
    assert changed==['projection'] and ast.dump(synthetic,include_attributes=False)==ast.dump(original['synthetic_component'],include_attributes=False)
    loaded=review._node('review_loaded');imports=[];calls=[]
    for node in ast.walk(loaded):
        if isinstance(node,ast.ImportFrom) and node.module=='p01_iac_unit_fixture_export':node.module='p01_iac_unit_export';imports.append(node)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='synthetic_component':
            assert [k.arg for k in node.keywords]==['input_zero_state','reference_components','qualifier_checkpoint','input_zero_checkpoint']
            node.keywords=[];calls.append(node)
    assert len(imports)==len(calls)==1
    assert ast.dump(loaded,include_attributes=False)==ast.dump(original['review_loaded'],include_attributes=False)
    # Compiling only defines functions: no hosted body/import/restore executes.
    assert callable(review._body('review_loaded'))


@pytest.mark.parametrize('kind',['BUY','CLOSE','POST_BUY'])
def test_exact_frozen_opening_audit_callsite_before_fees_and_predicate_removal(kind):
    sid=review.SOURCE if kind=='POST_BUY' else review.CHILD
    quantity=7 if kind=='CLOSE' else 0
    before=dict(wealth_core=dict(cash=50000.-70.07 if kind=='CLOSE' else 50000.,
        episodes={'0':dict(security_id=sid,current_shares=quantity)} if quantity else {}),ledger={'receivables':[]})
    current_quantity=0 if kind=='CLOSE' else 49
    after=dict(wealth_core=dict(cash=before['wealth_core']['cash']+69.93 if kind=='CLOSE' else 49509.51))
    opening=review.opening_equity(before,sid,10.)
    assert opening!=after['wealth_core']['cash']+current_quantity*10.
    def comparison(node):
        wanted="post['prefix']" if kind=='POST_BUY' else "row['audit']"
        return next(n for n in ast.walk(node) if isinstance(n,ast.Compare) and ast.unparse(n.left)==wanted)
    adapted=comparison(review._node('synthetic_component'))
    original=comparison(next(n for n in ast.parse(Path(review.previous.__file__).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='synthetic_component'))
    row=dict(audit=dict(prefix=dict(resolved_open_equity=opening),spinoff_audit=[]))
    post=dict(prefix=dict(resolved_open_equity=opening),raw_price=10.)
    ns=dict(vars(review),before=before,after=after,sid=sid,row=row,post=post,
        actual=[dict(current_shares=current_quantity)] if current_quantity else [],
        episodes=[dict(current_shares=current_quantity)])
    evaluate=lambda node:eval(compile(ast.fix_missing_locations(ast.Expression(node)),'<actual-prefix-audit-comparison>','eval'),ns)
    assert evaluate(adapted) is True and evaluate(original) is False
    if kind=='POST_BUY':post['prefix']['resolved_open_equity']=0.
    else:row['audit']['prefix']['resolved_open_equity']=0.
    assert evaluate(adapted) is False and evaluate(ast.Constant(True)) is True

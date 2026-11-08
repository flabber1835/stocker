"""Single-session source/reader falsifiers; all prices/states are synthetic."""
import ast
from copy import deepcopy
from pathlib import Path
import sys

import pytest

HERE=Path(__file__).parents[1]
sys.path.insert(0,str(HERE))
import p01_native_resume_review as review

SOURCE='369995575874917058';OTHER='984687283821901795'


def parent():
    return dict(sha256='PARENT',run={'input_sha256':'53c3b13673552dbf98263ab0272ac11c8951de619bf19e9ddf2020e59b01584a'})


def summary():
    p=parent()
    return dict(status='OWN627_NATIVE_EPOCH_AND_ONE_SESSION_QUALIFIED',component_transitions=1,
        qualified_through='2020-06-30',epoch_zero_outer_sha256=p['sha256'],original_input_sha256=p['run']['input_sha256'],
        original_inputs=11,source_epoch_boundary_reemitted=False,input_boundary_reemitted=False,
        financial_authority=False,financial_predecessor_authorized=False)


@pytest.mark.parametrize('field,value',[
    ('component_transitions',0),('component_transitions',2),('component_transitions',3),('component_transitions',True),
    ('qualified_through','2020-07-01'),('qualified_through',None),
    ('status','OWN627_NATIVE_EPOCH_AND_THREE_SESSIONS_QUALIFIED'),('input_boundary_reemitted',True)])
def test_q1_exact_integer_count_endpoint_and_status_are_mandatory(field,value):
    good=summary();review.one_session_summary(good,parent());good[field]=value
    with pytest.raises(ValueError,match='ONE_SESSION'):review.one_session_summary(good,parent())


def state():
    return dict(last_processed_session='2020-06-29',
        wealth_core=dict(episodes={'7':dict(security_id=OTHER,current_shares=7,exit_pending=True)},
                         unresolved_terminals={},terminal_pending_terms={},terminal_pending_sessions={}),
        pending=[dict(security_id=OTHER,kind='BUY',dollars=100)],
        ledger=dict(events=[],receivables=[dict(security_id=OTHER,amount=3,accrued_session='2020-06-29')]),
        median5={'selected':[SOURCE,OTHER]},
        feed={'series':{SOURCE:{'signal_basis_anchor':['2020-06-29',5,10]}}})


def closing_fixture():
    prior=state();after=deepcopy(prior);after['last_processed_session']='2020-06-30'
    after['pending'].append(dict(security_id=OTHER,kind='CLOSE',full='retained'))
    after['ledger']['events'].append(dict(security_id=OTHER,event_type='DIVIDEND_ACCRUED'))
    term={'security_id':SOURCE,'cash_per_share':9.,'kind':'CASH_MERGER'}
    bars={SOURCE:dict(security_id=SOURCE,raw_open=8.,raw_close=9.,split_ratio=1.,volume=100.),
          OTHER:dict(security_id=OTHER,raw_open=30.,raw_close=31.,split_ratio=1.,volume=200.)}
    path=[dict(session='2020-06-30',prior_checkpoint={'state':prior},checkpoint={'state':after},
               publication=dict(session='2020-06-30',terminal_events=[term],bars=list(bars.values())))]
    native=review.digest(term);hashes={'2020-06-30/'+sid:'ROW_'+sid for sid in bars}
    observations=[dict(session='2020-06-30',post_all11_terminal=term,native_term_sha256=native,
        actual_source_bars=bars,raw_source_row_sha256=hashes,proxy_equals_current_raw_close=True,source_volume_positive=True,
        phase='CLOSING_WITNESS_ONLY_NOT_LEGAL_CASH_OR_OPENING_FILL',packet_mutated_by_observer=False)]
    closing=[dict(session='2020-06-30',source_selected=True,prior_signal_basis_anchor=['2020-06-29',5,10],
        actual_terminal_witness=18.,expected_current_close_normalized=18.,current_close_equivalence=True,
        actual_canonical_kernel_callsite_verified=True,
        source_ledger_events_added=0,source_claims_or_pending_created=False,financial_state_or_input_modified_by_guard=False)]
    return path,observations,closing,bars,hashes,native


def test_q1_source_gate_does_not_restrict_other_security_holding_pending_exit_or_claim():
    args=closing_fixture();before=deepcopy(args)
    proof=review.closing_proxy(*args)
    assert proof['source_current_close_only'] and proof['source_ledger_events_added']==0
    assert args==before and review.source_scope(state())['unheld'] is True


@pytest.mark.parametrize('role',['holding','pending_BUY','pending_CLOSE','exit_flag','receivable','unresolved'])
def test_actual_source_roles_and_all_claims_refuse_before_proxy_settlement(role):
    value=state()
    if role in ('holding','exit_flag'):
        value['wealth_core']['episodes']['1']=dict(security_id=SOURCE,current_shares=1,exit_pending=role=='exit_flag')
    elif role.startswith('pending'):
        value['pending'].append(dict(security_id=SOURCE,kind=role.split('_')[1]))
    elif role=='receivable':value['ledger']['receivables'].append(dict(security_id=SOURCE,amount=1))
    else:value['wealth_core']['terminal_pending_terms'][SOURCE]={'incomplete':True}
    with pytest.raises(ValueError):review.source_scope(value)


@pytest.mark.parametrize('change',['missing_observation','duplicate_observation','missing_sensor','wrong_phase','opening_proxy','wrong_witness','source_cash','bar_drop','missing_actual_callsite'])
def test_actual_closing_gate_and_entire_source_preimage_cannot_be_omitted(change):
    args=list(deepcopy(closing_fixture()))
    if change=='missing_observation':args[1]=[]
    elif change=='duplicate_observation':args[1].append(deepcopy(args[1][0]))
    elif change=='missing_sensor':args[2]=[]
    elif change=='wrong_phase':args[1][0]['phase']='OPENING_CASH'
    elif change=='opening_proxy':args[0][0]['publication']['terminal_events'][0]['cash_per_share']=8.
    elif change=='wrong_witness':args[2][0]['actual_terminal_witness']=18.00000001
    elif change=='source_cash':args[0][0]['checkpoint']['state']['ledger']['events'].append(dict(security_id=SOURCE,cash_delta=9))
    elif change=='bar_drop':args[0][0]['publication']['bars'].pop()
    elif change=='missing_actual_callsite':del args[2][0]['actual_canonical_kernel_callsite_verified']
    with pytest.raises(ValueError):review.closing_proxy(*args)


def mutant(code):
    tree=ast.parse((HERE/'p01_native_resume_review.py').read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='closing_proxy')
    guards=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need'
            and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and n.args[1].value==code]
    assert len(guards)==1;guards[0].args[0]=ast.Constant(True);namespace=dict(vars(review))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-q1-proof-guard>','exec'),namespace)
    return namespace['closing_proxy']


def test_actual_missing_gate_and_wrong_witness_guard_removal_falsifiers():
    args=list(closing_fixture());args[1]=[]
    with pytest.raises(ValueError):review.closing_proxy(*args)
    assert mutant('ONE_ACTUAL_CLOSING_PROXY_GATE_REQUIRED')(*args)['source_current_close_only'] is True
    args=list(deepcopy(closing_fixture()));args[2][0]['actual_terminal_witness']=18.00000001
    with pytest.raises(ValueError):review.closing_proxy(*args)
    assert mutant('EXACT_ACTUAL_CURRENT_CLOSE_NORMALIZED_SENSOR_PROOF')(*args)['source_current_close_only'] is True


def test_source_proof_binds_entire_clock_contract_reused_qualification_and_records():
    clock={'actual_night_clock':'bound'};reused={'component_sha256':'frozen'};contract={'actual_kernel_ast':'bound'}
    value=dict(schema='research.p01-native-closing-source-proof/1',records=[],source_clock_qualification=clock,
        reused_action_qualification=reused,source_contract=contract,source_financial_files_unchanged=True)
    assert review.source_proof(value,clock,reused,contract)==[]
    for key in ('source_contract','source_clock_qualification','reused_action_qualification'):
        bad=deepcopy(value);bad[key]={'changed':True}
        with pytest.raises(ValueError):review.source_proof(bad,clock,reused,contract)
    bad=deepcopy(value);del bad['records']
    with pytest.raises(ValueError):review.source_proof(bad,clock,reused,contract)


def test_all_eight_actual_source_scope_falsifiers_required_without_mutation():
    proof=dict(schema='research.p01-native-scope-refusal-falsifiers/1',status='ALL_SCOPED_FALSIFIERS_REFUSED',
        tested=list(review.FALSIFIER_CASES),financial_authority=False,actual_original_state_unchanged=True)
    assert review.refusal_falsifiers(proof,review.FALSIFIER_CASES)==list(review.FALSIFIER_CASES)
    bad=deepcopy(proof);bad['tested'].pop()
    with pytest.raises(ValueError):review.refusal_falsifiers(bad,review.FALSIFIER_CASES)
    bad=deepcopy(proof);bad['actual_original_state_unchanged']=False
    with pytest.raises(ValueError):review.refusal_falsifiers(bad,review.FALSIFIER_CASES)


def test_exact_actual_producer_gzip_fields_source_contract_and_refusal_labels():
    tree=ast.parse((HERE/'p01_native_resume_run.py').read_bytes())
    functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
    def dictionaries(name):
        return [n for n in ast.walk(functions[name]) if isinstance(n,ast.Call)
                and isinstance(n.func,ast.Name) and n.func.id=='dict']
    q=[n for n in dictionaries('qualify') if {'actual_components','qualifier_checkpoint'}<={k.arg for k in n.keywords}]
    assert len(q)==1 and {k.arg for k in q[0].keywords}=={'actual_components','action_checks','pre_event_checkpoints',
        'inherited_native_scope_checks','native_seam_scope_checks','closing_proofs','qualifier_checkpoint',
        'financial_authority','qualification_state_adopted'}
    f=[n for n in dictionaries('economic') if 'attempted_components' in {k.arg for k in n.keywords}]
    assert len(f)==1 and {k.arg for k in f[0].keywords}=={'actual_components','attempted_components',
        'financial_authority','qualification_state_adopted'}
    source=dictionaries('source_proof');assert len(source)==1
    assert {k.arg for k in source[0].keywords}=={'schema','records','source_clock_qualification',
        'reused_action_qualification','source_contract','source_financial_files_unchanged'}
    labels=next(n.value for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='FALSIFIERS' for t in n.targets))
    assert ast.literal_eval(labels)==review.FALSIFIER_CASES
    source=(HERE/'p01_native_resume_review.py').read_text()
    assert 'actual-one-session-component.json.gz' in source and 'actual-financial-first-one-component.json.gz' in source
    assert 'actual-three-session-component.json.gz' not in source

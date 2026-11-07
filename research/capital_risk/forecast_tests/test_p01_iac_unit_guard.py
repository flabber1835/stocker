"""Pure scope/hook/source-AST tests; every role and price example is synthetic."""
import ast
from copy import deepcopy
from pathlib import Path
import os
import sys
from types import SimpleNamespace

import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_unit_guard as guard
import p01_iac_unit_component as component
from p01_iac_unit_contract import SOURCE,CHILD,OLD_MATCH,EVENT


def state():
    return dict(wealth_core=dict(episodes={'0':dict(security_id=CHILD,exit_pending=True,current_shares=7)},
        slots={'0':dict(reserved_for=None,reserved_ticker=None,reserved_issuer=None)},
        unresolved_terminals={},terminal_pending_terms={},terminal_pending_sessions={},terminal_carry_audit={}),
        pending=[dict(security_id=OLD_MATCH,operation='OPEN_SLOT_POSITION',intended_dollars='100')],
        ledger=dict(events=[],receivables=[dict(security_id=CHILD,amount='3')]),
        median5={'selected':[SOURCE]},feed={'series':{SOURCE:{'ticker':'SYNTHETIC_SOURCE'}}})


def test_unit_scope_is_pre_event_and_preserves_all_independent_target_roles():
    value=state();before=deepcopy(value);rows=guard.unit_scope(value,EVENT)
    assert rows[0]['independent_target_roles'][CHILD]['episodes']==value['wealth_core']['episodes']
    assert rows[0]['independent_target_roles'][OLD_MATCH]['pending']==value['pending']
    value['pending'].append(dict(security_id=SOURCE,operation='OPEN_SLOT_POSITION',intended_dollars='100'))
    assert guard.unit_scope(value,'2020-07-02')==[]
    with pytest.raises(ValueError,match='ANY_PENDING'):guard.unit_scope(value,EVENT)
    assert before['pending']==value['pending'][:-1]


def test_all_source_scope_negatives_refuse_without_mutating_original():
    original=state();copy=deepcopy(original)
    proof=component.scope_falsifiers(original)
    assert tuple(p['case'] for p in proof)==component.NEGATIVE_ROLES
    assert all(p['caller_unchanged'] for p in proof) and original==copy


def test_dangling_source_reservation_is_guarded_without_pending_or_holding():
    value=state();value['wealth_core']['slots']['0']['reserved_for']=SOURCE
    with pytest.raises(ValueError,match='RESERVATION'):guard.unit_scope(value,EVENT)


def test_source_pending_guard_removal_admits_bad_state_and_falsifier_detects_it(monkeypatch):
    tree=ast.parse(Path(guard.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='unit_scope')
    fn.body=[n for n in fn.body if not any(isinstance(k,ast.Constant)
        and k.value=='OLD_UNIT_SOURCE_ANY_PENDING_UNSUPPORTED' for k in ast.walk(n))]
    ns=dict(vars(guard));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<disposable-source-scope-guard-removal>','exec'),ns)
    bad=state();bad['pending'].append(dict(security_id=SOURCE,operation='OPEN_SLOT_POSITION'))
    assert ns['unit_scope'](bad,EVENT)
    monkeypatch.setattr(component,'unit_scope',ns['unit_scope'])
    with pytest.raises(ValueError,match='MISSING_ACTUAL_UNIT_SCOPE_FALSIFIER:source_future_buy'):
        component.scope_falsifiers(state())


def test_deferred_native_error_is_stopped_after_saved_current_before_prepare():
    subject=guard.UnitGuard.__new__(guard.UnitGuard);calls=[]
    subject.codec=SimpleNamespace(refusals={EVENT:{'reason':'SYNTHETIC_NATIVE_BASIS_MISMATCH'}})
    subject.refusals=[];subject.unknown_action=lambda packet:False
    subject.prior_saved=lambda prior,day:calls.append('canonical_saved_current')
    subject.original_prepare=lambda *args,**kwargs:calls.append('FORBIDDEN_PREPARE')
    packet=SimpleNamespace(day=EVENT,bars=[]);buffer=SimpleNamespace(current=packet)
    with pytest.raises(ValueError,match='BEFORE_PREPARE'):subject.prepare(buffer,None,1)
    assert calls==['canonical_saved_current']
    assert subject.refusals[-1]['current_saved_before_refusal'] is True


def test_missing_save_hook_falsifier_cannot_claim_saved_current():
    subject=guard.UnitGuard.__new__(guard.UnitGuard);subject.codec=SimpleNamespace(refusals={EVENT:{}})
    subject.refusals=[];subject.unknown_action=lambda packet:False
    subject.prior_saved=lambda *args:(_ for _ in ()).throw(ValueError('SYNTHETIC_NO_ACTUAL_CURRENT_SAVE'))
    with pytest.raises(ValueError,match='NO_ACTUAL_CURRENT_SAVE'):
        subject.prepare(SimpleNamespace(current=SimpleNamespace(day=EVENT,bars=[])),None,1)
    assert subject.refusals[-1]['current_saved_before_refusal'] is False


def test_exact_retained516_source_shape_and_fill_prefix_ast():
    source=os.environ.get('P01_IAC_SOURCE_PREIMAGES')
    extra=os.environ.get('P01_IAC_NORMALIZER_PREIMAGES')
    if source is None or extra is None:pytest.skip('explicit exact retained516 preimages required')
    def native_path(value):
        path=Path(value).resolve()
        return Path('\\\\?\\'+str(path)) if os.name=='nt' and not str(path).startswith('\\\\?\\') else path
    source,extra=native_path(source),native_path(extra)
    files={}
    for name in guard.MODULES:
        member=name.replace('/','__')+'.txt';path=extra/member
        if not path.exists():path=source/member
        files[name]=path.read_bytes()
    expected={n:guard.sha(raw) for n,raw in files.items()};proof=guard.source_shape(files,expected)
    assert proof['window_length']==85 and proof['defaults']['signal_basis_multiplier']==1.0
    adapter=ast.parse(files['shared/stock_strategy_shared/wealth_core/adapter.py'])
    fn=next(n for n in adapter.body if isinstance(n,ast.FunctionDef) and n.name=='step_session')
    cut=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call)
        and isinstance(n.value.func,ast.Name) and n.value.func.id=='decide')
    calls={n.func.id for stmt in fn.body[:cut] for n in ast.walk(stmt)
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
    assert {'apply_entry','apply_exit','apply_splits','apply_dividends'}<=calls and 'decide' not in calls
    wrong=dict(files);key='shared/stock_strategy_shared/wealth_core/feed.py'
    wrong[key]=wrong[key].replace(b'factor *= float(b.split_ratio)',b'factor += float(b.split_ratio)')
    with pytest.raises(ValueError,match='ACTUAL516'):guard.source_shape(wrong,expected)
    expected_wrong={n:guard.sha(raw) for n,raw in wrong.items()}
    with pytest.raises(ValueError,match='FACTOR_OPERATION_ORDER'):guard.source_shape(wrong,expected_wrong)

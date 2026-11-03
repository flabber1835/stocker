"""Pure role/source/stub checks only; every example position/price is synthetic."""
import ast
from copy import deepcopy
from dataclasses import dataclass,replace
import os
from pathlib import Path
import sys
from types import SimpleNamespace,ModuleType

import pytest

HERE=Path(__file__).parents[1]
sys.path.insert(0,str(HERE))
import p01_native_resume_contract as contract
import p01_native_resume_guard as guard
import p01_native_resume_run as run


def state():
    return dict(last_processed_session='2020-06-29',wealth_core=dict(episodes={
        '7':dict(security_id=contract.IAC,exit_pending=True,current_shares=7)},
        unresolved_terminals={},terminal_pending_terms={},terminal_pending_sessions={}),
        pending=[dict(security_id=contract.IAC,operation='OPEN_SLOT_POSITION',intended_dollars='11')],
        median5=dict(selected=[contract.SOURCE,contract.IAC]),
        ledger=dict(events=[],receivables=[dict(security_id=contract.IAC,amount='3')]),
        feed={'series':{contract.SOURCE:{'signal_basis_anchor':['2020-06-29',5,10]}}})


def test_only_affected_source_is_guarded_other_identity_and_claims_are_untouched():
    value=state();before=deepcopy(value)
    rows=guard.native_seam_scope(value,contract.END)
    assert len(rows)==1 and rows[0]['source_selected'] is True
    assert guard.native_seam_scope(value,'2020-07-01')==[]
    assert value==before


def test_each_scoped_falsifier_uses_noncanonical_copy_and_retains_actual_source():
    value=state();before=deepcopy(value);proof=run.scope_falsifiers(value)
    assert tuple(proof['tested'])==run.FALSIFIERS and proof['actual_original_state_unchanged'] is True
    assert proof['financial_authority'] is False and value==before


def test_source_future_buy_guard_removal_is_detected(monkeypatch):
    tree=ast.parse(Path(guard.__file__).read_bytes())
    function,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='native_seam_scope']
    function.body=[n for n in function.body if not any(isinstance(k,ast.Constant)
        and k.value=='NATIVE_SOURCE_ANY_PENDING_INTENT_UNSUPPORTED' for k in ast.walk(n))]
    scope=dict(vars(guard));exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),
        '<synthetic-guard-removal>','exec'),scope)
    bad=state();bad['pending'].append(dict(security_id=contract.SOURCE,operation='OPEN_SLOT_POSITION'))
    with pytest.raises(ValueError,match='ANY_PENDING'):guard.native_seam_scope(bad,contract.END)
    assert scope['native_seam_scope'](bad,contract.END)
    monkeypatch.setattr(run,'native_seam_scope',scope['native_seam_scope'])
    with pytest.raises(ValueError,match='MISSING_SCOPE_FALSIFIER_source_future_buy'):run.scope_falsifiers(state())


def test_ledger_schema_cannot_hide_unregistered_claim_container():
    value=state();value['ledger']['opaque_claims']=[]
    with pytest.raises(ValueError,match='LEDGER_CLAIM_SCHEMA'):guard.native_seam_scope(value,contract.END)


@dataclass(frozen=True)
class Term:
    security_id:str=contract.SOURCE
    cash_per_share:float=17.0


@dataclass(frozen=True)
class Bar:
    security_id:str=contract.SOURCE
    session:str=contract.END
    raw_close:float=17.0
    split_ratio:float=1.0
    volume:int=99


@dataclass(frozen=True)
class Packet:
    day:str=contract.END
    terminal:tuple=(Term(),)
    bars:tuple=(Bar(),Bar(security_id=contract.IAC))


def test_observer_returns_identical_packet_and_rejects_proxy_or_any_quote_mutation(monkeypatch):
    module=ModuleType('research.bounded_20y.run');module.vendor=lambda row:Bar(security_id=row['security_id'])
    monkeypatch.setitem(sys.modules,'research.bounded_20y.run',module)
    monkeypatch.setattr(guard,'NATIVE_SHA',guard.digest(guard.material(Term())))
    loaded=SimpleNamespace(sha256='synthetic-descriptor')
    binding=SimpleNamespace(objects=[SimpleNamespace(sha256=loaded.sha256)],parent={'repairs':[{'sha256':loaded.sha256}]})
    rows={contract.END+'/'+s:dict(security_id=s)
        for s in (contract.SOURCE,contract.IAC)}
    observer=guard.SourceObserver(binding,rows);observer.original=lambda packet,obj:packet
    packet=Packet();assert observer.apply(packet,loaded) is packet
    assert observer.records[0]['packet_mutated_by_observer'] is False
    with pytest.raises(ValueError,match='NATIVE_POST_ALL11'):
        observer.apply(replace(packet,terminal=(Term(cash_per_share=19.0),)),loaded)
    with pytest.raises(ValueError,match='QUOTE_FIELDS'):
        observer.apply(replace(packet,bars=(Bar(),Bar(security_id=contract.IAC,raw_close=19.0))),loaded)
    with pytest.raises(ValueError,match='CURRENT_POSITIVE'):
        monkeypatch.setattr(guard,'NATIVE_SHA',guard.digest(guard.material(Term(cash_per_share=19.0))))
        observer.apply(replace(packet,terminal=(Term(cash_per_share=19.0),)),loaded)


def test_witness_is_observed_only_at_exact_kernel_callsite_and_returns_original_dict(monkeypatch):
    monkeypatch.setattr(guard,'NATIVE_SHA',guard.digest(guard.material(Term())))
    reused=dict(target_independence_qualified=True,held_target_holding_qualified=True)
    subject=guard.NativeGuard(Path('/synthetic'),reused=reused)
    published=SimpleNamespace(session=contract.END,terminal_events=[Term()],bars=[Bar()])
    prior=SimpleNamespace(**state())
    result={contract.SOURCE:34.0};subject.original_witness=lambda **kw:result
    namespace={'subject':subject}
    exec('def advance_session(prior,published):\n return subject.witness(prior=prior,published=published)\n',namespace)
    subject.kernel=SimpleNamespace(advance_session=namespace['advance_session'])
    with pytest.raises(ValueError,match='EXACT_CANONICAL_KERNEL_CALLSITE'):
        subject.witness(prior=prior,published=published)
    assert subject.kernel.advance_session(prior,published) is result
    assert subject.witness_calls[0]['actual_terminal_witness']==34.0
    subject.original_witness=lambda **kw:{contract.SOURCE:35.0}
    with pytest.raises(ValueError,match='CURRENT_CLOSE_ONLY'):subject.kernel.advance_session(prior,published)


def test_scope_run_bound_precedes_any_archive_publication_or_advance():
    subject=guard.NativeGuard(Path('/synthetic'),reused=dict(target_independence_qualified=True,
        held_target_holding_qualified=True))
    subject.pre_event=lambda *args:pytest.fail('no July1 pre-event, publication or advance is allowed')
    with pytest.raises(ValueError,match='ONLY_JUNE30'):
        subject.advance(None,SimpleNamespace(session='2020-07-01'))


def test_exact_retained516_source_ast_hashes_and_order_falsifiers():
    root=os.environ.get('P01_NATIVE_SOURCE_PREIMAGES')
    if root is None:pytest.skip('exact retained516 source preimages require explicit read-only directory')
    files={name:(Path(root)/member).read_bytes() for name,member in guard.SOURCE_MODULES.items()}
    expected={name:guard.sha(raw) for name,raw in files.items()}
    proof=guard.source_shape(files,expected)
    assert proof['ordinary_plan_line']<proof['closing_witness_line']
    wrong=dict(files);key='sentinel/core/kernel.py';wrong[key]=wrong[key].replace(b'terminal_returns.values(',b'other.values(')
    with pytest.raises(ValueError,match='SOURCE_BYTES'):guard.source_shape(wrong,expected)
    wrong_expected={name:guard.sha(raw) for name,raw in wrong.items()}
    with pytest.raises(ValueError,match='AFTER_ORDINARY_SESSION_PLAN'):guard.source_shape(wrong,wrong_expected)


def test_public_spec_has_no_financial_admission_or_quote_payload_fields():
    spec=contract.specification()
    for key in ('reporting_precision','economics','stats','retries','holdings','positions','actual_roles','quote'):
        assert key not in spec
    assert spec['source_clock_qualification']['raw_html_sha256'] is None
    assert contract.END=='2020-06-30' and contract.MAXIMUM==1 and contract.FIRST==(contract.END,)

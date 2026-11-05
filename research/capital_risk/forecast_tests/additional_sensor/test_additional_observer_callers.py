"""Existing original caller adapter, two exact current-class instances, distinct output dirs."""
import importlib.util
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import sys
import pytest

import os
C=Path(os.environ.get('ADDITIONAL_SENSOR_DEPENDENCY_DIR',str(Path(__file__).resolve().parents[2])))
spec=importlib.util.spec_from_file_location('closed_actual_caller_test_helpers',C/'forecast_tests/retained_callers/test_retained_observer_callers.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

@pytest.fixture(autouse=True)
def fenced():
    fence=base.Fence();sys.meta_path.insert(0,fence)
    try:yield
    finally:sys.meta_path.remove(fence)

def setup(tmp_path):
    s=base.setup(tmp_path)
    # Both are the exact unchanged current ActualEvents class/method objects.
    retained=s.newns['ActualEvents'].__new__(s.newns['ActualEvents'])
    retained.__dict__.update(s.retained.__dict__)
    retained.out=tmp_path/'inherited-december-observation'
    s.retained=retained
    newer=s.newer
    newer.out=tmp_path/'new-seven-observation'
    new_terms=base.asdict(s.term);new_terms.update(session='2022-03-14',security_id='ADDITIONAL-ORDINARY-SYNTHETIC')
    newer.terms={(new_terms['session'],new_terms['security_id']):new_terms}
    s.new_term=type(s.term)(**new_terms)
    assert retained.terminal.__func__ is newer.terminal.__func__
    assert retained.advance.__func__ is newer.advance.__func__
    return s

def test_naive_same_source_class_still_refuses_inner_noncanonical_caller(tmp_path):
    s=setup(tmp_path)
    with s.retained,s.newer:
        with pytest.raises(ValueError,match='FUTURE_ONE_SELECTED_CASH_CALL_IN_ACTUAL_CANONICAL_STEP'):
            s.runtime.advance(s.run,s.published)
    assert len(s.calls)==1
    assert any(v.get('cash') and v['cash'][0]['actual_context_call'] is False for p,v in s.output)

def test_qualified_existing_adapter_observes_once_and_separates_output_origins(tmp_path):
    s=setup(tmp_path);original=s.newns['actual_terminal_call']
    with s.retained,s.newer:
        with s.dispatch['retained_terminal_callers']((object(),)):
            s.runtime.advance(s.run,s.published)
            s.runtime.advance(s.run,SimpleNamespace(session=s.new_term.session,term=s.new_term))
    records=[(p,v) for p,v in s.output if p.name.startswith('actual-future-event-') and v.get('passed') is True]
    assert len(s.calls)==2 and len(records)==2
    assert len({p for p,v in records})==2
    assert [p.parent.name for p,v in records]==['inherited-december-observation','new-seven-observation']
    assert all(len(v['cash'])==1 and v['cash'][0]['actual_context_call'] is True and
               len(v['order'])==1 for p,v in records)
    assert s.newns['actual_terminal_call'] is original
    assert s.terminal.apply_terminal is s.primitive and s.runtime.advance is s.advance

def test_duplicate_selected_economic_term_refused_by_existing_adapter(tmp_path):
    s=setup(tmp_path);s.newer.terms[s.term.session,s.term.security_id]=base.asdict(s.term)
    with s.retained,s.newer,s.dispatch['retained_terminal_callers']((object(),)):
        with pytest.raises(ValueError,match='ONLY_FOREIGN_UNSELECTED'):
            s.runtime.advance(s.run,s.published)

def test_changed_caller_step_code_refused_and_all_functions_restore(tmp_path):
    s=setup(tmp_path);original=s.newns['actual_terminal_call']
    with s.retained,s.newer:
        s.retained.step_code=(lambda:None).__code__
        with pytest.raises(ValueError):
            with s.dispatch['retained_terminal_callers']((object(),)):
                s.runtime.advance(s.run,s.published)
    assert s.newns['actual_terminal_call'] is original
    assert s.terminal.apply_terminal is s.primitive and s.runtime.advance is s.advance

def stock_setup(tmp_path):
    s=setup(tmp_path)
    term=base.asdict(s.term);term['kind']='CASH_PLUS_STOCK'
    s.term=type(s.term)(**term);s.published.term=s.term
    s.retained.terms={(s.term.session,s.term.security_id):term}
    s.state.to_dict=lambda:dict(episodes={},slots={})
    s.ledger.to_dict=lambda:dict(receivables=[])
    def primitive(state,terms,**kwargs):
        s.calls.append((state,terms,kwargs));return dict(applied=False,reason='NOT_HELD')
    s.terminal.apply_terminal=s.primitive=primitive
    names={'unheld_stock_postcondition','require_source_absent'}
    base.execute([n for n in base.tree('system_campaign_financial_future.py').body if isinstance(n,base.ast.FunctionDef) and n.name in names],s.newns)
    return s

def test_inner_stock_original_caller_pending_access_refuses_even_with_caller_bridge(tmp_path):
    s=stock_setup(tmp_path)
    with s.retained,s.newer,s.dispatch['retained_terminal_callers']((object(),)):
        with pytest.raises(KeyError,match='pending'):s.runtime.advance(s.run,s.published)
    assert len(s.calls)==1
    assert s.terminal.apply_terminal is s.primitive and s.runtime.advance is s.advance

def test_outermost_original_stock_observer_keeps_actual_pending_frame_and_noop_postcondition(tmp_path):
    s=stock_setup(tmp_path)
    with s.newer,s.retained,s.dispatch['retained_terminal_callers']((object(),)):
        s.runtime.advance(s.run,s.published)
    assert len(s.calls)==1
    passed=[(p,v) for p,v in s.output if v.get('passed') is True]
    assert len(passed)==1 and passed[0][0].parent.name=='inherited-december-observation'
    proof=passed[0][1]['stock'];assert len(proof)==1 and proof[0]['actual_context_call'] is True
    assert proof[0]['postcondition']==dict(actual_held=False,quantity=0,nominal_cash=0.)
    assert s.terminal.apply_terminal is s.primitive and s.runtime.advance is s.advance

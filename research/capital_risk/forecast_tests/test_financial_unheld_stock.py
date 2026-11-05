"""Exact canonical no-op observation for an unheld mixed consideration term."""
import ast
from copy import deepcopy
from dataclasses import make_dataclass
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
from research.capital_risk.forecast_tests.test_financial_native_preimage import without_guard


def fixture():
    before=dict(cash=100.,episodes={},slots={},terminal_pending_terms={},terminal_pending_sessions={},
                unresolved_terminals={},terminal_carry_audit={})
    ledger=dict(events=[],receivables=[])
    term=deepcopy(f.original_delivery_selection('P05','2018-10-31')[2][0]['added'])
    result=dict(applied=False,reason='NOT_HELD')
    return before,deepcopy(before),ledger,deepcopy(ledger),[],term,result,'OPEN'


def test_unheld_canonical_stock_noop_is_checked_and_counted_once():
    args=fixture();before=deepcopy(args)
    proof=f.unheld_stock_postcondition(*args)
    assert proof==dict(actual_held=False,quantity=0,nominal_cash=0.) and args==before
    term=args[5];record=dict(session=term['session'],stock=[dict(security_id=term['security_id'],
        actual_context_call=True,applied=False,unheld_noop=True,postcondition=proof)])
    f.actual_stock_phase(record,[term])


@pytest.mark.parametrize('change',['held','order','reserved','claim','pending_native','after_state','ledger','result','reason','phase'])
def test_noop_cannot_hide_a_holding_claim_or_financial_mutation(change):
    args=list(fixture());before,after,ledger,ledger_after,pending,term,result,phase=args;sid=term['security_id']
    if change=='held':before['episodes']['1']=dict(security_id=sid)
    elif change=='order':pending.append(dict(security_id=sid))
    elif change=='reserved':before['slots']['1']=dict(reserved_for=sid)
    elif change=='claim':ledger['receivables'].append(dict(security_id=sid))
    elif change=='pending_native':before['terminal_pending_terms'][sid]={}
    elif change=='after_state':after['cash']+=1.
    elif change=='ledger':ledger_after['events'].append(dict(event_type='CASH_MERGER'))
    elif change=='result':result['applied']=True
    elif change=='reason':result['reason']='OTHER'
    else:args[-1]='CLOSE'
    with pytest.raises(ValueError):f.unheld_stock_postcondition(*args)


def test_noop_postcondition_guard_removal_falsifier():
    args=list(fixture());args[1]['cash']+=1.
    with pytest.raises(ValueError):f.unheld_stock_postcondition(*args)
    assert without_guard('unheld_stock_postcondition','FUTURE_UNHELD_STOCK_EXACT_CANONICAL_NOOP')(*args)['actual_held'] is False


@pytest.mark.parametrize('change',['diagnostic','duplicate','missing_proof','nonzero','not_noop'])
def test_stock_phase_requires_one_actual_call_and_the_exact_zero_proof(change):
    args=fixture();term=args[5];proof=f.unheld_stock_postcondition(*args)
    item=dict(security_id=term['security_id'],actual_context_call=True,applied=False,unheld_noop=True,postcondition=proof)
    record=dict(session=term['session'],stock=[item])
    if change=='diagnostic':item['actual_context_call']=False
    elif change=='duplicate':record['stock'].append(deepcopy(item))
    elif change=='missing_proof':del item['postcondition']
    elif change=='nonzero':proof['quantity']=1
    else:item['unheld_noop']=False
    with pytest.raises(ValueError):f.actual_stock_phase(record,[term])


def test_actual_observer_delegates_once_and_actual_call_guard_has_a_falsifier(monkeypatch):
    pending=[]  # The real adapter's local pending list is observed through its frame.
    args=fixture();before,after,ledger,ledger_after,_,term,result,phase=args
    Terms=make_dataclass('Terms',[(k,type(v)) for k,v in term.items()]);terms=Terms(**term)
    state=SimpleNamespace(to_dict=lambda:deepcopy(before));book=SimpleNamespace(to_dict=lambda:deepcopy(ledger))
    observer=f.ActualEvents.__new__(f.ActualEvents);calls=[]
    observer.terms={(term['session'],term['security_id']):term};observer.scopes=[];observer.step_code=object()
    observer.terminal_original=lambda *a,**kw:(calls.append('canonical') or deepcopy(result))
    observer.current=dict(stock=[])
    monkeypatch.setattr(f,'actual_terminal_call',lambda *a:True)
    assert observer.terminal(state,terms,ledger=book,phase='OPEN')==result
    assert calls==['canonical'] and observer.current['stock'][0]['unheld_noop'] is True
    monkeypatch.setattr(f,'actual_terminal_call',lambda *a:False)
    with pytest.raises(ValueError,match='ACTUAL_CANONICAL_CALL'):
        observer.terminal(state,terms,ledger=book,phase='OPEN')
    tree=ast.parse(Path(f.__file__).read_bytes())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ActualEvents')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='terminal')
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value=='FUTURE_UNHELD_STOCK_ACTUAL_CANONICAL_CALL' for v in node.value.args):return ast.Pass()
            return self.generic_visit(node)
    ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[Remove().visit(fn)],type_ignores=[])),'<removed-actual-stock-call-guard>','exec'),ns)
    assert ns['terminal'](observer,state,terms,ledger=book,phase='OPEN')==result

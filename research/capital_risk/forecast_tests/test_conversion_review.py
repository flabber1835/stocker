"""Independent ownership review of a synthetic two-security conversion."""
import ast
import copy
from pathlib import Path
import pytest
from core_window_review import reconcile


def snapshot():
    events=[dict(event_type='BUY',security_id='OLD',session='2020-01-02',
        cash_before=50000,cash_delta=-100.1,cash_after=49899.9,
        shares_delta=10,price=10,fees=.1,detail={}),
        dict(event_type='CONVERSION',security_id='OLD',session='2020-01-03',
        cash_before=49899.9,cash_delta=50,cash_after=49949.9,
        shares_delta=-6,price=5,fees=0,
        detail=dict(shares_in=10,shares_delivered=4,delivered_security_id='NEW'))]
    return dict(wealth_core=dict(cash=49949.9,episodes={'slot':dict(security_id='NEW',current_shares=4)}),
        ledger=dict(events=events,receivables=[]),prices={'NEW':dict(raw_price=25,status='CURRENT')},
        resolved_equity=50049.9)


def test_cross_identity_conversion_and_same_identity_scale():
    value=snapshot();reconcile(value)
    value['ledger']['events'][1]['detail']['delivered_security_id']='OLD'
    value['wealth_core']['episodes']['slot']['security_id']='OLD'
    value['prices']['OLD']=value['prices'].pop('NEW');reconcile(value)


@pytest.mark.parametrize('mutation',('delivered','aggregate','state','negative'))
def test_conversion_economic_mutations_are_refused(mutation):
    value=snapshot();event=value['ledger']['events'][1]
    if mutation=='delivered':event['detail']['shares_delivered']=5
    elif mutation=='aggregate':event['shares_delta']=-5
    elif mutation=='state':value['wealth_core']['episodes']['slot']['current_shares']=5
    else:event['detail']['shares_in']=-1
    with pytest.raises(ValueError,match='REFUSED_'):reconcile(value)


def test_actual_old_reviewer_falsifier():
    """Removing the conversion branch recreates the actual historical refusal."""
    tree=ast.parse(Path(reconcile.__code__.co_filename).read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='reconcile')
    branch=next(n for n in ast.walk(function) if isinstance(n,ast.If)
        and isinstance(n.test,ast.Compare) and ast.unparse(n.test)=="kind == 'CONVERSION'")
    assert len(branch.orelse)==1 and isinstance(branch.orelse[0],ast.If)
    legacy=branch.orelse[0];branch.test=legacy.test;branch.body=legacy.body;branch.orelse=[]
    scope=dict(reconcile.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),
        '<removed-conversion-review>','exec'),scope)
    with pytest.raises(ValueError,match='REFUSED_LEDGER_SHARES'):scope['reconcile'](snapshot())

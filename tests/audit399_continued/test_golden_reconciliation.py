"""Read-only reconciliation assertions over independently executed immutable versions.

The historical source is 5afba080; the audited production source remains aff4461d.
These checks explain the old reference's cash gap and test the current clock.
They do not authorize a fixture re-pin or certify strategy correctness globally.
"""
import gzip,json
from decimal import Decimal as D
from pathlib import Path
import pytest
ROOT=Path('/evidence')

@pytest.fixture(scope='module')
def versions():
    return tuple(json.load(gzip.open(ROOT/f'golden-{name}.json.gz')) for name in ('historical','pinned'))

def test_historical_source_reproduces_retained_reference_exactly(versions):
    old,current=versions
    assert old['summary']['result_hash']=='5c1af5731f79c7029d0c92b82275ef3b2b84d2a4fed0afbdc32688dfb6103a89'
    assert old['summary']['state_hash']=='427baff03aa27870'
    assert old['summary']['ledger_hash']=='0cf335b69e5a0279'
    assert current['summary']['result_hash']=='11566dc3608fa06644d31aecb90f470ab3c2cec7075b9d32ab84e063a10ecaef'

def test_historical_input_values_are_preserved_with_explicit_new_defaults(versions):
    old,current=versions
    additions=[]
    allowed={'signal_close':None,'exchange':None,'exchange_authoritative':False,
             'last_session':None,'entitlement_aggregation':'HOLDER'}
    def compare(a,b,path=''):
        if isinstance(a,dict):
            assert isinstance(b,dict) and a.keys()<=b.keys(),path
            for k in a:compare(a[k],b[k],path+'/'+k)
            for k in b.keys()-a.keys():
                assert k in allowed and b[k]==allowed[k],(path,k,b[k])
                additions.append((path,k))
        elif isinstance(a,list):
            assert len(a)==len(b),path
            for i,(x,y) in enumerate(zip(a,b,strict=True)):compare(x,y,path+'/'+str(i))
        else:assert a==b,(path,a,b)
    compare(old['input'],current['input'])
    assert len(additions)==32395

@pytest.mark.parametrize('exit_index,slot,security',[(179,'5','SEC_HALTED'),(210,'3','SEC_STRANDED')])
def test_current_cooldown_starts_at_zero_and_admits_only_after_21_completed_sessions(versions,exit_index,slot,security):
    old,current=versions
    for age in range(21):
        row=current['trace'][exit_index+age]
        assert row['slots'][slot]['cooldown_sessions_elapsed']==age,(row['session'],row['slots'][slot])
        assert row['security_cooldowns'][security]==age
        assert not [o for o in row['admissions'] if str(o['slot_id'])==slot]
    due=current['trace'][exit_index+21]
    assert due['slots'][slot]['cooldown_sessions_elapsed'] is None
    assert [o for o in due['admissions'] if str(o['slot_id'])==slot]
    assert old['trace'][exit_index]['security_cooldowns'][security]==1
    assert [o for o in old['trace'][exit_index+20]['admissions'] if str(o['slot_id'])==slot]

def test_three_changed_buys_explain_entire_cash_difference(versions):
    old,current=versions
    old_events=old['result']['ledger'];new_events=current['result']['ledger']
    assert len(old_events)==len(new_events)==41
    changes=[];tol=D('0.0000001')
    for i,(a,b) in enumerate(zip(old_events,new_events,strict=True)):
        if a['event_type']=='BUY':
            assert b['event_type']=='BUY'
            ka=(a['session'],a['security_id'],a['shares_delta'],a['price'])
            kb=(b['session'],b['security_id'],b['shares_delta'],b['price'])
            debit=lambda e:D(str(e['shares_delta']))*D(str(e['price']))*D('1.001')
            assert abs(D(str(a['cash_delta']))+debit(a))<tol
            assert abs(D(str(b['cash_delta']))+debit(b))<tol
            if ka!=kb:changes.append((i,ka,kb,debit(b)-debit(a)))
        else:
            assert (a['event_type'],a['session'],a['security_id'],a['shares_delta']) == (b['event_type'],b['session'],b['security_id'],b['shares_delta'])
            assert abs(D(str(a['cash_delta']))-D(str(b['cash_delta'])))<tol
    assert [i for i,*_ in changes]==[35,36,39]
    assert [x[-1] for x in changes]==[D('239.57934'),D('-239.55932'),D('43.48344')]
    total=sum((x[-1] for x in changes),D(0))
    assert total==D('43.50346')
    observed=D(str(old['summary']['cash']))-D(str(current['summary']['cash']))
    assert abs(observed-total)<tol
    print(json.dumps({'changed_buys':changes,'exact_additional_spend':str(total),'observed_cash_difference':str(observed)},default=str))

def test_ex_date_nav_includes_earned_unsettled_receivable(versions):
    old,current=versions
    a,b=old['trace'][155],current['trace'][155]
    accrual=next(e for e in current['result']['ledger'] if e['event_type']=='DIVIDEND_ACCRUED')
    oracle=D('334')*D('0.50')
    assert oracle==D('167')
    assert D(str(b['receivables']))==oracle
    assert abs(D(str(b['resolved_equity']))-D(str(a['resolved_equity']))-oracle)<D('0.0000001')
    assert not a['admissions'] and not b['admissions']
    assert current['trace'][156]['receivables']==0
    assert abs(D(str(current['trace'][156]['resolved_equity']))-D(str(old['trace'][156]['resolved_equity'])))<D('0.0000001')

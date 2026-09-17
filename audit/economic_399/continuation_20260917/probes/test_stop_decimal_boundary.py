"""Audit-only full canonical witness for the inclusive 30% stop boundary."""
import json
from decimal import Decimal
import pytest
from test_rounded_nav import canonical_two_days
from sentinel.core.session import PublishedSession, SessionState
from sentinel.core.kernel import advance_session
from sentinel.strategy import production_strategy
from sentinel.feed import calendar
from stock_strategy_shared.wealth_core.feed import VendorBar


def _day(env,meta,session,sid_close, sid_open=None):
    cfg,identity=production_strategy()
    all_days=calendar.previous_sessions('2026-08-11',253)[:-1]+calendar.sessions_in_range('2026-08-11',session)
    spy={d:100+i*.05 for i,d in enumerate(all_days)}
    days=calendar.previous_sessions(session,210)
    bars=[VendorBar(session=session,security_id=sid,ticker=m.ticker,
        raw_open=(sid_open if sid_open is not None else sid_close) if sid=='0' else 100.,
        raw_close=sid_close if sid=='0' else 100.,volume=1e6,
        signal_close=sid_close if sid=='0' else 100.) for sid,m in meta.items()]
    published=PublishedSession(session,7,bars,meta,{s:'Sector' for s in meta},[spy[d] for d in days],
        spy_sessions=days,spy_expected_sessions=days)
    before=json.loads(json.dumps(env.to_dict()))
    result=advance_session(SessionState.from_dict(before),published,controller_config=cfg,strategy_identity=identity)
    assert env.to_dict()==before
    return SessionState.from_dict(json.loads(json.dumps(result.to_dict())))

@pytest.mark.parametrize('closing_price,oracle_exit',[(70.69,True),(70.70,True),(70.71,False)])
def test_inclusive_stop_from_owned_peak_through_next_raw_open(closing_price,oracle_exit):
    env,meta,_=canonical_two_days(0.)
    peak=_day(env,meta,'2026-08-13',101.)
    episode=next(ep for ep in peak.wealth_core['episodes'].values() if ep['security_id']=='0')
    assert episode['episode_peak_split_adjusted_close']==101.
    assert Decimal(str(closing_price)) <= Decimal('101')*Decimal('0.7') if oracle_exit else Decimal(str(closing_price)) > Decimal('101')*Decimal('0.7')
    # Restart before the stop decision, then again before next-session execution.
    stopped=_day(peak,meta,'2026-08-14',closing_price)
    ep=next(ep for ep in stopped.wealth_core['episodes'].values() if ep['security_id']=='0')
    observed=bool(ep['exit_pending'])
    assert observed is (closing_price<70.70)
    assert sum(p['security_id']=='0' for p in stopped.pending)==int(observed)
    next_state=_day(stopped,meta,'2026-08-17',60.,60.)
    owned=sum(ep['current_shares'] for ep in next_state.wealth_core['episodes'].values() if ep['security_id']=='0')
    # Independent raw-open liquidation oracle: 10 shares * $60 less 10bp costs.
    oracle_cash=Decimal(10)*Decimal(60)*(Decimal(1)-Decimal('0.001')) if oracle_exit else Decimal(0)
    observed_cash=Decimal(str(next_state.wealth_core['cash']))
    assert owned==(0 if observed else 10)
    assert observed_cash==(Decimal('599.4') if observed else Decimal(0))
    if closing_price==70.70:
        assert oracle_exit and not observed
        assert observed_cash-oracle_cash==Decimal('-599.4')
        assert owned==10
    print('STOP_ORACLE',dict(peak='101.00',close=str(closing_price),float_threshold=101*.7,
          oracle_exit=oracle_exit,production_exit=observed,next_owned=owned,
          oracle_next_cash=str(oracle_cash),production_next_cash=str(observed_cash)))

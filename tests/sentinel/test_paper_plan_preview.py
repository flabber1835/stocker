from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import paper_plan_preview as preview, web_push
from sentinel.panel import model, render

NOW=datetime(2026,10,13,22,tzinfo=timezone.utc)


def plan():
    return dict(cycle_id='c'*64,plan_id='p'*64,decision_session=date(2026,10,13),
        effective_session=date(2026,10,14),execute_at=NOW+timedelta(hours=15,minutes=31),
        created_at=NOW,target_basket={'one':'12','two':'0','three':'5'})


def project(positions=None, observation_at=NOW, selected=None, **kwargs):
    return preview.project(plan=selected or plan(),positions={'one':'2','two':'3','three':'5'}
        if positions is None else positions,observation_at=observation_at,
        tickers={'one':'ONE','two':'TWO','three':'THREE'},now=NOW,**kwargs)


def test_proposed_buys_sells_and_holds_use_saved_quantities():
    value=project()
    assert (value.buys,value.sells,value.trades)==(1,1,2)
    assert [(x.action,x.change_quantity) for x in value.legs]==[
        ('BUY',Decimal(10)),('HOLD',Decimal(0)),('SELL',Decimal(-3))]


@pytest.mark.parametrize('age', [None,timedelta(minutes=10,seconds=1),timedelta(seconds=-1)])
def test_stale_missing_future_broker_observation_cannot_invent_trades(age):
    value=project(observation_at=NOW-age if age is not None else None)
    assert value.trades==0
    assert all(x.current_quantity is None and x.change_quantity is None and x.action=='UNAVAILABLE' for x in value.legs)


@pytest.mark.parametrize('quantity', ['NaN','Infinity','-1','1e100',True])
def test_malformed_plan_quantities_are_not_zero_or_trades(quantity):
    selected=plan();selected['target_basket']['one']=quantity
    with pytest.raises(ValueError):project(selected=selected)


def test_opening_dollars_do_not_become_invented_share_orders():
    selected=plan();selected['target_basket']['one']='0'
    selected['opening_intents']=dict(kind='plan-opening-intents/v1',plan_id=selected['plan_id'],
        plan_fingerprint='a'*64,intents=[dict(security_id='one',slot_id=0,intended_dollars='2000')])
    value=project(selected=selected,positions={})
    leg=next(x for x in value.legs if x.security_id=='one')
    assert leg.action=='BUY' and leg.opening_dollars==2000 and leg.change_quantity is None
    row=model.Row('paper_plan','Next paper plan','ready',paper_plan=value,valid_until=value.execute_at)
    html=render._paper_plan_html(row,NOW)
    assert '2026-10-14' in html and '06:31 AM Pacific' in html
    assert 'Sized at open' in html and '$2000 at open' in html
    assert render._paper_plan_html(row,value.execute_at+timedelta(seconds=1))==''


def test_duplicate_opening_slots_cannot_announce_two_buys():
    selected = plan()
    selected['target_basket']['one'] = '0'
    selected['opening_intents'] = dict(kind='plan-opening-intents/v1', plan_id=selected['plan_id'],
        plan_fingerprint='a'*64, intents=[dict(security_id=sid, slot_id=0, intended_dollars='2000')
                                        for sid in ('one','two')])
    with pytest.raises(ValueError, match='contradictory'):
        project(selected=selected, positions={})


def test_plan_view_escapes_ticker_and_has_no_order_action():
    value=project();value.legs[0]=value.legs[0].model_copy(update={'ticker':'<script>attack</script>'})
    html=render._paper_plan_html(model.Row('paper_plan','Plan','ready',paper_plan=value),NOW)
    assert '<script>attack</script>' not in html and '&lt;script&gt;' in html
    assert '<form' not in html and 'type="submit"' not in html
    assert 'proposed changes' in html and 'No orders' in html


def test_plan_notification_is_distinct_from_a_fill_and_payload_is_bounded():
    alert=SimpleNamespace(event_type='PAPER_PLAN_READY',severity='INFO',alert_id='a'*64,
        payload={'effective_session':'2026-10-14','reason':'2 proposed buys; no orders submitted'})
    value=web_push.notification_payload(alert)
    assert value['title']=='Paper trades planned for 2026-10-14'
    assert 'proposed' in value['body'] and 'filled' not in value['title']
    assert value['url']=='/' and value['tag']==alert.alert_id

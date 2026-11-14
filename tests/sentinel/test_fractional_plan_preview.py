"""Dollar preview uses saved policy/valuation; it never asserts broker eligibility."""
from copy import deepcopy
from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest

from sentinel import paper_plan_preview as preview
from sentinel.execution.market_buy_policy import FRACTIONAL_MODE, MarketBuyPolicy
from sentinel.panel import intent_memo, model, overview, render
from tests.sentinel.test_paper_plan_preview import original_authority, NOW


def inputs():
    plan, authority = original_authority()
    plan.update(account_nav='10000', target_exposure='1',
        target_basket={'mtd':'0', 'crl':'0', 'hold':'2.125', 'sell':'0'},
        opening_intents=[dict(security_id='mtd',slot_id=0,intended_dollars='1341.19'),
                         dict(security_id='crl',slot_id=1,intended_dollars='1338.67')])
    authority.update(market_buy_policy_sha256=MarketBuyPolicy(fractional=True).fingerprint(),
        decision_session=plan['decision_session'].isoformat(),
        marks={'mtd':'1756.29','crl':'341.34','hold':'100','sell':'20'},
        held_share_targets={'targets':{'hold':'2.125'}},
        shadow_state={'last_evidence':{'wealth_core':{'estimated_equity':'10000'}}},
        tickers={'mtd':'MTD','crl':'CRL','hold':'HELD','sell':'EXIT'})
    authority['broker_observation']['positions'] = [
        dict(instrument={'security_id':'hold','symbol':'HELD'},quantity='2.125'),
        dict(instrument={'security_id':'sell','symbol':'EXIT'},quantity='3.654321987')]
    return plan, authority


def test_monday_dollar_preview_and_hold_exit_quantities(monkeypatch):
    plan, authority = inputs()
    original = deepcopy((plan, authority))
    monkeypatch.setenv('SENTINEL_PAPER_BUY_POLICY', 'PROTECTED_LIMIT_DAY_V1')
    result = preview.project_original_intent(plan, authority)
    assert result.buy_policy == FRACTIONAL_MODE
    legs = {x.ticker:x for x in result.legs}
    assert (legs['MTD'].purchase_notional, legs['CRL'].purchase_notional) == (
        Decimal('1340.19'),Decimal('1337.67'))
    assert legs['MTD'].change_quantity is None
    assert legs['HELD'].action == 'HOLD' and legs['HELD'].target_quantity == Decimal('2.125')
    assert legs['EXIT'].action == 'SELL' and legs['EXIT'].change_quantity == Decimal('-3.654321987')
    assert (plan, authority) == original
    assert preview.project_original_intent(plan, intent_memo.projection(authority)) == result
    html = overview._leg_html(legs['MTD'], ())
    assert '$1,340.19 market order' in html and 'estimated shares' not in html
    row = model.Row('paper_plan','Plan','ready',paper_plan=result)
    card = overview._plan_html(SimpleNamespace(now=NOW, row=lambda key: row if key=='paper_plan' else None))
    assert '$1,340.19 market order' in card and '$1,337.67 market order' in card
    assert 'Buy limits' not in card and 'whole-share market orders apply' in card
    detail = render._paper_plan_html(row, NOW)
    assert '$1340.19 market order' in detail and 'whole-share market orders' in detail
    assert '3.654321987' in detail


def test_dollar_preview_respects_scaled_account_allocation_and_fee_floor():
    plan, authority = inputs()
    plan['account_nav'] = '5000'
    plan['target_exposure'] = '0.55'
    result = preview.project_original_intent(plan, authority)
    mtd = next(x for x in result.legs if x.ticker == 'MTD')
    assert mtd.opening_dollars == Decimal('368.82')
    assert mtd.purchase_notional == Decimal('367.82')


def test_missing_reference_is_unavailable_not_a_whole_share_skip():
    plan, authority = inputs()
    authority['marks'].pop('mtd')
    mtd = next(x for x in preview.project_original_intent(plan, authority).legs if x.ticker == 'MTD')
    assert mtd.action == 'UNAVAILABLE' and mtd.purchase_notional is None
    assert 'Sizing evidence unavailable' in overview._leg_html(mtd, ())


@pytest.mark.parametrize('budget,action,notional', [('1.99','SKIP',None),('2.00','BUY','1.00')])
def test_minimum_buy_includes_fee_headroom(budget, action, notional):
    plan, authority = inputs()
    plan['opening_intents'][0]['intended_dollars'] = budget
    mtd = next(x for x in preview.project_original_intent(plan, authority).legs if x.ticker == 'MTD')
    assert mtd.action == action
    assert mtd.purchase_notional == (None if notional is None else Decimal(notional))


def test_rounding_is_independent_of_ambient_decimal_precision():
    plan, authority = inputs()
    expected = preview.project_original_intent(plan, authority)
    with localcontext() as ctx:
        ctx.prec = 7
        assert preview.project_original_intent(plan, authority) == expected


def test_preview_policy_is_not_inferred_from_current_environment(monkeypatch):
    plan, authority = original_authority()
    monkeypatch.setenv('SENTINEL_PAPER_BUY_POLICY', FRACTIONAL_MODE)
    assert preview.project_original_intent(plan, authority).buy_policy is None


def test_unknown_saved_policy_refuses():
    plan, authority = inputs()
    authority['market_buy_policy_sha256'] = 'f'*64
    with pytest.raises(ValueError, match='saved plan BUY policy is unknown'):
        preview.project_original_intent(plan, authority)


def test_saved_policy_guard_falsifier(monkeypatch):
    real = preview.sizing_display_inputs
    monkeypatch.setattr(preview, 'sizing_display_inputs', lambda authority: real(dict(authority,
        market_buy_policy_sha256=MarketBuyPolicy(fractional=True).fingerprint())))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_unknown_saved_policy_refuses()

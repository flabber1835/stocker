"""Independent exact grouped-action ledger checks; no financial state mutation."""
from fractions import Fraction
import math

from p01_factual_batch_contract import need


def number(value):
    need(type(value) in (int,float) and math.isfinite(value), 'FINITE_CANONICAL_LEDGER_NUMBER')
    return Fraction(str(value))


def action_flows(events, actions):
    """Audit dated legal components against canonical cash/stock postings."""
    result=[]
    for action in actions:
        sid=action['source_security_id']
        need(not any(e['security_id']==sid and e['session']>'2020-02-04' and e['event_type'] in
                     ('WRITE_OFF','TERMINAL_LIQUIDATION','TERMINAL_MARK') for e in events),
             'REGISTERED_LEGAL_ACTION_CANNOT_USE_PROXY_OR_WRITE_OFF')
        rows=[e for e in events if e['security_id']==sid and e['session']>'2020-02-04'
              and e['event_type'] in ('CASH_MERGER','CONVERSION')]
        if not rows:continue
        need(action['clock_scope']=='KNOWN_COMPLETION_BEFORE_OPEN'
             and action['held_representation_scope']=='CANONICAL_EXACT_INTEGRAL_ONLY',
             'UNHELD_ONLY_CLOCK_CANNOT_CREATE_PORTFOLIO_ENTITLEMENT')
        quantity=Fraction();delivered=Fraction();cash_exact=Fraction();recorded_cash=Fraction();allocations=[]
        for event in rows:
            need(event['session']==action['economic_session'] and event['ticker']==action['source_ticker']
                 and event['detail']['reference']==action['primary_reference'] and number(event['fees'])==0,
                 'EXACT_ACTION_DATE_IDENTITY_REFERENCE_NO_INVENTED_FEE')
            if action['kind']=='CASH_MERGER':
                q=number(event['detail']['shares']);price=Fraction(action['cash_per_share'])
                need(event['event_type']=='CASH_MERGER' and event['reason']=='CASH_MERGER'
                     and q>0 and number(event['shares_delta'])==-q and event['price']==float(price)
                     and event['cash_delta']==float(q)*float(price),
                     'EXACT_ORDINARY_CASH_CANONICAL_BINARY64_POST_NOT_MARKET_QUOTE')
                cash_exact+=q*price
            else:
                detail=event['detail'];q=number(detail['shares_in']);ratio=Fraction(action['exchange_ratio'])
                shares=number(detail['shares_delivered']);legal_cash=Fraction(action['cash_per_share'] or '0')
                need(event['event_type']=='CONVERSION' and event['reason']==action['kind'] and q>0
                     and detail['delivered_security_id']==action['delivered_security_id']
                     and detail['delivered_ticker']==action['delivered_ticker']
                     and detail['exchange_ratio_exact']==action['exchange_ratio']
                     and shares==q*ratio and Fraction.from_float(float(shares))==q*ratio
                     and detail['exact_fractional_entitlement']=='0' and detail['cash_in_lieu']==0
                     and event['price']==(None if action['cash_per_share'] is None else float(legal_cash))
                     and number(event['shares_delta'])==shares-q,
                     'EXACT_CANONICAL_STOCK_DELIVERY_CASH_LEG_AND_ZERO_UNSUPPORTED_FRACTION')
                delivered+=shares;cash_exact+=q*legal_cash;allocations.append((q,shares,event))
            quantity+=q
            need(number(event['cash_before'])>=0 and number(event['cash_after'])>=0
                 and number(event['cash_delta'])>=0
                 and event['cash_after']==event['cash_before']+event['cash_delta'], 'EXACT_ACTION_LEDGER_CASH_CHAIN')
            recorded_cash+=Fraction.from_float(float(event['cash_delta']))
        if allocations:
            whole=quantity*Fraction(action['exchange_ratio']);so_far=cash_so_far=0.0
            legal_cash=Fraction(action['cash_per_share'] or '0')
            need(Fraction(str(float(legal_cash)))==legal_cash, 'LEGAL_CASH_PRESERVED_BY_EXISTING_TERM_NORMALIZATION')
            total_cash=quantity*legal_cash;cumulative_weight=Fraction();first_cash=allocations[0][2]['cash_before']
            previous_cash=first_cash
            need(whole.denominator==1 and Fraction.from_float(float(whole))==whole,
                 'EXACT_HOLDER_INTEGRAL_ENTITLEMENT_NO_CIL_PRICE')
            for index,(q,shares,event) in enumerate(allocations):
                actual=float(whole)-so_far if index==len(allocations)-1 else float(whole*q/quantity)
                need(Fraction.from_float(actual)==shares, 'EXACT_CANONICAL_EPISODE_ALLOCATION_WITHOUT_ROUNDING')
                so_far+=actual
                weight=q/quantity;cumulative_weight+=weight
                episode_cash=float(total_cash)-cash_so_far if index==len(allocations)-1 else float(total_cash*weight)
                after=first_cash+float(total_cash*cumulative_weight)
                need(math.isfinite(after) and event['cash_before']==previous_cash
                     and event['cash_delta']==after-event['cash_before']
                     and event['detail']['cash_consideration']==round(episode_cash,10),
                     'EXACT_FROZEN_CUMULATIVE_CASH_ALLOCATION_SUBTRACTION_AND_DETAIL_PRESENTATION')
                cash_so_far+=episode_cash;previous_cash=after
            need(Fraction.from_float(so_far)==whole, 'EXACT_CANONICAL_HOLDER_DELIVERY_CONSERVATION')
        result.append(dict(action_id=action['action_id'],session=action['economic_session'],
            source_shares_exact=str(quantity),delivered_shares_exact=str(delivered),legal_cash_exact=str(cash_exact),
            recorded_cash_delta_exact=str(recorded_cash),cash_floating_residual_exact=str(recorded_cash-cash_exact),
            recorded_cash_delta_binary64_hexes=[float(e['cash_delta']).hex() for e in rows],
            cash_source_expression=('initial_cash + float(total_legal_cash * cumulative_weight); '
                'delta = allocation_cash_after - state_cash; detail = round(episode_cash_leg, 10)'
                if allocations else 'delta = episode_current_shares * per_share'),
            source_cash_scalars_finite_nonnegative=True,
            ledger_events=len(rows),market_quote_invented=False,fraction_or_cash_rounding_added=False))
    return result


def reconcile(snapshot, quote, actions=None, ordinary=None):
    from p01_celg_bridge_accounting import right_flow
    if ordinary is None:
        from core_window_review import reconcile as ordinary
    if actions is None:
        from p01_factual_batch_contract import facts
        actions=facts()['records']
    historical=right_flow(snapshot['ledger']['events'],quote)
    grouped=action_flows(snapshot['ledger']['events'],actions)
    ordinary(snapshot)
    return dict(historical_celg_right_flow=historical,grouped_action_flows=grouped)

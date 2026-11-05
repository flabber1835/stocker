"""Independent exact entitlement/cash audit using the authenticated actual input."""
from decimal import Decimal
from fractions import Fraction
from p01_celg_bridge_gate import need

SID='11651249425833422';BMY='578964201416671255';DAY='2019-11-21'


def right_flow(events,quote):
    rows=[v for v in events if v['event_type'] in ('MERGER_RIGHT_RECEIPT','MERGER_RIGHT_LIQUIDATION')]
    if not rows:return None
    need(len(rows)==2 and [v['event_type'] for v in rows]==['MERGER_RIGHT_RECEIPT','MERGER_RIGHT_LIQUIDATION'],
         'INDEPENDENT_EXACT_ONE_RIGHT_RECEIPT_SALE_PAIR')
    received,sold=rows;body=received['detail']
    need(body==sold['detail'] and body['schema']=='canonical.merger-right-ledger-detail/1'
         and body['right_quote']==quote and body['right_identity']==quote['identity']
         and quote['authority']=='AUTHENTICATED_RETAINED_ALPACA_RAW_SIP_INPUT'
         and quote['observed_market_data'] is True and quote['session']==DAY,
         'INDEPENDENT_COMPLETE_ACTUAL_QUOTE_IDENTITY_AND_PROVENANCE')
    amount=Fraction(body['right_units_exact']);source=Fraction(body['source_shares_exact']);cost=Fraction(body['cost_bps'])
    need(amount==source and amount>0 and amount.denominator==1 and body['right_units_per_source']=='1'
         and 0<=cost<10000 and body['source_security_id']==SID and body['source_ticker']=='CELG'
         and body['legal_completion_day']=='2019-11-20' and body['valuation_session']==DAY,
         'INDEPENDENT_INTEGRAL_ENTITLEMENT_AND_DISTINCT_CLOCKS')
    need(all(v['session']==DAY and v['security_id'] is None and v['ticker']=='BMYRT' for v in rows)
         and type(received['shares_delta']) is int and type(sold['shares_delta']) is int
         and received['shares_delta']==amount and sold['shares_delta']==-amount,
         'INDEPENDENT_OPAQUE_RIGHT_IDENTITY_AND_ZERO_RESIDUAL')
    need(received['cash_delta']==0 and received['fees']==0 and received['cash_before']==received['cash_after']
         and received['reason']=='MERGER_RIGHT_CONTRACTUAL_ENTITLEMENT','INDEPENDENT_RECEIPT_CANNOT_INVENT_CASH')
    price=Fraction(quote['raw_open']);gross=amount*price;fees=gross*cost/10000;net=gross-fees
    need(received['price']==float(price)==sold['price'] and sold['cash_delta']==float(net)
         and sold['fees']==float(gross)-float(net) and sold['cash_before']==received['cash_after']
         and sold['cash_after']==sold['cash_before']+sold['cash_delta']
         and sold['reason']=='INVOLUNTARY_MERGER_RIGHT_LIQUIDATED_AT_OPEN'
         and abs(Decimal(str(sold['fees']))-Decimal(str(float(fees))))<=Decimal('0.0000001'),
         'INDEPENDENT_EXACT_CANONICAL_NET_SALE_AND_SEPARATE_FEE')
    need(body['gross_value_exact']==str(gross) and body['gross_value']==float(gross),
         'INDEPENDENT_GROSS_RIGHT_DISTINCT_FROM_LEGAL_CASH')
    conversions=[v for v in events if v['event_type']=='CONVERSION' and v['security_id']==SID and v['session']==DAY]
    quantity=Fraction()
    for event in conversions:
        info=event['detail'];q=Fraction(str(info['shares_in']));delivered=Fraction(str(info['shares_delivered']))
        need(info['delivered_security_id']==BMY and info['delivered_ticker']=='BMY'
             and info['exchange_ratio_exact']=='1' and q==delivered>0 and event['price']==50.0
             and info['reference']==body['reference'] and info['cash_consideration']==float(q*50),
             'INDEPENDENT_CANONICAL_ONE_BMY_AND_SEPARATE_LEGAL_CASH_50')
        quantity+=q
    need(quantity==amount,'INDEPENDENT_RIGHT_EQUALS_ACTUAL_CONVERTED_SOURCE_SHARES')
    return dict(schema='research.p01-celg-actual-independent-right-flow/1',units=str(amount),residual_units='0',
        legal_merger_cash_exact=str(quantity*50),gross_right_open_value_exact=str(gross),
        right_sale_fee_exact=str(fees),net_right_sale_cash_exact=str(net),
        separate_closing_sensor_quote=quote['raw_close'],quote_input_identity_sha256=quote['input_identity_sha256'],
        actual_provider_response_authenticated=True)


def reconcile(snapshot,quote,ordinary=None):
    proof=right_flow(snapshot['ledger']['events'],quote)
    if ordinary is None:
        from core_window_review import reconcile as ordinary
    ordinary(snapshot);return proof

"""Independent typed right-flow reconciliation before ordinary stock accounting."""
from decimal import Decimal
from fractions import Fraction
import json

from typing import Literal
from pydantic import BaseModel,ConfigDict
from p01_celg_multileg_facts import Identity

class Quote(BaseModel):
    """Independent strict synthetic fixture schema, never a market observation."""
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    identity:Identity
    session:Literal['2019-11-21']
    authority:Literal['SYNTHETIC_COMPONENT_FIXTURE_NOT_MARKET_DATA']
    raw_open:Literal['2.30']
    raw_close:Literal['2.25']
    adjustment:Literal['raw']
    observed_market_data:Literal[False]

SID='11651249425833422'
BMY='578964201416671255'
DAY='2019-11-21'

def need(value,code):
    if not value:raise ValueError('REFUSED_CELG_ACCOUNTING_'+code)
def near(a,b,code):
    need(abs(Decimal(str(a))-Decimal(str(b)))<=Decimal('0.0000001'),code)

def right_flow(events):
    rows=[v for v in events if v['event_type'] in ('MERGER_RIGHT_RECEIPT','MERGER_RIGHT_LIQUIDATION')]
    if not rows:return None
    need(len(rows)==2 and [v['event_type'] for v in rows]==['MERGER_RIGHT_RECEIPT','MERGER_RIGHT_LIQUIDATION'],
         'EXACT_ONE_RECEIPT_SALE_PAIR_NO_MISSING_OR_REPEATED_RIGHT')
    received,sold=rows;body=received['detail']
    need(body==sold['detail'] and body['schema']=='canonical.merger-right-ledger-detail/1', 'IMMUTABLE_COMPLETE_ACTION_DETAIL')
    ident=Identity.model_validate(body['right_identity']);quoted=Quote.model_validate(body['right_quote'])
    need(json.dumps(body['right_identity'],sort_keys=True,allow_nan=False)==json.dumps(ident.model_dump(),sort_keys=True,allow_nan=False)
         and json.dumps(body['right_quote'],sort_keys=True,allow_nan=False)==json.dumps(quoted.model_dump(),sort_keys=True,allow_nan=False),
         'COMPLETE_EXTERNAL_IDENTITY_AND_QUOTE_WITHOUT_DEFAULTS_OR_TYPE_COERCION')
    need(quoted.identity==ident and body['source_security_id']==SID and body['source_ticker']=='CELG'
         and body['legal_completion_day']=='2019-11-20' and body['valuation_session']==DAY,
         'DISTINCT_LEGAL_AND_QUOTED_MARKET_CLOCKS')
    amount=Fraction(body['right_units_exact']);source=Fraction(body['source_shares_exact']);cost=Fraction(body['cost_bps'])
    need(amount==source and amount>0 and amount.denominator==1 and body['right_units_per_source']=='1'
         and 0<=cost<10000,'EXACT_INTEGRAL_SOURCE_AND_RIGHT_ENTITLEMENT_NO_FRACTION_OR_LEVERAGE')
    need(all(v['session']==DAY and v['security_id'] is None and v['ticker']=='BMYRT' for v in rows)
         and type(received['shares_delta']) is int and type(sold['shares_delta']) is int
         and received['shares_delta']==amount and sold['shares_delta']==-amount,
         'TYPED_OPAQUE_IDENTITY_AND_ZERO_RESIDUAL_RIGHT_UNITS')
    need(received['cash_delta']==0 and received['fees']==0 and received['cash_before']==received['cash_after']
         and received['reason']=='MERGER_RIGHT_CONTRACTUAL_ENTITLEMENT', 'RECEIPT_NEVER_INVENTS_CASH')
    gross=amount*Fraction(quoted.raw_open);fees=gross*cost/10000;net=gross-fees
    need(received['price']==float(quoted.raw_open)==sold['price'] and sold['cash_delta']==float(net)
         and sold['fees']==float(gross)-float(net) and sold['cash_before']==received['cash_after']
         and sold['cash_after']==sold['cash_before']+sold['cash_delta']
         and sold['reason']=='INVOLUNTARY_MERGER_RIGHT_LIQUIDATED_AT_OPEN', 'EXACT_CANONICAL_OPEN_SALE_CASH_CHAIN')
    near(sold['fees'],float(fees),'INDEPENDENT_EXACT_FEE_EXPECTATION')
    need(body['gross_value_exact']==str(gross) and body['gross_value']==float(gross), 'GROSS_RIGHT_VALUE_SEPARATE_FROM_LEGAL_CASH')
    converted=[v for v in events if v['event_type']=='CONVERSION' and v['security_id']==SID and v['session']==DAY]
    need(converted,'ACTUAL_CANONICAL_CELG_TO_BMY_CONVERSION_REQUIRED')
    quantity=Fraction()
    for event in converted:
        info=event['detail'];q=Fraction(str(info['shares_in']));delivered=Fraction(str(info['shares_delivered']))
        need(info['delivered_security_id']==BMY and info['delivered_ticker']=='BMY'
             and info['exchange_ratio_exact']=='1' and q==delivered>0
             and event['price']==50.0 and info['reference']==body['reference'], 'CANONICAL_STOCK_1_TO_1_AND_LEGAL_CASH_50')
        near(info['cash_consideration'],float(q*50),'NO_COMBINED_52_30_OR_CONTINGENT_9_CASH_TERM')
        quantity+=q
    need(quantity==amount,'RIGHT_RECEIPT_EQUALS_ACTUAL_CANONICAL_HOLDER_SOURCE_QUANTITY')
    return dict(schema='research.celg-independent-right-flow/1',right_identity=ident.model_dump(),
        units=str(amount),residual_units='0',legal_merger_cash_exact=str(quantity*50),
        gross_right_open_value_exact=str(gross),right_sale_fee_exact=str(fees),net_right_sale_cash_exact=str(net),
        separate_closing_sensor_quote=quoted.raw_close,quote_authority=quoted.authority,
        actual_provider_response_authenticated=False,
        financial_clock_admitted=False)

def reconcile(snapshot,ordinary=None):
    proof=right_flow(snapshot['ledger']['events'])
    if ordinary is None:
        from core_window_review import reconcile as ordinary
    ordinary(snapshot)
    return proof

"""Original independent cash-event reviewer; private operation-order adapter only."""
from decimal import Decimal as D
from system_campaign_ordinary_augmentation_data import need

def verify_event(record, term, before, opened, events):
    sid, day = (term['security_id'], term['added']['session'])
    price = D(str(term['added']['cash_per_share']))
    held = [e for e in before['wealth_core']['episodes'].values() if e['security_id'] == sid]
    need(all((type(e['current_shares']) is int and e['current_shares'] > 0 for e in held)), 'INTEGER_HELD_QUANTITIES')
    quantity = sum((e['current_shares'] for e in held))
    amount = D(quantity) * price
    need(record['passed'] is True and record['financial_source_changed'] is False and (record['session'] == day) and (record['source'] == record['stock'] == record['risk'] == []) and (record['engine_calls'] == 0) and (record['order'] == ['CASH:' + sid]) and (len(record['cash']) == 1), 'ACTUAL_ORDINARY_CASH_CONTEXT')
    c = record['cash'][0]
    need(c['actual_context_call'] is True and c['source_only_noop'] is False and (c['security_id'] == sid) and (c['session'] == day) and (c['postcondition']['actual_held'] == bool(held)) and (c['postcondition']['quantity'] == quantity) and (D(str(c['postcondition']['nominal_cash'])) == amount), 'EXACT_ORIGINAL_CASH_CONSIDERATION')
    paid = [e for e in events if e['security_id'] == sid and e['session'] == day and (e['event_type'] == 'CASH_MERGER')]
    need(len(paid) == len(held) and sum((D(str(e['cash_delta'])) for e in paid), D(0)) == amount and all((D(str(e['price'])) == price and e['shares_delta'] < 0 and (e['fees'] == 0.0) and (D(str(e['cash_delta'])) == -D(str(e['shares_delta'])) * price) and (e['detail']['reference'] == term['added']['reference']) for e in paid)) and (not any((e['security_id'] == sid for e in opened['wealth_core']['episodes'].values()))) and (not any((e['security_id'] == sid for e in opened['pending']))), 'EXACT_ORDINARY_LEDGER_AND_CLEARANCE')
    return dict(ticker=term['ticker'], session=day, quantity=quantity, nominal_cash=str(amount))

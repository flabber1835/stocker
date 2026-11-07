"""Actual committed cash entitlements and exact common-basis delta."""
import json
import math
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import sha
from system_campaign_uncertainty_review import committed_rows
from system_campaign_spring2023_basis import require_exact_delta


def same(a, b):
    return math.isfinite(float(a)) and math.isfinite(float(b)) and math.isclose(
        float(a), float(b), rel_tol=1e-12, abs_tol=1e-8)


def actual_cash(root, cp, parent, catalog, output):
    hosted()
    by_day = {}
    terms = catalog['terms']
    for term in terms: by_day.setdefault(term['added']['session'], []).append(term)
    checks = {}
    before = parent['run']['state']['wealth_core']
    events = cp['run']['state']['ledger']['events']
    indexed = {}
    for event in events:
        if event['event_type'] == 'CASH_MERGER':
            indexed.setdefault(event['security_id'], []).append(event)
    for row in committed_rows(root / 'book', cp, 'daily'):
        day = row['session']
        if day <= parent['source_cursor']: continue
        audit = row['evidence']['research_entry_audit']
        opening = audit['opening_accounting']['wealth_core']
        closing = audit['closing_accounting']['wealth_core']
        for term in by_day.get(day, []):
            sid = term['security_id'];price = term['added']['cash_per_share']
            episodes = [v for v in before['episodes'].values() if v['security_id'] == sid]
            quantity = sum(v['current_shares'] for v in episodes)
            actual = indexed.get(sid, [])
            need(all(v['session'] == day and same(v['price'], price)
                     and same(v['cash_delta'], float(v['detail']['shares'])*price)
                     and same(v['shares_delta'], -float(v['detail']['shares']))
                     and v['detail']['reference'] == term['added']['reference'] for v in actual)
                 and len(actual) == len(episodes)
                 and same(sum(float(v['detail']['shares']) for v in actual), quantity),
                 'Q4_ACTUAL_LEDGER_ENTITLEMENT_DATE_PRICE_QUANTITY_EXACTLY_ONCE')
            need(all(v['security_id'] != sid for v in opening['episodes'].values()),
                 'Q4_ACTUAL_RECOGNITION_OPEN_REMOVES_OLD_POSITION')
            checks[sid] = dict(ticker=term['ticker'], session=day, prior_shares=quantity,
                ledger_events=len(actual), actual_cash=sum(float(v['cash_delta']) for v in actual),
                expected_cash=float(quantity)*price)
        for term in terms:
            sid = term['security_id'];recognition = term['added']['session']
            if day >= recognition:
                need(all(v['security_id'] != sid for v in closing['episodes'].values())
                     and sid not in closing['unresolved_terminals']
                     and sid not in closing['terminal_pending_sessions'],
                     'Q4_NO_RESIDUAL_OR_PENDING_TERMINAL_POSITION')
            else:
                need(not any(v['session'] <= day for v in indexed.get(sid, [])),
                     'Q4_NO_EARLY_TERMINAL_PAYMENT_ON_PRESERVED_TRADING_DAY')
        before = closing
    reached = {v['security_id'] for v in terms if v['added']['session'] <= cp['source_cursor']}
    need(set(checks) == reached, 'Q4_EVERY_REACHED_EVENT_REQUIRES_ACTUAL_COMMITTED_PROOF')
    value = dict(status='ACTUAL_COMMITTED_CASH_ENTITLEMENTS_REVIEWED',
        checkpoint_sha256=cp['sha256'], through=cp['source_cursor'], actual_checks=checks,
        not_yet_reached=[v['ticker'] for v in terms if v['security_id'] not in reached],
        unheld_events_do_not_invent_payments=True, production_contacted=False)
    save(output, value)
    return value


def factual_delta(before, after, root, catalog):
    group = catalog['commitment_group'];raw = (root / group['private_file']).read_bytes()
    payload = json.loads(raw)
    need(payload['catalog'] == catalog and payload['all_physical_provider_preimages_verified'] is True
         and payload['recognition_quote_qualification']['actual_recognition_quotes'] == [],
         'Q4_EXACT_PUBLIC_CATALOG_AND_ACTUAL_PRIVATE_SOURCE_QUALIFICATION')
    refs = {group['reference_stem'] + k: v for k, v in (
        ('catalog', sha((Path(__file__).parent / group['catalog_file']).read_bytes())),
        ('loader', sha((Path(__file__).parent / group['loader_file']).read_bytes())), ('private', sha(raw)))}
    return require_exact_delta(before, after, catalog, refs)

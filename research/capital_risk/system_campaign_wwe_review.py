"""Actual resumed conversion and exact common factual delta; hosted review only."""
from copy import deepcopy
import json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import sha
from system_campaign_wwe_facts import SID, DELIVERED, DAY
from system_campaign_uncertainty_review import committed_rows
from system_campaign_spring2023_basis import require_exact_delta


def actual_conversion(root, cp, parent, output):
    hosted()
    rows = committed_rows(root / 'book', cp, 'daily')
    before = parent['run']['state']['wealth_core']
    observed = None
    for row in rows:
        if row['session'] <= parent['source_cursor']:
            continue
        audit = row['evidence']['research_entry_audit']
        opening, closing = audit['opening_accounting'], audit['closing_accounting']
        if row['session'] == DAY:
            prior_quantity = sum(v['current_shares'] for v in before['episodes'].values()
                                 if v['security_id'] == SID)
            target_quantity = sum(v['current_shares'] for v in opening['wealth_core']['episodes'].values()
                                  if v['security_id'] == DELIVERED)
            need(prior_quantity == target_quantity == 16
                 and all(v['security_id'] != SID for v in opening['wealth_core']['episodes'].values()),
                 'WWE_ACTUAL_RESUMED_OPEN_CONVERTS_ALL_SIXTEEN_COMMON_SHARES')
            observed = dict(session=DAY, prior_shares=prior_quantity, delivered_shares=target_quantity,
                            next_state_sha256=row['state_sha256'], fractional_cash=0)
        if row['session'] >= DAY:
            need(all(v['security_id'] != SID for v in closing['wealth_core']['episodes'].values())
                 and SID not in closing['wealth_core']['unresolved_terminals']
                 and SID not in closing['wealth_core']['terminal_pending_sessions'],
                 'WWE_NO_RESIDUAL_OR_PENDING_OLD_SECURITY_AFTER_CONVERSION')
        before = closing['wealth_core']
    if cp['source_cursor'] >= DAY:
        need(observed is not None, 'WWE_COMPLETED_EVENT_REQUIRES_ACTUAL_RESUMED_PROOF')
    events = cp['run']['state']['ledger']['events']
    converted = [event for event in events if event['session'] == DAY
                 and event['event_type'] == 'CONVERSION' and event['security_id'] == SID]
    if observed is not None:
        need(len(converted) == 1 and float(converted[0]['cash_delta']) == 0,
             'WWE_ACTUAL_CONVERSION_LEDGER_EXACTLY_ONCE_WITHOUT_MERGER_CASH')
    proof = dict(status='ACTUAL_WWE_CONVERSION_REVIEWED' if observed else 'PRE_EVENT_COMMITTED_PREFIX_ONLY',
        checkpoint_sha256=cp['sha256'], through=cp['source_cursor'], actual_conversion=observed,
        conversion_ledger_events=len(converted), no_second_merger_cash_payment=True,
        separate_dividend_remains_original_frozen_input=True, production_contacted=False)
    save(output, proof)
    return proof


def factual_delta(before, after, root, catalog):
    group = catalog['commitment_group']
    private_raw = (root / group['private_file']).read_bytes()
    payload = json.loads(private_raw)
    need(payload['catalog'] == catalog and len(payload['effective_terms']) == 1,
         'WWE_EXACT_PUBLIC_CATALOG_AND_PRIVATE_EFFECTIVE_TERM')
    effective = deepcopy(catalog)
    effective['terms'][0]['added'] = payload['effective_terms'][0]
    commitments = {group['reference_stem'] + key: value for key, value in (
        ('catalog', sha((Path(__file__).parent / group['catalog_file']).read_bytes())),
        ('loader', sha((Path(__file__).parent / group['loader_file']).read_bytes())),
        ('private', sha(private_raw)))}
    return require_exact_delta(before, after, effective, commitments)

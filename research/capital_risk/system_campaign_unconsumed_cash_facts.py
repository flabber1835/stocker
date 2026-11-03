"""Five already researched ordinary cash facts after the exact own37 boundary."""
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_pxd_financial_body import function
from system_campaign_unconsumed_cash_context import STEM
import system_campaign_q4_cash_facts as original

CATALOG = 'system-campaign-unconsumed2024-cash-calendar-terminal-facts.json'
EXPECTED = {'ALPN': ('2024-05-17', '2024-05-20', 65.),
            'SWAV': ('2024-05-30', '2024-05-31', 335.),
            'DCPH': ('2024-06-10', '2024-06-11', 25.6),
            'EVBG': ('2024-07-01', '2024-07-02', 35.),
            'PRFT': ('2024-10-01', '2024-10-02', 76.)}


def validate(catalog):
    need(catalog['schema'] == 'research.factual-cash-calendar-catalog/1'
         and catalog['source_research_events'] == 8 and catalog['active_unconsumed_events'] == 5
         and len(catalog['terms']) == 5 and catalog['same_day_quote_claims'] == []
         and catalog['full_provider_rows_verification_required'] is True
         and catalog['commitment_group']['reference_stem'] == STEM
         and catalog['commitment_group']['catalog_file'] == CATALOG
         and catalog['loader_sha256'] == sha(Path(original.original.__file__).read_bytes())
         and all(catalog[k] is False for k in ('canonical_financial_source_changed', 'provider_metadata_upgraded', 'production_contacted')),
         'UNCONSUMED_CASH_EXACT_FIVE_DATA_ONLY_TERMS_AND_ORIGINAL_LOADER')
    need({v['ticker'] for v in catalog['excluded_consumed_events']} == {'KRTX', 'AYX', 'MDC'}
         and all(v['native_session'] <= '2024-04-30' for v in catalog['excluded_consumed_events'])
         and catalog['excluded_pending_events'] == [dict(ticker='WIRE', reason='ACTUAL_FROZEN_RECOGNITION_QUOTE_CONFLICT')],
         'UNCONSUMED_CASH_NO_RETROACTIVE_OR_CONFLICTING_EVENT')
    actual = {}
    for term in catalog['terms']:
        original.original.validate_term(term)
        extraction = term['primary_extraction']
        actual[term['ticker']] = term['native_session'], term['added']['session'], term['added']['cash_per_share']
        need(term['native_session'] > '2024-04-30' and extraction['currency'] == 'USD'
             and float(extraction['cash_per_ordinary_share']) == term['added']['cash_per_share']
             and term['preopen_completion_confirmed'] and term['recognition_rule'] == original.original.PREOPEN
             and len(term['provider_rows_proof']['selected_row_sha256']) == 3,
             'UNCONSUMED_CASH_PRIMARY_MANDATORY_USD_CASH_AND_COMPLETE_PROVIDER_ROLES')
    need(actual == EXPECTED, 'UNCONSUMED_CASH_ONLY_FIVE_SOURCE_BOUND_FACTS')
    return catalog


def hydrate(catalog, cp, root, out):
    return function('system_campaign_q4_cash_facts.py', 'hydrate', {},
                    dict(vars(original), validate=validate))(catalog, cp, root, out)


def build(cp, old, out):
    return function('system_campaign_q4_cash_facts.py', 'build', {},
                    dict(vars(original), CATALOG=CATALOG, validate=validate, hydrate=hydrate,
                         __file__=__file__))(cp, old, out)


def qualify(out, cp, facts, loaded, old_objects, request):
    import system_campaign_q4_cash_gate as gate
    return function('system_campaign_q4_cash_gate.py', 'qualify', {
        'q4-cash-packet-qualification.json': 'unconsumed2024-cash-packet-qualification.json',
        'q4-cash-canonical-qualification.json': 'unconsumed2024-cash-canonical-qualification.json',
        'ALL_31_CASH_EVENTS_CANONICALLY_QUALIFIED': 'ALL_FIVE_CASH_EVENTS_CANONICALLY_QUALIFIED'},
        vars(gate))(out, cp, facts, loaded, old_objects, request)

"""Eleven source-bound winter cash facts; no Core financial implementation."""
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_pxd_financial_body import function
from system_campaign_winter2025_cash_context import STEM
from system_campaign_q4_cash_review import factual_delta
import system_campaign_q4_cash_facts as original

CATALOG = 'system-campaign-winter2025-cash-terminal-facts.json'
EXPECTED = {
    'CDMO': ('641708992638960500', '2025-02-04', '2025-02-05', 12.50, 5),
    'RVNC': ('561615213934063912', '2025-02-05', '2025-02-06', 3.65, 3),
    'SUM': ('364431306575234844', '2025-02-07', '2025-02-10', 52.50, 3),
    'ZUO': ('699288853008671138', '2025-02-13', '2025-02-14', 10.00, 5),
    'NARI': ('543768354908702200', '2025-02-18', '2025-02-19', 80.00, 3),
    'OMIC': ('252574123696847206', '2025-02-20', '2025-02-21', 20.00, 3),
    'HCP': ('610550191134128154', '2025-02-26', '2025-02-27', 35.00, 3),
    'INFN': ('472454776648049441', '2025-02-27', '2025-02-28', 6.65, 3),
    'EMKR': ('106733641894872523', '2025-02-28', '2025-03-03', 3.10, 3),
    'ALTM': ('683269517186158393', '2025-03-05', '2025-03-06', 5.85, 3),
    'AZPN': ('556944515102158299', '2025-03-11', '2025-03-12', 265.00, 3),
}


def validate(catalog):
    need(catalog['schema'] == 'research.factual-cash-calendar-catalog/1'
         and catalog['source_research_events'] == 15
         and catalog['active_unconsumed_events'] == len(catalog['terms']) == 11
         and catalog['same_day_quote_claims'] == catalog['excluded_pending_events'] == []
         and catalog['full_provider_rows_verification_required'] is True
         and catalog['commitment_group']['reference_stem'] == STEM
         and catalog['commitment_group']['catalog_file'] == CATALOG
         and catalog['loader_sha256'] == sha(Path(original.original.__file__).read_bytes())
         and all(catalog[k] is False for k in (
             'canonical_financial_source_changed', 'provider_metadata_upgraded', 'production_contacted')),
         'WINTER2025_EXACT_ELEVEN_FACTS_AND_UNCHANGED_CASH_COMPILER')
    need({v['ticker'] for v in catalog['excluded_consumed_events']} == {'VZIO', 'AGR', 'NAPA', 'SMAR'}
         and len(catalog['excluded_consumed_events']) == 4
         and all(v['native_session'] <= '2025-01-31'
                 and v['cross_candidate_equivalence_claimed'] is False
                 for v in catalog['excluded_consumed_events'])
         and catalog['consumed_agr_distribution_discrepancy_retained'] is True,
         'WINTER2025_NO_CONSUMED_EVENT_OR_RETROSPECTIVE_DIVIDEND_CHANGE')
    need(catalog['conditional_default_scope'] == dict(
        ticker='INFN', scope='NO_AFFIRMATIVE_ELECTION', all_holders_mandatory_cash=False,
        actual_source_bound_passive_book_gate_required=True),
        'WINTER2025_EXPLICIT_CONDITIONAL_INFN_SCOPE')
    actual = {}
    for term in catalog['terms']:
        original.original.validate_term(term)
        extraction = term['primary_extraction']
        need(term['ticker'] not in actual and term['native_session'] > '2025-01-31'
             and extraction['currency'] == 'USD'
             and float(extraction['cash_per_ordinary_share']) == term['added']['cash_per_share'],
             'WINTER2025_UNIQUE_UNCONSUMED_PRIMARY_COMMON_CONSIDERATION')
        actual[term['ticker']] = (
            term['security_id'], term['native_session'], term['added']['session'],
            term['added']['cash_per_share'], len(term['provider_rows_proof']['selected_row_sha256']))
        if term['ticker'] == 'EMKR':
            need(term['recognition_rule'] == original.original.NEXT
                 and term['preopen_completion_confirmed'] is False
                 and term['actual_completion_date'] == term['last_trading_session'] == '2025-02-28'
                 and term['added']['session'] == '2025-03-03'
                 and extraction['retained_next_session_convention_explicit'] is True,
                 'WINTER2025_EMKR_ACTUAL_CLOSE_DAY_AND_RETAINED_NEXT_SESSION')
        else:
            need(term['recognition_rule'] == original.original.PREOPEN
                 and term['preopen_completion_confirmed'] is True
                 and term['actual_completion_date'] == term['added']['session'],
                 'WINTER2025_ACTUAL_PREOPEN_COMPLETION')
        if term['ticker'] == 'INFN':
            need(term['cash_scope'] == extraction['cash_scope'] == 'NO_AFFIRMATIVE_ELECTION'
                 and extraction['remaining_common_shares_automatically_cash'] is False
                 and extraction['all_holders_mandatory_cash'] is False
                 and extraction['non_electing_common_shares_automatically_cash'] is True
                 and extraction['passive_book_default_only'] is True
                 and extraction['stock_or_mixed_election_proration_not_applied_to_passive_book'] is True
                 and extraction['contract_sections'] == [
                     '2.7(a)(iii)', '2.7(b)(ii)', '2.7(b)(v)', '2.7(c)'],
                 'WINTER2025_INFN_NO_BLANKET_CASH_OR_INVENTED_ELECTION')
        else:
            need(term['cash_scope'] == extraction['cash_scope'] == 'ORDINARY_COMMON_MANDATORY'
                 and extraction['remaining_common_shares_automatically_cash'] is True,
                 'WINTER2025_OTHER_TERMS_REMAIN_MANDATORY_ORDINARY_COMMON')
    need(actual == EXPECTED, 'WINTER2025_EXACT_IDENTITIES_DATES_AMOUNTS_AND_ALL_PHYSICAL_ROLES')
    return catalog


def hydrate(catalog, cp, root, out):
    return function('system_campaign_q4_cash_facts.py', 'hydrate', {},
                    dict(vars(original), validate=validate))(catalog, cp, root, out)


def build(cp, old, out):
    return function('system_campaign_q4_cash_facts.py', 'build', {},
                    dict(vars(original), CATALOG=CATALOG, validate=validate,
                         hydrate=hydrate, __file__=__file__))(cp, old, out)


def qualify(out, cp, facts, loaded, old_objects, request):
    import system_campaign_q4_cash_gate as gate
    from system_campaign_winter2025_cash_gate import qualify_default_scope, qualify_held
    qualify_default_scope(out, cp, facts, request)
    result = function('system_campaign_q4_cash_gate.py', 'qualify', {
        'q4-cash-packet-qualification.json': 'winter2025-cash-packet-qualification.json',
        'q4-cash-canonical-qualification.json': 'winter2025-cash-canonical-qualification.json',
        'ALL_31_CASH_EVENTS_CANONICALLY_QUALIFIED': 'WINTER2025_ELEVEN_CASH_EVENTS_CANONICALLY_QUALIFIED'},
        vars(gate))(out, cp, facts, loaded, old_objects, request)
    qualify_held(out, cp, facts)
    return result

"""Closed own-parent source and contingent legal endpoints; no book runtime."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

from system_campaign_bounded_sensor_input import Event, need, digest, sha

SCHEMA = 'research.qualified-bounded-contingent-sensor-catalog/1'


def encoded(value):
    return (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()


def validate(value, *, root_lookup):
    need(value['schema'] == SCHEMA and value['input_adopted'] is False
         and value['financial_authority'] is False and value['local_canonical_runtime_executed'] is False,
         'CATALOG_DATA_ONLY_AUTHORITY')
    event=Event.model_validate(value['event']).model_dump()
    root=root_lookup(value['arm'],value['parent_root_admission_sha256'])
    need((root['outer_sha256'],root['selected_session'],root['measured_closes']) ==
         (value['parent_outer_sha256'],value['parent_cursor'],value['parent_completed'])
         and root['repairs'] == value['parent_descriptors']
         and root['inner_sha256'] == value['parent_inner_sha256']
         and value['parent_cursor'] < event['native_session'], 'CATALOG_EXACT_FULL_OWN_PARENT')
    source=value['source_data'];payload,review,q=(source[k] for k in ('payload','review','qualification'))
    for key in ('payload','review','qualification'):
        need(sha(encoded(source[key])) == source[key+'_sha256'], 'CATALOG_EXACT_CLOSED_SOURCE_BYTES')
    need(q['schema'] == 'research.independent-source290-DATA-validation/1'
         and q['passed'] is True and q['source_identity_only'] is True
         and q['value_timing_or_unheld_source_policy_qualified'] is False
         and q['current_unheld_unordered_unreserved_no_claims'] is True
         and q['model_activated'] is q['financial_authority'] is q['canonical_financial_runtime_executed'] is False
         and q['payload_sha256'] == source['payload_sha256']
         and q['review_sha256'] == source['review_sha256']
         and q['scope_sha256'] == digest(payload['scope'])
         and q['own_inputs_preserved'] == len(root['repairs']), 'CATALOG_CLOSED_SOURCE290_QUALIFICATION')
    sid=event['security_id']
    need(payload['arm'] == review['arm'] == value['arm']
         and payload['parent_outer_sha256'] == review['parent_outer_sha256'] == value['parent_outer_sha256']
         and payload['parent_cursor'] == value['parent_cursor']
         and review['parent_root_admission_sha256'] == q['parent_root_admission_sha256'] == value['parent_root_admission_sha256']
         and review['payload_sha256'] == source['payload_sha256'] and review['passed'] is True
         and review['source_identity_qualified_for_separate_future_input_review'] is True
         and review['source_value_or_settlement_timing_qualified'] is False
         and review['input_adopted'] is review['financial_authority'] is review['local_canonical_runtime_executed'] is False
         and type(review['financial_sessions_advanced']) is int and review['financial_sessions_advanced'] == 0,
         'CATALOG_EXACT_SOURCE_OWN_SCOPE_AND_NO_ECONOMIC_AUTHORITY')
    terms=[t for t in payload['terms'] if t['native_term']['security_id'] == sid]
    need(len(terms) == 1, 'CATALOG_ONE_EXACT_SOURCE_NATIVE')
    term,=terms
    need(term['parent_positions'] == [] and review['parent_pending_context'][sid] == []
         and term['native_term'] == value['native']
         and digest(term['native_term']) == event['native_term_sha256']
         and term['native_term']['cash_per_share'] is None
         and term['native_term']['session'] == event['native_session']
         and term['native_term']['kind'] == 'CASH_MERGER'
         and term['identity_witness'] == value['identity_witness']
         and term['identity_witness']['session'] == event['prior_session'],
         'CATALOG_EXACT_INCOMPLETE_NATIVE_AND_UNOWNED_ROLE')
    primary=value['primary_facts']
    need(sha(encoded(primary)) == value['primary_facts_sha256']
         and primary['ticker'] == event['ticker'] and primary['currency'] == event['currency']
         and primary['event_date'] == event['effective_session']
         and primary['upfront_cash_per_share'] == event['upfront_cash_per_share']
         and primary['right_lower_per_share'] == event['right_lower_per_share']
         and primary['right_upper_per_share'] == event['right_upper_per_share']
         and primary['rights_per_share'] == '1' and primary['right_transferable'] is False
         and primary['settlement_authorized'] is primary['probability_selected'] is False,
         'CATALOG_EXACT_QUALIFIED_CONTINGENT_LEGAL_ENDPOINTS')
    market=value['market_source'];preparation=value['raw_quote_preparation']
    need(sha(encoded(market)) == value['market_source_sha256']
         and sha(encoded(preparation)) == value['raw_quote_preparation_sha256']
         and market['event_contract_sha256'] == digest(event)
         and market['source290_payload_sha256'] == preparation['source290_payload_sha256'] == source['payload_sha256']
         and market['source290_review_sha256'] == preparation['source290_review_sha256'] == source['review_sha256']
         and market['source290_qualification_sha256'] == preparation['source290_qualification_sha256'] == source['qualification_sha256']
         and market['archive_sha256'] == preparation['archive_sha256']
         and preparation['passed'] is True and preparation['local_canonical_runtime_executed'] is preparation['financial_authority'] is False,
         'CATALOG_EXACT_RAW_QUOTE_PREPARATION_PROVENANCE')
    need(market['source_quote_present'] is preparation['source_quote_present'] is True
         and len(preparation['event_rows']) == 1
         and market['raw_event_row'] == preparation['event_rows'][0]
         and market['raw_prior_row'] == preparation['prior_row']
         and market['source_observation_sha256'] == digest(market['raw_event_row'])
         and market['session'] == market['raw_event_row']['session'] == event['effective_session']
         and market['raw_prior_row']['session'] == event['prior_session']
         and market['security_id'] == market['raw_event_row']['security_id'] == market['raw_prior_row']['security_id'] == sid
         and market['raw_event_row']['issuer_id'] == market['raw_prior_row']['issuer_id'] == term['identity_witness']['issuer_id']
         and digest(market['raw_prior_row']) == term['identity_witness']['source_observation_sha256']
         and market['split_ratio'] == market['raw_event_row']['split_ratio']
         and Decimal(market['split_ratio']) > 0
         and market['right_price_selected'] is market['portfolio_cash_settlement_authorized'] is market['financial_authority'] is False,
         'CATALOG_ACTUAL_PRESENT_EVENT_QUOTE_AND_IDENTITY')
    return deepcopy(value)


def load(path):
    from system_campaign_financial_partial import root_spec
    raw=Path(path).read_bytes()
    need(len(raw) <= 262144, 'CATALOG_BOUNDED_SOURCE_SIZE')
    return validate(json.loads(raw),root_lookup=root_spec)

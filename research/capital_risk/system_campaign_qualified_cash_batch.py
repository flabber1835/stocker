"""Source-bound cash input batches; all financial arithmetic stays canonical."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from full_system_benchmark import need
from system_campaign_facts import digest, sha

HERE = Path(__file__).parent
Digest = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
Session = Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]


class CashInputBatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.qualified-own-cash-input-batch/1'] = Field(alias='schema')
    arm: Annotated[str, Field(pattern=r'^P(0[0-9]|1[01])$')]
    parent_cursor: Session
    parent_outer_sha256: Digest
    parent_root_admission_sha256: Digest
    loader_sha256: Digest
    canonical_financial_source_changed: Literal[False]
    provider_metadata_upgraded: Literal[False]
    production_contacted: Literal[False]
    historical_causality: Literal['UNVERIFIED']
    source_data: dict
    terms: Annotated[list[dict], Field(min_length=1, max_length=128)]


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def source_binding(catalog):
    from system_campaign_financial_future import registered_scope
    from system_campaign_financial_partial import root_spec
    data = catalog['source_data']
    payload, review, qualification = (data[k] for k in ('payload', 'review', 'qualification'))
    root = root_spec(catalog['arm'], catalog['parent_root_admission_sha256'])
    need(root['outer_sha256'] == catalog['parent_outer_sha256'] == payload['parent_outer_sha256']
         == review['parent_outer_sha256'] and root['selected_session'] == catalog['parent_cursor']
         == payload['parent_cursor'] and review['parent_root_admission_sha256'] == catalog['parent_root_admission_sha256'],
         'CASH_BATCH_EXACT_ADMITTED_PARENT')
    need(payload['arm'] == review['arm'] == qualification['arm'] == catalog['arm']
         and payload['schema'] == 'research.own-parent-frozen-source-witnesses/1'
         and review['schema'] == 'research.independent-frozen-source-data-review/1'
         and qualification['schema'] == 'research.independent-frozen-source-data-validation/1'
         and review['passed'] is qualification['passed'] is True
         and sha(encoded(payload)) == review['payload_sha256']
         and sha(encoded(review)) == qualification['review_sha256']
         and review['scope_sha256'] == payload['scope_sha256'] == digest(payload['scope'])
         and payload['scope'] == registered_scope(payload['scope_sha256'])
         and payload.get('additional_rows', []) == review['additional_rows'] == [],
         'CASH_BATCH_EXACT_CLOSED_SOURCE_DATA')
    need(all(value[key] is False for value in (review, qualification) for key in (
             'financial_authority', 'input_adopted', 'local_canonical_runtime_executed',
             'source_value_or_settlement_timing_qualified'))
         and all(value['source_identity_qualified_for_separate_future_input_review'] is True
                 for value in (review, qualification))
         and all(payload[key] is False for key in ('financial_authority', 'input_adopted',
                 'provider_metadata_upgraded', 'production_contacted'))
         and type(payload['financial_sessions_advanced']) is int and payload['financial_sessions_advanced'] == 0
         and type(qualification['financial_workers_launched']) is int and qualification['financial_workers_launched'] == 0,
         'CASH_BATCH_SOURCE_IDENTITY_GRANTS_NO_FINANCIAL_AUTHORITY')
    return payload, review, qualification


def validate_tax_components(term):
    split = term.get('tax_components')
    if split is None:
        return
    total, dividend, proceeds = (Decimal(split[k]) for k in ('total_payment', 'dividend_component', 'proceeds_component'))
    need(split['schema'] == 'research.single-cash-payment-tax-components/1'
         and split['one_combined_payment'] is True and split['separate_dividend_to_add'] is False
         and all(v.is_finite() and v > 0 for v in (total, dividend, proceeds))
         and total == dividend + proceeds == Decimal(str(term['added']['cash_per_share']))
         and split['frozen_final_observations']
         and all(v['dividend_per_share'] == '0' for v in split['frozen_final_observations'])
         and len({v['session'] for v in split['frozen_final_observations']}) == len(split['frozen_final_observations'])
         and all(v['session'] <= term['native_session'] and len(v['source_observation_sha256']) == 64
                 for v in split['frozen_final_observations']), 'CASH_BATCH_ONE_PAYMENT_WITHOUT_DUPLICATE_DIVIDEND')


def validate(catalog):
    from system_campaign_cash_calendar import PREOPEN, validate_term
    from system_campaign_financial_future import RESEARCH_CASH, research_cash_term
    CashInputBatch.model_validate(catalog)
    need(catalog['loader_sha256'] == sha(Path(__file__).read_bytes())
         and all(catalog[k] is False for k in ('canonical_financial_source_changed',
                 'provider_metadata_upgraded', 'production_contacted')), 'CASH_BATCH_DATA_ONLY_EXACT_LOADER')
    payload, review, qualification = source_binding(catalog)
    terms, captured, declared = catalog['terms'], payload['terms'], payload['scope']['terms']
    need(len(terms) == len(captured) == len(declared) == len(review['terms'])
         and len({t['security_id'] for t in terms}) == len(terms)
         and [(t['ticker'], t['security_id']) for t in terms] == [(t['ticker'], t['security_id']) for t in declared],
         'CASH_BATCH_COMPLETE_ORDERED_UNIQUE_SOURCE_MEMBERS')
    expected_capture = dict(run_id=review['run_id'], head=review['head'], artifact_id=review['artifact_id'],
        payload_sha256=review['payload_sha256'], scope_sha256=review['scope_sha256'],
        independent_data_review_sha256=sha(encoded(review)), independent_qualification_sha256=sha(encoded(qualification)))
    for term, actual, scope, checked in zip(terms, captured, declared, review['terms'], strict=True):
        row, native = actual['source_row'], actual['native_term']
        witness = {k:row[k] for k in ('session', 'security_id', 'ticker', 'issuer_id',
                                     'listing_first_session', 'security_type_eligible')}
        witness['source_observation_sha256'] = digest(row)
        need(term['arm'] == catalog['arm'] and term['parent_cursor'] == catalog['parent_cursor']
             and term['parent_outer_sha256'] == catalog['parent_outer_sha256']
             and term['parent_root_admission_sha256'] == catalog['parent_root_admission_sha256']
             and term['source_capture'] == expected_capture
             and term['identity_witness'] == actual['identity_witness'] == checked['identity_witness'] == witness
             and term['native'] == native == checked['native_term'] and native['cash_per_share'] is None
             and digest(native) == term['native_term_sha256'] == scope['native_term_sha256']
             and term['native_session'] == native['session'] == scope['native_session']
             and term['parent_positions'] == actual['parent_positions'] == scope['parent_positions'] == checked['parent_positions']
             and term['security_id'] == native['security_id'] == row['security_id'] == scope['security_id']
             and row['session'] == scope['session'] and term['ticker'] == row['ticker'] == scope['ticker']
             and catalog['parent_cursor'] < term['native_session'], 'CASH_BATCH_EXACT_SOURCE_NATIVE_ROLE_AND_CLOCK')
        if term['recognition_rule'] == RESEARCH_CASH:
            research_cash_term(term)
        else:
            need(term['recognition_rule'] == PREOPEN, 'CASH_BATCH_ONLY_EXISTING_CASH_POLICIES')
            validate_term(term)
        extraction = term['primary_extraction']
        need(extraction['mandatory_common_cash'] is True
             and extraction['cash_currency'] == 'USD'
             and Decimal(extraction['cash_per_share']) == Decimal(str(term['added']['cash_per_share']))
             and extraction['completion_date'] == term['actual_completion_date']
             and extraction['source'] == term['primary_source']
             and extraction['preopen_completion_confirmed'] is term['preopen_completion_confirmed'],
             'CASH_BATCH_EXACT_PRIMARY_AMOUNT_AND_DATE_EXTRACTION')
        validate_tax_components(term)
    return True


class QualifiedCashBatch:
    def __init__(self, catalog):
        validate(catalog)
        self.catalog = deepcopy(catalog)

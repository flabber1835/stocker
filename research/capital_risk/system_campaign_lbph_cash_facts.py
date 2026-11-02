"""One mandatory ordinary-share merger, after the exact own39 boundary."""
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_pxd_financial_body import function
from system_campaign_lbph_cash_context import STEM
from system_campaign_q4_cash_review import factual_delta
import system_campaign_q4_cash_facts as original

CATALOG='system-campaign-lbph-preopen-cash-terminal-facts.json'


def validate(catalog):
    need(catalog['schema']=='research.factual-cash-calendar-catalog/1'
         and catalog['source_research_events']==catalog['active_unconsumed_events']==len(catalog['terms'])==1
         and catalog['same_day_quote_claims']==[] and catalog['excluded_consumed_events']==[]
         and catalog['excluded_pending_events']==[] and catalog['full_provider_rows_verification_required'] is True
         and catalog['commitment_group']['reference_stem']==STEM
         and catalog['commitment_group']['catalog_file']==CATALOG
         and catalog['loader_sha256']==sha(Path(original.original.__file__).read_bytes())
         and all(catalog[k] is False for k in ('canonical_financial_source_changed','provider_metadata_upgraded','production_contacted')),
         'LBPH_EXACT_ONE_ORDINARY_FACT_AND_UNCHANGED_CASH_COMPILER')
    term,=catalog['terms'];original.original.validate_term(term)
    extraction=term['primary_extraction']
    need(term['security_id']=='355279027800974395' and term['ticker']=='LBPH'
         and term['native_session']==term['last_trading_session']=='2024-11-29'
         and term['actual_completion_date']==term['added']['session']=='2024-12-02'
         and term['added']['cash_per_share']==60. and extraction['currency']=='USD'
         and extraction['cash_per_ordinary_share']=='60.00'
         and term['mandatory_common_share_completion_confirmed'] is True
         and term['preopen_completion_confirmed'] is True and term['recognition_rule']==original.original.PREOPEN
         and extraction['remaining_common_shares_automatically_cash'] is True
         and extraction['tender_expiration_date_not_used']=='2024-11-27'
         and extraction['administrative_suspension_date_not_used']=='2024-12-03'
         and term['native_term_sha256']=='e65b583e8e8358e98294987b3fcaa172ce122bb744aa1fc51a875ee73a48d669'
         and len(term['provider_rows_proof']['selected_row_sha256'])==3,
         'LBPH_ONLY_MANDATORY_60_CASH_DECEMBER2_PRESERVING_NOVEMBER29')
    return catalog


def hydrate(catalog,cp,root,out):
    return function('system_campaign_q4_cash_facts.py','hydrate',{},
                    dict(vars(original),validate=validate))(catalog,cp,root,out)


def build(cp,old,out):
    return function('system_campaign_q4_cash_facts.py','build',{},
        dict(vars(original),CATALOG=CATALOG,validate=validate,hydrate=hydrate,__file__=__file__))(cp,old,out)


def qualify(out,cp,facts,loaded,old_objects,request):
    import system_campaign_q4_cash_gate as gate
    from system_campaign_lbph_cash_gate import qualify_held
    result=function('system_campaign_q4_cash_gate.py','qualify',{
        'q4-cash-packet-qualification.json':'lbph-cash-packet-qualification.json',
        'q4-cash-canonical-qualification.json':'lbph-cash-canonical-qualification.json',
        'ALL_31_CASH_EVENTS_CANONICALLY_QUALIFIED':'LBPH_CASH_EVENT_CANONICALLY_QUALIFIED'},vars(gate))(
            out,cp,facts,loaded,old_objects,request)
    qualify_held(out,cp,facts)
    return result

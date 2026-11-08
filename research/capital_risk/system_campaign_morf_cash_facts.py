"""Explicit MORF-only retained quote coexistence; original cash loader unchanged."""
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import digest,sha
from system_campaign_pxd_financial_body import function
from system_campaign_morf_cash_context import STEM
from system_campaign_spring2023_basis import require_exact_delta
import system_campaign_q4_cash_facts as original

CATALOG='system-campaign-morf-preopen-cash-terminal-facts.json'
SID='977112340201324412'


def validate(catalog):
    need(catalog['schema']=='research.factual-cash-calendar-catalog/1'
         and catalog['source_research_events']==catalog['active_unconsumed_events']==len(catalog['terms'])==1
         and catalog['commitment_group']['reference_stem']==STEM
         and catalog['commitment_group']['catalog_file']==CATALOG
         and catalog['loader_sha256']==sha(Path(original.original.__file__).read_bytes())
         and catalog['quote_context_sha256']==sha(Path(__file__).read_bytes())
         and catalog['full_provider_rows_verification_required'] is True
         and all(catalog[k] is False for k in ('canonical_financial_source_changed','provider_metadata_upgraded','production_contacted')),
         'MORF_EXACT_ONE_SOURCE_BOUND_FACT_AND_ORIGINAL_LOADER')
    term,=catalog['terms'];original.original.validate_term(term)
    quote=term['recognition_quote_witness']
    need(term['ticker']=='MORF' and term['security_id']==SID and term['native_session']=='2024-08-16'
         and term['last_trading_session']=='2024-08-15' and term['added']['session']=='2024-08-16'
         and term['added']['cash_per_share']==57. and term['preopen_completion_confirmed'] is True
         and term['recognition_rule']==original.original.PREOPEN
         and term['actual_completion_date']=='2024-08-16'
         and term['primary_extraction']['currency']=='USD'
         and term['primary_extraction']['cash_per_ordinary_share']=='57.00'
         and term['native_term_sha256']=='86f0b41fbd1d1e2489011ed3649696b50ad7cebd4375cc1725a382724ed60235'
         and len(term['provider_rows_proof']['selected_row_sha256'])==3,
         'MORF_ONLY_MANDATORY_PREOPEN_57_CASH_ON_ACTUAL_COMPLETION')
    need(quote['session']=='2024-08-16' and quote['security_id']==SID
         and quote['ticker']=='MORF' and quote['issuer_id']=='SEC_CIK:1679363'
         and catalog['same_day_quote_claims']==[quote]
         and catalog['quote_source_metadata_unchanged'] is True
         and catalog['quote_generation_cause_claimed'] is False,
         'MORF_EXPLICIT_EXACT_RECOGNITION_QUOTE_NO_ABSENCE_OR_CAUSE_CLAIM')
    return catalog


class RecognitionTap(original.RecognitionTap):
    def __init__(self,catalog):
        super().__init__(catalog)
        self.quotes={(v['session'],v['security_id']):v for v in catalog['same_day_quote_claims']}

    def proof(self):
        need(self.completed==self.expected and set(self.found)==set(self.quotes)
             and self.inputs._archive_rows is self.original,'MORF_COMPLETE_SCAN_AND_EXACT_QUOTE_SET')
        for key,witness in self.quotes.items():
            actual=self.found[key]
            need(digest(actual)==witness['source_observation_sha256']
                 and all(actual[k]==v for k,v in witness.items() if k!='source_observation_sha256'),
                 'MORF_EXACT_FULL_RECOGNITION_QUOTE_PREIMAGE_UNCHANGED')
        return dict(status='EXACT_DECLARED_RECOGNITION_QUOTE_RETAINED_UNCHANGED',annual_rows=self.completed,
            actual_recognition_quotes=[self.found[k] for k in sorted(self.found)],
            original_rows_returned_unchanged=True,original_reader_restored=True,
            quote_absence_claimed=False,quote_generation_cause_claimed=False)


def hydrate(catalog,cp,root,out):
    return function('system_campaign_q4_cash_facts.py','hydrate',{},
        dict(vars(original),validate=validate,RecognitionTap=RecognitionTap))(catalog,cp,root,out)


def build(cp,old,out):
    return function('system_campaign_q4_cash_facts.py','build',{},
        dict(vars(original),CATALOG=CATALOG,validate=validate,hydrate=hydrate,__file__=__file__))(cp,old,out)


def qualify(out,cp,facts,loaded,old_objects,request):
    import system_campaign_q4_cash_gate as gate
    from system_campaign_morf_cash_gate import qualify_quote
    result=function('system_campaign_q4_cash_gate.py','qualify',{
        'q4-cash-packet-qualification.json':'morf-cash-packet-qualification.json',
        'q4-cash-canonical-qualification.json':'morf-cash-canonical-qualification.json',
        'ALL_31_CASH_EVENTS_CANONICALLY_QUALIFIED':'MORF_CASH_EVENT_CANONICALLY_QUALIFIED'},vars(gate))(
            out,cp,facts,loaded,old_objects,request)
    qualify_quote(out,cp,facts,loaded,old_objects,request)
    return result


def factual_delta(before,after,root,catalog):
    validate(catalog);group=catalog['commitment_group'];raw=(root/group['private_file']).read_bytes()
    payload=json.loads(raw);proof=payload['recognition_quote_qualification']
    need(payload['catalog']==catalog and payload['all_physical_provider_preimages_verified'] is True
         and proof['status']=='EXACT_DECLARED_RECOGNITION_QUOTE_RETAINED_UNCHANGED'
         and len(proof['actual_recognition_quotes'])==1 and proof['quote_absence_claimed'] is False,
         'MORF_ACTUAL_RETAINED_QUOTE_PROOF_REQUIRED_FOR_COMMON_BASIS')
    quote,=proof['actual_recognition_quotes'];witness,=catalog['same_day_quote_claims']
    need(digest(quote)==witness['source_observation_sha256'],'MORF_COMMON_BASIS_EXACT_QUOTE_BINDING')
    refs={group['reference_stem']+k:v for k,v in (
        ('catalog',sha((Path(__file__).parent/group['catalog_file']).read_bytes())),
        ('loader',sha((Path(__file__).parent/group['loader_file']).read_bytes())),('private',sha(raw)))}
    return require_exact_delta(before,after,catalog,refs)

"""Source-bound PXD ordinary common conversion; no owned fractional settlement."""
from copy import deepcopy
import json
from pathlib import Path
from types import FunctionType

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest, sha
from system_campaign_action_preflight import require_disjoint
import system_campaign_close_facts as original
from system_campaign_close_basis import SevenModelPreflight
from system_campaign_pxd_scope import SCHEMA, SCOPE, NATIVES, COMPLETIONS, parse, require_absent, require_intents

HERE = Path(__file__).resolve().parent
CONTRACT = 'system-campaign-pxd-preopen-contract.json'
PRIVATE = 'hydrated-pxd-preopen-fact.json'
OVERLAY = 'pxd-unowned-preopen-input.json'
IMPLEMENTATIONS = ('system_campaign_pxd_scope.py', 'system_campaign_pxd_facts.py',
                  'system_campaign_pxd_basis.py', 'system_campaign_pxd_gate.py',
                  'system_campaign_pxd_review.py', 'system_campaign_pxd_reuse.py')
STEM = 'research:system-optimization-002/pxd-preopen/'


def validate_contract(value):
    event=value['event'];term=event['added'];native=event['native']
    need(value['schema']=='research.unowned-preopen-stock-conversion-contract/1'
         and value['scope']==SCOPE and len(value['inherited_sources'])==263
         and all(value[k] is False for k in ('canonical_financial_source_changed',
             'provider_metadata_upgraded','new_owned_settlement_model','production_contacted')),
         'PXD_FACTS_EXACT_UNOWNED_STOCK_SCOPE_NO_SOURCE_OR_SETTLEMENT_CHANGE')
    need({event['security_id']:event['native_session']}==NATIVES
         and {event['security_id']:event['session']}==COMPLETIONS
         and event['ticker']=='PXD' and event['last_trading_session']=='2024-05-02'
         and event['mandatory_remaining_common_share_entitlement'] is True
         and event['ordinary_common_only'] is True and event['preopen_completion_claimed'] is True
         and event['exact_effective_clock_claimed'] is False,
         'PXD_FACTS_PRIMARY_ORDINARY_COMMON_PREOPEN_COMPLETION')
    need(native['kind']=='CASH_MERGER' and native['session']=='2024-05-02'
         and native['security_id']==event['security_id']
         and native['cash_per_share'] is None and digest(native)==event['native_term_sha256']
         and event['native_term_sha256']=='75634fb117503001b3c9e09b14f381c25aa4de0dbb9f6cf05db57eee57adde3f',
         'PXD_FACTS_EXACT_INCOMPLETE_NATIVE_CANONICAL_DICTIONARY')
    delivered=event['delivered_witness']
    need(term==dict(session='2024-05-03',security_id=event['security_id'],kind='CONVERSION',
             cash_per_share=None,delivered_security_id='687957854936610949',delivered_ticker='XOM',
             delivered_issuer_id='SEC_CIK:34088',exchange_ratio='2.3234',
             cash_in_lieu_price_per_delivered_share=None,
             reference=event['primary_source']+'#Items2.01and3.01',entitlement_aggregation='HOLDER')
         and (term['delivered_security_id'],term['delivered_ticker'],term['delivered_issuer_id'])
             ==tuple(delivered[k] for k in ('security_id','ticker','issuer_id')),
         'PXD_FACTS_EXACT_ORDINARY_RATIO_WITHOUT_CASH_OR_CIL_GUESS')
    need(event['primary_source']=='https://www.sec.gov/Archives/edgar/data/1038357/000119312524130052/d803313d8k.htm'
         and event['primary_sections']==dict(before_market_open_delisting='Item3.01',ordinary_entitlement='Item2.01'),
         'PXD_FACTS_EXACT_RETAINED_PRIMARY_SECTIONS')
    return value


def contract():
    value=validate_contract(json.loads((HERE/CONTRACT).read_bytes()))
    for name,expected in value['inherited_sources'].items():
        need(sha((HERE/name).read_bytes())==expected,'PXD_FACTS_ALL263_ADOPTED_SOURCE_BYTES_UNCHANGED')
    return value


def copy_body(fn, **bindings):
    value=contract()
    need(fn.__closure__ is None and sha(Path(original.__file__).read_bytes())
         ==value['inherited_sources']['system_campaign_close_facts.py'],
         'PXD_FACTS_UNCHANGED_ORIGINAL_SOURCE_HYDRATION_BODY')
    result=FunctionType(fn.__code__,dict(fn.__globals__,**bindings),fn.__name__,fn.__defaults__)
    result.__kwdefaults__=fn.__kwdefaults__
    return result


def evidence(root):
    return [dict(reference=STEM+name,sha256=sha((HERE/name).read_bytes()),
        description='Exact PXD unowned ordinary-common preopen contract or implementation.')
        for name in (CONTRACT,*IMPLEMENTATIONS)]+[dict(reference=STEM+'private/1',
        sha256=sha((Path(root)/PRIVATE).read_bytes()),
        description='Complete actual PXD/XOM source witnesses, native term, provider rows and quote absence.')]


def validate_payload(payload,value):
    # This private schema describes witness bytes, not an intraday timing rule.
    return copy_body(original.validate_payload)(payload,value)


def hydrate(root,out):
    return copy_body(original.hydrate,contract=contract,validate_payload=validate_payload,
                     PRIVATE=PRIVATE)(root,out)


def expected_repair(root,predecessor):
    return copy_body(original.expected_repair,contract=contract,validate_payload=validate_payload,
                     evidence=evidence,PRIVATE=PRIVATE)(root,predecessor)


def build(cp,root,out):
    hosted();value=contract();event=value['event'];sid=event['security_id']
    need(cp['source_cursor']<event['native_session'], 'PXD_FACTS_OWN_UNCONSUMED_PARENT')
    require_absent(cp['run']['state']['wealth_core'],cp['run']['state']['pending'],[sid])
    require_intents(cp['run']['state']['last_evidence']['wealth_core']['intents'],[sid])
    preflight=SevenModelPreflight(cp,root)
    report=preflight.analyze(cp,root,dict(schema=value['schema'],terms=[event]))
    require_disjoint(report);save(Path(out)/'pxd-collision-preflight.json',report)
    hydrate(root,out)
    predecessor=cp['run']['checkpoint_sha256'];body=expected_repair(out,predecessor)
    path=Path(out)/OVERLAY
    save(path,dict(schema=SCHEMA,predecessor_checkpoint_sha256=predecessor,scope=SCOPE,
        require_unowned_and_unordered=True,require_no_entry_intents=True,morning_settlement_claimed=False,
        canonical_repair=deepcopy(body),source_evidence=evidence(out)))
    obj=parse(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=predecessor,
        expected_repair=body,expected_evidence=evidence(out))
    for cursor,pred in ((cp['source_cursor'],'0'*64),(event['native_session'],predecessor)):
        try:parse(path,resume_session=cursor,predecessor_checkpoint_sha256=pred,
                  expected_repair=body,expected_evidence=evidence(out))
        except ValueError:pass
        else:raise ValueError('REFUSED_PXD_FACTS_WRONG_PREDECESSOR_OR_CONSUMED_SESSION')
    return value,obj,path

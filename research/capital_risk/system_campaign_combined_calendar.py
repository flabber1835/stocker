"""Merge disjoint new factual groups into one own-predecessor ordinary overlay."""
from copy import deepcopy
import json
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_cash_calendar import build as cash_build
from system_campaign_stock_calendar import build as stock_build
from system_campaign_action_preflight import analyze_new_catalog,require_disjoint

CASH='system-campaign-february-cash-calendar-terminal-facts.json'
STOCK='system-campaign-stock-calendar-terminal-facts.json'
OVERLAY='february-combined-calendar-overlay.json'


def combine_documents(documents,predecessor):
    result=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=predecessor,
                source_evidence=[],suppress=[],add=[])
    seen_suppress=set();seen_add=set();seen_refs={}
    for doc in documents:
        need(doc['schema']=='terminal-repair/1' and doc['predecessor_checkpoint_sha256']==predecessor,
             'COMBINED_EXACT_SAME_OWN_PREDECESSOR')
        for field,seen in (('suppress',seen_suppress),('add',seen_add)):
            for term in doc[field]:
                key=term['session'],term['security_id'];need(key not in seen,'COMBINED_NO_DUPLICATE_NATIVE_OR_EFFECTIVE_KEY')
                seen.add(key);result[field].append(deepcopy(term))
        for e in doc['source_evidence']:
            ref=e['reference']
            if ref in seen_refs:
                need(seen_refs[ref]==e,'COMBINED_NO_REDEFINED_SOURCE_REFERENCE');continue
            seen_refs[ref]=e;result['source_evidence'].append(deepcopy(e))
    need(len(result['suppress'])==len(result['add'])>0,'COMBINED_ONE_EXACT_SUPPRESSION_AND_ADDITION_PER_EVENT')
    return result


def build(cp,old,out,*,driver=Path('/driver')):
    cash,_,cash_path=cash_build(cp,old,out,driver/CASH)
    stock,_,stock_path=stock_build(cp,old,out,driver/STOCK)
    proof=analyze_new_catalog(cp,old,dict(terms=[*cash.catalog['terms'],*stock.catalog['terms']]))
    require_disjoint(proof);save(out/'combined-calendar-collision-preflight.json',proof)
    doc=combine_documents([json.loads(p.read_bytes()) for p in (cash_path,stock_path)],cp['run']['checkpoint_sha256'])
    path=out/OVERLAY;save(path,doc)
    from research.pooled_vacancy_funding.repair import load_repair
    loaded=load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    for cursor,pred in ((cp['source_cursor'],'0'*64),(min(t['session'] for t in doc['suppress']),cp['run']['checkpoint_sha256'])):
        try:load_repair(path,resume_session=cursor,predecessor_checkpoint_sha256=pred)
        except ValueError:pass
        else:raise ValueError('REFUSED_COMBINED_WRONG_PREDECESSOR_OR_CONSUMED_SESSION')
    return (cash,stock),loaded,path


def qualify(components,loaded,old_objects,out,*,packet_source_sha256):
    cash,stock=components
    cash.qualify(loaded,old_objects,out/'february-cash-input-qualification.json',packet_source_sha256=packet_source_sha256)
    stock.qualify(loaded,old_objects,out/'stock-calendar-input-qualification.json',packet_source_sha256=packet_source_sha256)
    save(out/'combined-calendar-input-qualification.json',dict(schema='research.combined-factual-calendar-qualification/1',
        status='BOTH_COMPONENTS_QUALIFIED_ACTUAL_COMBINED_OVERLAY',combined_sha256=loaded.sha256,
        cash_terms=len(cash.catalog['terms']),stock_terms=len(stock.catalog['terms']),
        all_old_inputs_applied=True,component_terms_and_evidence_unmodified=True,
        financial_sessions_advanced=0,production_contacted=False))

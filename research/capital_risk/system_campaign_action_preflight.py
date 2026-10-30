"""Data-only collision checks against immutable, admitted ordinary action inputs."""
import json,re
from collections import defaultdict
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import digest,sha


def analyze_new_catalog(cp,root,catalog):
    """Read hashes/terms only; never restore, execute or choose financial state."""
    suppress=defaultdict(list);add=defaultdict(list);ordinary=0
    for descriptor in cp['repairs']:
        h=descriptor['sha256'];name=descriptor['filename']
        need(re.fullmatch('[a-f0-9]{64}',h) is not None and name==h+'.json',
             'ACTION_PREFLIGHT_EXACT_RETAINED_FILENAME')
        raw=(Path(root)/'book/repairs'/name).read_bytes()
        need(sha(raw)==h,'ACTION_PREFLIGHT_EXACT_RETAINED_BYTES')
        document=json.loads(raw)
        if document['schema']=='research.leadership-uncertainty-input/1':continue
        need(document['schema']=='terminal-repair/1','ACTION_PREFLIGHT_DECLARED_ORDINARY_SCHEMA')
        ordinary+=1
        for field,index in (('suppress',suppress),('add',add)):
            for term in document[field]:
                index[term['session'],term['security_id']].append(dict(repair_sha256=h,term_sha256=digest(term)))
    conflicts=[];seen_suppress=set();seen_add=set()
    for t in catalog['terms']:
        native=t['native_session'],t['security_id'];effective=t['added']['session'],t['added']['security_id']
        need(t['security_id']==t['added']['security_id'],'ACTION_PREFLIGHT_SAME_SOURCE_IDENTITY')
        if min(native[0],effective[0])<=cp['source_cursor']:
            conflicts.append(dict(ticker=t['ticker'],reason='CONSUMED_SESSION',native_session=native[0],effective_session=effective[0]))
        for key,seen,prior,label in ((native,seen_suppress,suppress,'SUPPRESSION'),(effective,seen_add,add,'ADDITION')):
            if key in seen:conflicts.append(dict(ticker=t['ticker'],reason='INTERNAL_DUPLICATE_'+label,session=key[0],security_id=key[1]))
            seen.add(key)
            if key in prior:
                conflicts.append(dict(ticker=t['ticker'],reason='RETAINED_'+label+'_KEY_ALREADY_PRESENT',
                    session=key[0],security_id=key[1],prior_terms=prior[key]))
    return dict(schema='research.ordinary-factual-input-preflight/1',
        status='DISJOINT_UNCONSUMED' if not conflicts else 'REFUSED_PREEXISTING_OR_CONSUMED_ACTION',
        selected_outer_sha256=cp['sha256'],selected_session=cp['source_cursor'],
        selected_input_sha256=cp['run']['input_sha256'],catalog_content_sha256=digest(catalog),
        retained_ordinary_repairs=ordinary,requested_events=len(catalog['terms']),
        requested_native_keys=len(seen_suppress),requested_effective_keys=len(seen_add),conflicts=conflicts,
        no_silent_deduplication_or_override=True,financial_sessions_advanced=0,production_contacted=False)


def require_disjoint(report):
    need(report['schema']=='research.ordinary-factual-input-preflight/1'
         and report['status']=='DISJOINT_UNCONSUMED' and not report['conflicts'],
         'ACTION_PREFLIGHT_DISJOINT_UNCONSUMED_NEW_ACTIONS')

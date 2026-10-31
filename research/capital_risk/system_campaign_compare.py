"""Exact economic comparator with explicitly bounded own-origin provenance."""
from copy import deepcopy

def need(value,code):
    if not value:raise ValueError('REFUSED_CAMPAIGN_COMPARISON_'+code)

def rows(left,right):
    need(len(left)==len(right),'ROW_COUNT')
    for index,(a,b) in enumerate(zip(left,right)):
        a,b=deepcopy(a),deepcopy(b)
        for row in (a,b):
            for k in ('input_sha256','chain_sha256'):need(k in row,'IDENTITY_PRESENT');row.pop(k)
        need(a==b,'EXACT_FINANCIAL_EVIDENCE_ROW_'+str(index))

def origin_state(left,right):
    left,right=deepcopy(left),deepcopy(right)
    a=left['wealth_core']['median5'].pop('sums');b=right['wealth_core']['median5'].pop('sums')
    need(set(a)==set(b) and all(len(a[k])==len(b[k])==7 for k in a),'SAME_ORIGIN_ACCUMULATOR_AXIS')
    need(left==right,'ALL_OTHER_ORIGIN_STATE_EXACT')
    return sum(x!=y for k in a for x,y in zip(a[k],b[k]))

def facts(left,right):
    a,b=deepcopy(left),deepcopy(right)
    for value in (a,b):need('predecessor_checkpoint_sha256' in value,'FACT_PREDECESSOR');value.pop('predecessor_checkpoint_sha256')
    need(a==b,'ALL_ACTUAL_FACTS_EXACT')

def watch(left,right):
    need(len(left)==len(right),'WATCH_COUNT')
    for a,b in zip(deepcopy(left),deepcopy(right)):
        if a==b:continue
        need(a.get('schema')==b.get('schema')=='research.pooled-action-successor/1','WATCH_SCHEMA')
        for value in (a,b):
            for k in ('predecessor_checkpoint_sha256','state_sha256','successor_input_sha256'):need(k in value,'WATCH_IDENTITY_PRESENT');value.pop(k)
            overlay=value['overlay']
            for k in ('filename','predecessor_checkpoint_sha256','sha256'):need(k in overlay,'OVERLAY_IDENTITY_PRESENT');overlay.pop(k)
        need(a==b,'ALL_OTHER_WATCH_FIELDS_EXACT')

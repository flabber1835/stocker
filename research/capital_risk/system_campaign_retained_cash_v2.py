"""Hosted observation of the full authenticated ordinary cash input history."""
from contextlib import contextmanager
from copy import deepcopy
import gzip,json
from pathlib import Path

from full_system_benchmark import need
import system_campaign_retained_forward_cash as original
import system_campaign_retained_cash_materials_v2 as materials
from system_campaign_pending_cash_api import observer_initializer


def source_names():
    return (*original.source_names(),'system_campaign_retained_cash_v2.py',
            'system_campaign_retained_cash_materials_v2.py')


def full_inventory(root,cp,plan):
    root=Path(root)
    paths=[*root.glob('hydrated-future-financial-terminal-catalog-*.json'),
           *(root/materials.DIRECTORY).glob('*/hydrated-future-financial-terminal-catalog-*.json')]
    names={p.relative_to(root).as_posix() for p in paths}
    return materials.inventory(cp,plan,names,lambda name:(root/name).read_bytes())


def union_terms(*groups):
    result={}
    for group in groups:
        for term in group:
            key=term['added']['session'],term['security_id']
            need(key not in result or result[key]==term,'RETAINED_CASH_V2_NO_CONFLICTING_FULL_TERM')
            result[key]=deepcopy(term)
    return list(result.values())


def stage(root,cp,out,plan):
    from full_system_core import hosted
    hosted()
    prior=original.stage(root,cp,out,plan)
    inventory=full_inventory(root,cp,plan)
    for name,raw in inventory['resources'].items():original.write_exact(Path(out)/name,raw)
    return union_terms(prior,inventory['terms'])


@contextmanager
def context(root,cp,out,spec):
    chosen=original.selected(cp,spec)
    if not chosen:yield;return
    from full_system_core import hosted
    hosted()
    need(len(chosen)==1,'RETAINED_CASH_V2_ONE_EXPLICIT_FAMILY')
    plan,=chosen;Original=original.observer_class(plan);terms=stage(root,cp,out,plan)
    import system_campaign_financial_future as future
    need(future.ActualEvents is Original,'RETAINED_CASH_V2_EXACT_UNWRAPPED_OBSERVER')
    class ObservedCash(Original):
        def __init__(self,target,arm,*,cp=None):
            observer_initializer(Original.__init__,cp,arm)(self,target,arm,cp=cp)
            need(arm==plan['arm'] and Path(target)==Path(out),'RETAINED_CASH_V2_EXACT_ACTIVE_OUTPUT')
            original.merge_terms(self,terms)
    need(ObservedCash.advance is Original.advance and ObservedCash.terminal is Original.terminal,
         'RETAINED_CASH_V2_ORIGINAL_CALLER_FRAME_METHODS')
    future.ActualEvents=ObservedCash
    try:yield
    finally:future.ActualEvents=Original


def review(evidence,out,spec,cp):
    chosen=original.selected(cp,spec)
    if not chosen:return
    need(len(chosen)==1,'RETAINED_CASH_V2_ONE_REVIEW_FAMILY');plan,=chosen
    _,_,prior=original.checked_resources(evidence,cp,plan)
    inventory=full_inventory(evidence,cp,plan)
    terms=union_terms(prior,inventory['terms'])
    from system_campaign_uncertainty_review import committed_rows
    observed={day:json.loads(raw) for day,raw in original.committed_logs(evidence,cp,plan).items()}
    checked=original.verify_records(committed_rows(Path(evidence)/'book',cp,'daily'),
        cp['run']['state']['ledger']['events'],observed,terms,cp['source_cursor'])
    original.write_exact(Path(out)/'retained-forward-cash-review.json',original.encoded(dict(
        passed=True,events=checked,financial_sessions_reexecuted=0,retained_terms=len(terms),
        full_input_count=inventory['full_input_count'],full_tail_materials=len(inventory['entries']),
        original_observer_methods_unchanged=True,all_committed_logs_required=True)))


def review_entry(evidence,out,spec,legacy):
    from full_system_core import hosted
    hosted()
    legacy(evidence,out,spec)
    cp=json.loads(gzip.decompress((Path(evidence)/'book/checkpoint.json.gz').read_bytes()))
    review(evidence,out,spec,cp)

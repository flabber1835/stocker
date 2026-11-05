"""Unchanged financial predicates with explicit recorded/new-source domains."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import p01_iac_unit_review_recovery_adapter as previous
from p01_iac_unit_contract import FIRST,need,sha,digest
from p01_iac_reference_evidence import ORIGIN,ADMISSION,APPROVED,same,reference_spec
from p01_iac_reference_source import SCHEMA,COMPILER_ORIGIN,REPORT_ORIGIN,check_prepared,preparation_shape,report_shape
from p01_iac_unit_recovery_guard import interface,BACKTEST,ADAPTER
from p01_iac_unit_parent import OUTER

ADAPTER_SHA='8bfd5cbb445a0cd4e3b594d7bf4614b377f10437dde39f68c64d9cc196c7870c'
FIELDS={'reference_applications':('source_compiler_check','applications'),
    'reference_refusals':('source_compiler_check','refusals'),
    'fast_applications':('fresh_execution','applications'),'fast_refusals':('fresh_execution','refusals')}


def source_proof(value,contract,origin,members):
    """Explicit origins, no old names for newly observed compiler records."""
    need(set(value)=={'schema','source_contract','origin_basis','source_members','recorded_reference',
         'source_compiler_check','fresh_execution','reference_report_check','financial_authority'} and value['schema']==SCHEMA
         and same(value['source_contract'],contract) and same(value['source_members'],members)
         and value['origin_basis']==dict(source_series=origin,source_series_sha256=digest(origin),
             original_outer_sha256=OUTER) and value['financial_authority'] is False,
         'REFERENCE_REVIEW_EXPLICIT_NEW_SOURCE_PROOF_SCHEMA_AND_ORIGIN')
    recorded=value['recorded_reference'];check=value['source_compiler_check'];fresh=value['fresh_execution']
    need(set(recorded)=={'origin','source_origin','root_reuse_admission_sha256','approved_members',
         'original_compiler_and_ring_logs_available','publications'}
         and recorded['origin']=='OLD_RECORDED_REFERENCE' and same(recorded['source_origin'],ORIGIN)
         and recorded['root_reuse_admission_sha256']==ADMISSION and same(recorded['approved_members'],APPROVED)
         and recorded['original_compiler_and_ring_logs_available'] is False,
         'REFERENCE_REVIEW_NO_FABRICATED_OLD_COMPILER_OR_RING_LOG')
    need(check['origin']==COMPILER_ORIGIN and check['financial_transitions']==0 and type(check['financial_transitions']) is int
         and check['refusals']==[] and same(check['source_contract'],contract)
         and same(check['origin_basis'],value['origin_basis']) and same(check['advance_blocker'],dict(
             installed_entrypoints=['runtime.advance','runtime.advance_session','kernel.advance_session','kernel.plan_session',
                 'live.plan_session','core_adapter.step_session'],attempted_calls=[],financial_transitions=0))
         and len(check['prepared_publications'])==len(check['unit_window_anchor_checks'])==2
         and [v['session'] for v in check['prepared_publications']]==list(FIRST),
         'REFERENCE_REVIEW_PREPARATION_ONLY_ACTUAL_TWO_SOURCE_PROOFS_ZERO_ADVANCE')
    restores=check['canonical_restores']
    need(restores['origin']=='NEW_HOSTED_CANONICAL_RESTORE_OF_OLD_RECORDED_DATA'
         and restores['synthetic_wires']==18 and type(restores['synthetic_wires']) is int
         and restores['financial_transitions']==0 and type(restores['financial_transitions']) is int
         and restores['source_gate_adoption'] is False
         and restores['financial_authority'] is False and len(restores['checked'])==25,
         'REFERENCE_REVIEW_NEW_ACTUAL_CANONICAL_RESTORES_WITHOUT_STATE_ADOPTION')
    need(set(fresh)=={'origin','applications','refusals'} and fresh['origin'] in (
        'NEW_HOSTED_FAST_EXECUTION','NEW_FRESH_OWN628_FINANCE'),
        'REFERENCE_REVIEW_EXPLICIT_NEW_FAST_OR_FRESH_FINANCE_DOMAIN')
    report=value['reference_report_check']
    need(report['origin']==REPORT_ORIGIN and report['financial_transitions']==0 and type(report['financial_transitions']) is int
         and report['full_runtime_unchanged'] is report['complete_typed_report_equal'] is True,
         'REFERENCE_REVIEW_NEW_READONLY_REPORT_IS_NOT_AN_OLD_LOST_LOG')


def validate_reuse(evidence):
    """Check new provenance and source-preparation links before old predicates."""
    from p01_iac_unit_review import read
    evidence=Path(evidence);qsource=read(evidence/'qualification/unit-normalization-source-proof.json')
    fsource=read(evidence/'unit-normalization-source-proof.json')
    q=read(evidence/'qualification/actual-two-session-component.json.gz')
    provenance=read(evidence/'qualification/reference-evidence.json')
    raw_request=(evidence/'request.json').read_bytes()
    need(raw_request==Path(__file__).with_name('p01_iac_reference_request.json').read_bytes()
         and sha(raw_request)!=ORIGIN['request_sha256'],'REFERENCE_REVIEW_NEW_RAW_REQUEST_SEPARATE_FROM_OLD_ORIGIN')
    request=json.loads(raw_request)
    need(provenance['schema']=='research.p01-iac-reference-evidence-provenance/1'
         and same(provenance['specification'],reference_spec())
         and sha(provenance['original_raw_request_utf8'].encode())==ORIGIN['request_sha256']
         and provenance['financial_authority'] is provenance['qualification_state_adopted'] is False,
         'REFERENCE_REVIEW_OLD_RAW_REQUEST_AND_APPROVED_SUBSET_PROVENANCE')
    need(qsource['fresh_execution']['origin']=='NEW_HOSTED_FAST_EXECUTION'
         and fsource['fresh_execution']['origin']=='NEW_FRESH_OWN628_FINANCE'
         and same(qsource['source_compiler_check'],fsource['source_compiler_check'])
         and same(qsource['recorded_reference'],fsource['recorded_reference'])
         and same(qsource['reference_report_check'],fsource['reference_report_check']),
         'REFERENCE_REVIEW_SAVED_OLD_AND_NEW_SOURCE_CHECK_DOMAINS_UNCHANGED_IN_FINANCE')
    check=qsource['source_compiler_check'];paths=q['reference_components'];recorded=qsource['recorded_reference']
    need(recorded['publications']==[dict(session=r['session'],sha256=digest(r['publication']),
         runtime_sha256=digest(r['checkpoint'])) for r in paths]
         and same(q['reference_components'],q['actual_components'])
         and same(q['reference_qualifier_checkpoint'],q['qualifier_checkpoint']),
         'REFERENCE_REVIEW_FULL_TYPED_OLD_REFERENCE_NEW_FAST_OUTPUT_EQUALITY')
    mapping=read(evidence/'source-map.json')['successor_all_sources']
    backtest_raw=(Path('/variant')/BACKTEST).read_bytes();adapter_raw=(Path('/variant')/ADAPTER).read_bytes()
    need(same(check['callsite'],preparation_shape(backtest_raw,mapping[BACKTEST]))
         and same(check['interface'],interface(backtest_raw,adapter_raw))
         and check['advance_source_files']=={k:mapping[n] for k,n in {
             'runtime':'research/pooled_vacancy_funding/runtime.py','kernel':'sentinel/core/kernel.py',
             'live':'shared/stock_strategy_shared/wealth_core/live.py',
             'core_adapter':'shared/stock_strategy_shared/wealth_core/adapter.py'}.items()},
         'REFERENCE_REVIEW_ACTUAL516_PREPARATION_AND_NO_ADVANCE_CALLSITE_PINS')
    zero=read(evidence/'qualification/zero-session-boundaries.json')
    labels=[dict(label=label,runtime_sha256=digest(value)) for label,value in [
        ('old-epoch-zero',zero['epoch_checkpoint']['run']),('old-input-zero',zero['input_checkpoint']['run']),
        *[(f'old-reference/{r["session"]}/{k}',r[k]) for r in paths for k in ('prior_checkpoint','checkpoint')],
        ('old-reference-final',q['reference_qualifier_checkpoint']['run'])]]
    component=read(evidence/'qualification/unit-normalization-component.json.gz')
    wires=[]
    for case in component['fixture_aggregate']['expected_case_ids']:
        row=component['post_event_new_unit_case'] if case=='POST_EVENT_SOURCE_BUY' else component['target_cases'][case]
        wires.extend((row['before'],row['after'] if case=='POST_EVENT_SOURCE_BUY' else row['actual']))
    labels.extend(dict(label='old-synthetic/'+str(i),state_sha256=digest(wire)) for i,wire in enumerate(wires))
    need(len(wires)==18 and same(check['canonical_restores']['checked'],labels),
         'REFERENCE_REVIEW_ALL_25_SOURCE_BOUND_NEW_RESTORE_LABELS_AND_ENTIRE_HASHES')
    report=read(evidence/'qualification/actual-unit-accounting-and-report.json');report_check=qsource['reference_report_check']
    pins=json.loads(Path(__file__).with_name('p01_iac_unit_fixture_request.json').read_bytes())['sources']
    shape=report_shape(Path(__file__).with_name('p01_iac_unit_run.py').read_bytes(),mapping,
        Path(__file__).with_name('p01_factual_batch_accounting.py').read_bytes(),pins['p01_factual_batch_accounting.py'])
    need(same(report_check['source_contract'],shape)
         and report_check['reference_final_runtime_sha256']==digest(q['reference_qualifier_checkpoint']['run'])
         and same(report['reference'],report['fast'])
         and report_check['restored_reference_report_sha256']==digest(report['reference'])
         and report_check['fresh_fast_report_sha256']==digest(report['fast']),
         'REFERENCE_REVIEW_UNCHANGED_FULL_REPORT_CALLSITE_RUNTIME_AND_COMPLETE_REPORT_BINDINGS')
    for row,prepared,window in zip(paths,check['prepared_publications'],check['unit_window_anchor_checks']):
        application,=[a for a in check['applications'] if a['session']==row['session']]
        before=row['prior_checkpoint']
        expected=check_prepared(row['publication'],prepared['prepared_publication'],before,before,window,application)
        need(same(prepared,expected),'REFERENCE_REVIEW_FULL_RECORDED_AND_NEW_PREPARED_PUBLICATION_LINK')
    need(same(check['applications'],qsource['fresh_execution']['applications'])
         and same(check['unit_window_anchor_checks'],q['unit_window_anchor_checks']),
         'REFERENCE_REVIEW_ACTUAL_NEW_COMPILER_AND_FULL_RING_PROOFS_MATCH_FAST')
    return dict(schema='research.p01-iac-reference-reuse-review-binding/1',root_reuse_admission_sha256=ADMISSION,
        recorded_reference_origin=deepcopy(ORIGIN),reference_evidence_sha256=sha((evidence/'qualification/reference-evidence.json').read_bytes()),
        actual_new_request_sha256=sha(raw_request),actual_new_driver_source_count=len(request['sources']),
        original_compiler_and_ring_logs_available=False,new_source_proof_schema=SCHEMA,
        source_compiler_origin=COMPILER_ORIGIN,recorded_reference_financial_transitions_reexecuted=0,
        reference_report_origin=REPORT_ORIGIN,
        source_preparations=2,fresh_fast_transitions=2,old_synthetic_wires_newly_restored=18,
        financial_origin='ORIGINAL_ADMITTED_OWN628',qualification_state_adopted=False,
        old_financial_predicates_preserved=True)


def _node(name):
    need(sha(Path(previous.__file__).read_bytes())==ADAPTER_SHA,'REFERENCE_EXACT_SINGLE_SAVE_REVIEW_ADAPTER')
    node=previous._node(name);changes=[];fields=[]
    class Scope(ast.NodeTransformer):
        def visit_ImportFrom(self,item):
            names=[(n.name,n.asname) for n in item.names]
            if item.module=='p01_iac_unit_epoch':
                need(name=='review' and names==[('historical_epoch',None)],'REFERENCE_REVIEW_EXACT_LOCAL_QUOTE_CONTEXT_IMPORT')
                item.module='p01_iac_quote_epoch';changes.append('quote_context')
            if item.module=='p01_iac_unit_review_recovery_adapter':
                need(name=='review_loaded' and names==[('save_review','save')],'REFERENCE_REVIEW_EXACT_SINGLE_SAVE_SITE')
                item.module='p01_iac_reference_review';changes.append('single_save')
            if item.module=='p01_iac_unit_fixture_export':
                need(name=='review_loaded' and names==[('qualification',None)],'REFERENCE_REVIEW_EXACT_NEW_QUALIFICATION_GATE')
                item.module='p01_iac_reference_export';changes.append('q_gate')
            return item
        def visit_Subscript(self,item):
            item=self.generic_visit(item)
            if isinstance(item.value,ast.Name) and item.value.id in ('qsource','fsource') \
                    and isinstance(item.slice,ast.Constant) and item.slice.value in FIELDS:
                first,second=FIELDS[item.slice.value];fields.append((item.value.id,item.slice.value))
                return ast.copy_location(ast.parse(item.value.id+'['+repr(first)+']['+repr(second)+']').body[0].value,item)
            return item
    node=Scope().visit(node)
    need(changes==({'review':['quote_context'],'review_loaded':['single_save','q_gate']}[name]),
         'REFERENCE_REVIEW_ONLY_THREE_DECLARED_LOCAL_IMPORT_SITES')
    need((name=='review' and fields==[]) or (name=='review_loaded' and len(fields)==18),
         'REFERENCE_REVIEW_EXACT_EXPLICIT_SOURCE_DOMAIN_ACCESS_SITES')
    return node


def _body(name):
    node=_node(name);values=dict(previous._body(name).__globals__,source_proof=source_proof,
        review=review,review_loaded=review_loaded,__file__=__file__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<source-bound-reference-reuse-review:'+name+'>','exec'),values)
    return values[name]


def save_review(path,result):
    # Called at the same one exclusive create; no second result save.
    result['reference_reuse_review']=validate_reuse(Path('/evidence'))
    return previous.save_review(path,result)


def review(*args,**kwargs):return _body('review')(*args,**kwargs)
def review_loaded(*args,**kwargs):return _body('review_loaded')(*args,**kwargs)
main=review

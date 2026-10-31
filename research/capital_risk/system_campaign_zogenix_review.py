"""Hosted independent continuation of the admitted original interval proof."""
from dataclasses import replace
from fractions import Fraction
import gzip,json
from pathlib import Path
from types import SimpleNamespace
from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha
from system_campaign_uncertainty_context import discrete,encoded
from system_campaign_uncertainty_review import seed,committed_rows
from system_campaign_uncertainty_math import Interval,RollingWitnessBounds,growth
from system_campaign_uncertainty_gate import certified_recovery
from system_campaign_zogenix_input import SID,NATIVE,DAY,require_no_position
from system_campaign_zogenix_facts import PRIVATE
from system_campaign_zogenix_basis import validate


def event_checkpoint(root,row):
    from research.pooled_vacancy_funding import journal
    matches=[]
    for path in (root/'book/pre-event').glob(DAY+'-*.json.gz'):
        raw=path.read_bytes();cp=journal.read_checkpoint(path)
        need(path.name==DAY+'-'+cp['sha256']+'.json.gz','ZOGENIX_CANONICAL_EVENT_ARCHIVE_NAME')
        if cp['run']['state_sha256']==row['prior_state_sha256'] and cp['run']['input_sha256']==row['input_sha256']:
            matches.append((path,cp,sha(raw)))
    need(len(matches)==1,'ZOGENIX_UNIQUE_ACTUAL_EVENT_PREDECESSOR')
    path,cp,file_sha=matches[0]
    need(cp['source_cursor']==NATIVE,'ZOGENIX_EXACT_LAST_TRADING_EVENT_PREDECESSOR')
    return cp,dict(path=path.relative_to(root).as_posix(),file_sha256=file_sha,outer_sha256=cp['sha256'])


def review(root,old,spec,output):
    hosted()
    from research.pooled_vacancy_funding import journal
    from sentinel.controller import median5,champion_config
    cp=journal.read_checkpoint(root/'book/checkpoint.json.gz');parent=journal.read_checkpoint(old/spec['selected_checkpoint'])
    need(parent['sha256']==spec['outer_sha256'] and parent['source_cursor']=='2022-02-28'
         and parent['completed']==1047,'ZOGENIX_EXACT_REVIEWED_PARENT')
    prior_raw=(old/'uncertainty-certificate-review.json').read_bytes();prior=json.loads(prior_raw)
    need(sha(prior_raw)==spec['interval_review_sha256'] and prior['checkpoint_sha256']==parent['sha256']
         and prior['rows']==593 and prior['every_actual_comparison_invariant']
         and prior['every_committed_watch_and_financial_row_bound']
         and prior['every_discrete_controller_state_equal'],'ZOGENIX_AUTHENTICATED_PARENT_FULL_PROOF')
    inherited=seed(old,parent);rows=seed(root,cp);n=len(inherited)
    need(n==593 and rows[:n]==inherited,'ZOGENIX_ALL_ORIGINAL_COMMITTED_CERTIFICATES_IDENTICAL')
    original=(old/'uncertainty-certificate.jsonl').read_bytes()
    need((root/'lineage/uncertainty-certificate-original.jsonl').read_bytes()==original,
         'ZOGENIX_PARENT_ENTIRE_CERTIFICATE_AND_UNSENT_TAIL_PRESERVED')
    models=validate(root,cp)
    need(models or len(rows)==n,'ZOGENIX_NEW_ROWS_REQUIRE_ADMITTED_INPUT')
    math=RollingWitnessBounds.restore(inherited[-1]['math']);previous=inherited[-1]['after']
    financial={r['session']:r for r in committed_rows(root/'book',cp,'daily')}
    source=json.loads((root/PRIVATE).read_bytes());checks_count=prior['comparisons'];resolution=None
    for row in rows[n:]:
        need(row['before']==previous and row['representative_is_not_a_valuation']
             and row['owned_position'] is False and row['pending_order'] is False,
             'ZOGENIX_INDUCTIVE_DISCRETE_STATE_AND_NOTIONAL_SCOPE')
        material=row['material']['rows'];names=[v['security_id'] for v in material]
        need(len(names)==len(set(names)),'ZOGENIX_UNIQUE_WITNESS_MEMBERS')
        selected=False
        if row['session']==DAY:
            before,resolution=event_checkpoint(root,row);state=before['run']['state']
            require_no_position(SimpleNamespace(wealth_core=state['wealth_core'],pending=state['pending']))
            need(names==state['median5']['selected'] and all(v['prior']==state['median5']['selected_closes'][v['security_id']]
                 for v in material),'ZOGENIX_ACTUAL_EVENT_WITNESS_PREIMAGE')
            event=row['additional_event_basis'];selected=SID in names
            need(event['selected'] is selected and event['session']==DAY and event['security_id']==SID,
                 'ZOGENIX_ACTUAL_EVENT_SELECTED_OR_ABSENT')
            if selected:
                anchor=state['feed']['series'][SID]['signal_basis_anchor']
                need([event['prior_session'],event['raw_anchor'],event['signal_anchor']]==
                     [anchor[0],str(anchor[1]),str(anchor[2])] and anchor[0]==NATIVE,
                     'ZOGENIX_ACTUAL_RAW_SIGNAL_EVENT_ANCHOR')
                need(event['source_term_sha256']==digest({**source['actual_native'],'session':DAY})
                     and event['source_event_sha256']==digest(source) and event['split']=='1'
                     and source['source_quote_present'] is False,'ZOGENIX_EXACT_NATIVE_AND_EVENT_WITNESSES')
                raw,signal=map(Fraction,(event['raw_anchor'],event['signal_anchor']))
                need(raw>0 and signal>0,'ZOGENIX_NORMAL_EVENT_PRICE_BASIS')
                expected=[float(26*signal/raw),float(28*signal/raw)]
                actual,=[v for v in material if v['security_id']==SID]
                need(actual['current']==event['signal_consideration_interval']==expected,
                     'ZOGENIX_WHOLE_NEW_CONSIDERATION_RANGE')
        else:need('additional_event_basis' not in row,'ZOGENIX_NO_UNDECLARED_EXTRA_EVENT')
        returns=[]
        for item in material:
            bound=Interval(*item['current'])
            need(selected and item['security_id']==SID or bound.lo==bound.hi,
                 'ZOGENIX_ONLY_EXPLICIT_NEW_EVENT_CAN_VARY')
            returns.append(bound.div(Interval.point(item['prior'])).sub(Interval.point(1.)))
        factor=growth(returns);need(factor.pair()==row['material']['factor'],'ZOGENIX_INDEPENDENT_FACTOR_ORDER')
        math.advance(factor,row['material']['representative_nav'])
        need(math.snapshot()==row['math'],'ZOGENIX_ORIGINAL_AND_NEW_UNCERTAINTY_CONTINUATION')
        bounds={f'recent_r{k}':math.period(k) for k in (20,40)}
        need({k:v.pair() if v is not None else None for k,v in bounds.items()}==row['intervals'],
             'ZOGENIX_EVERY_ROUNDING_AWARE_BOUND')
        state=median5.fresh(champion=True);state.update(row['before']);state['last_session']=row['session']
        kwargs=dict(row['scalar_inputs'],state=state)
        need(all(kwargs[k]==row['material']['observed'][k] for k in bounds),'ZOGENIX_ACTUAL_OBSERVED_SCALARS')
        (after,decision),checks=certified_recovery(champion_config.recover,kwargs,bounds)
        need(checks==row['comparisons'] and discrete(after)==row['after'] and decision==row['decision'],
             'ZOGENIX_ACTUAL_CANONICAL_COMPARISONS_AND_FULL_DISCRETE_STATE')
        actual=financial[row['session']]
        need(actual['decision']['ldrc']==decision and actual['decision']['native_target_core_exposure']==kwargs['native'],
             'ZOGENIX_ACTUAL_FINANCIAL_CONTROLLER_DECISION')
        previous=discrete(after);checks_count+=len(checks)
    need(previous==discrete(cp['run']['state']['median5'])
         and math.absolute.contains(cp['run']['state']['median5']['witness_nav'][-1]),'ZOGENIX_CURRENT_CANONICAL_WITNESS_STATE')
    if cp['source_cursor']>=DAY:need(resolution is not None,'ZOGENIX_EVENT_PROOF_REQUIRED')
    save(output,dict(schema='research.joint-leadership-uncertainty-independent-review/1',
        status='COMMITTED_PREFIX_JOINT_INTERVAL_INVARIANT',rows=len(rows),comparisons=checks_count,
        through=cp['source_cursor'],checkpoint_sha256=cp['sha256'],inherited_rows=n,
        exact_parent_interval_proof_sha256=sha(prior_raw),event_resolution=resolution,
        original_certificate_and_entire_tail_preserved=True,every_actual_comparison_invariant=True,
        every_committed_watch_and_financial_row_bound=True,every_discrete_controller_state_equal=True,
        financial_path_invariant_over_declared_sensor_interval=True,independent_uncertainty_assumption=False,
        witness_valuation_unique=False,representative_is_not_a_valuation=True,no_owned_cvr_accounting_supported=True,
        full_period_complete=cp['completed']==2156,production_contacted=False))

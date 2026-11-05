"""Hosted independent continuation of the admitted four-event interval proof."""
import shutil
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace
from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha
from system_campaign_uncertainty_context import discrete
from system_campaign_uncertainty_review import seed,committed_rows
from system_campaign_uncertainty_math import Interval,RollingWitnessBounds,growth
from system_campaign_uncertainty_gate import certified_recovery
from system_campaign_chinook_input import SID,NATIVE,DAY,require_no_position
from system_campaign_chinook_facts import PRIVATE
from system_campaign_chinook_basis import validate
from system_campaign_completion_scope import review_guards
from system_campaign_completion_basis import validate as validate_completion
from system_campaign_abiomed_review import review_positions as review_prior_positions
from system_campaign_spring2023_review import preserve_parent as preserve_prior_parent


def event_checkpoint(root,row):
    from research.pooled_vacancy_funding import journal
    matches=[]
    for path in (root/'book/pre-event').glob(DAY+'-*.json.gz'):
        raw=path.read_bytes();cp=journal.read_checkpoint(path)
        need(path.name==DAY+'-'+cp['sha256']+'.json.gz','CHINOOK_CANONICAL_EVENT_ARCHIVE_NAME')
        if cp['run']['state_sha256']==row['prior_state_sha256'] and cp['run']['input_sha256']==row['input_sha256']:
            matches.append((path,cp,sha(raw)))
    need(len(matches)==1,'CHINOOK_UNIQUE_ACTUAL_EVENT_PREDECESSOR')
    path,cp,file_sha=matches[0]
    need(cp['source_cursor']==NATIVE,'CHINOOK_EXACT_LAST_TRADING_EVENT_PREDECESSOR')
    return cp,dict(path=path.relative_to(root).as_posix(),file_sha256=file_sha,outer_sha256=cp['sha256'])


def review(root,old,spec,output):
    hosted()
    from research.pooled_vacancy_funding import journal
    from sentinel.controller import median5,champion_config
    cp=journal.read_checkpoint(root/'book/checkpoint.json.gz');parent=journal.read_checkpoint(old/spec['selected_checkpoint'])
    need(parent['sha256']==spec['outer_sha256'] and parent['source_cursor']==spec['selected_session']
         and parent['source_cursor']<=cp['source_cursor'],'CHINOOK_EXACT_REVIEWED_PARENT')
    prior_raw=(old/'uncertainty-certificate-review.json').read_bytes();prior=json.loads(prior_raw)
    need((root/'parent-three-sensor-certificate-review.json').read_bytes()==prior_raw,
         'CHINOOK_EXACT_REUSED_PARENT_PROOF_COPY')
    need(sha(prior_raw)==spec['interval_review_sha256'] and prior['checkpoint_sha256']==parent['sha256']
         and prior['through']==parent['source_cursor'] and prior['every_actual_comparison_invariant']
         and prior['every_committed_watch_and_financial_row_bound']
         and prior['every_discrete_controller_state_equal'],'CHINOOK_AUTHENTICATED_PARENT_FULL_PROOF')
    need(sha((old/'completion-position-guard-review.json').read_bytes())==spec['completion_guard_review_sha256'],
         'CHINOOK_EXACT_PARENT_POSITION_GUARD_PROOF')
    prior_models = validate(old, parent)
    if prior_models:
        need(prior['every_new_chinook_before_and_after_position_and_intent_checked'] is True
             and (parent['source_cursor'] < DAY or prior.get('chinook_event_resolution') is not None),
             'CHINOOK_AUTHENTICATED_RETAINED_EVENT_PARENT')
    else:
        need(parent['source_cursor'] < NATIVE and prior.get('chinook_event_resolution') is None,
             'CHINOOK_FIRST_INPUT_REQUIRES_UNCONSUMED_PARENT')
    inherited=seed(old,parent);rows=seed(root,cp);n=len(inherited)
    need(n==prior['rows'] and n>0 and rows[:n]==inherited,'CHINOOK_ALL_ORIGINAL_COMMITTED_CERTIFICATES_IDENTICAL')
    original=(old/'uncertainty-certificate.jsonl').read_bytes()
    need((root/'lineage/uncertainty-certificate-original.jsonl').read_bytes()==original,
         'CHINOOK_PARENT_ENTIRE_CERTIFICATE_AND_UNSENT_TAIL_PRESERVED')
    models=validate(root,cp)
    need(models or len(rows)==n,'CHINOOK_NEW_ROWS_REQUIRE_ADMITTED_INPUT')
    math=RollingWitnessBounds.restore(inherited[-1]['math']);previous=inherited[-1]['after']
    financial={r['session']:r for r in committed_rows(root/'book',cp,'daily')}
    source=json.loads((root/PRIVATE).read_bytes());checks_count=prior['comparisons'];resolution=prior.get('chinook_event_resolution')
    for row in rows[n:]:
        need(row['before']==previous and row['representative_is_not_a_valuation']
             and row['owned_position'] is False and row['pending_order'] is False,
             'CHINOOK_INDUCTIVE_DISCRETE_STATE_AND_NOTIONAL_SCOPE')
        material=row['material']['rows'];names=[v['security_id'] for v in material]
        need(len(names)==len(set(names)),'CHINOOK_UNIQUE_WITNESS_MEMBERS')
        selected=False
        if row['session']==DAY:
            before,resolution=event_checkpoint(root,row);state=before['run']['state']
            require_no_position(SimpleNamespace(wealth_core=state['wealth_core'],pending=state['pending']))
            need(names==state['median5']['selected'] and all(v['prior']==state['median5']['selected_closes'][v['security_id']]
                 for v in material),'CHINOOK_ACTUAL_EVENT_WITNESS_PREIMAGE')
            event=row['chinook_event_basis'];selected=SID in names
            need(event['selected'] is selected and event['session']==DAY and event['security_id']==SID,
                 'CHINOOK_ACTUAL_EVENT_SELECTED_OR_ABSENT')
            if selected:
                anchor=state['feed']['series'][SID]['signal_basis_anchor']
                need([event['prior_session'],event['raw_anchor'],event['signal_anchor']]==
                     [anchor[0],str(anchor[1]),str(anchor[2])] and anchor[0]==NATIVE,
                     'CHINOOK_ACTUAL_RAW_SIGNAL_EVENT_ANCHOR')
                need(event['source_term_sha256']==digest({**source['actual_native'],'session':DAY})
                     and event['source_event_sha256']==digest(source) and event['split']=='1'
                     and source['source_quote_present'] is False,'CHINOOK_EXACT_NATIVE_AND_EVENT_WITNESSES')
                raw,signal=map(Fraction,(event['raw_anchor'],event['signal_anchor']))
                need(raw>0 and signal>0,'CHINOOK_NORMAL_EVENT_PRICE_BASIS')
                expected=[float(40*signal/raw),float(44*signal/raw)]
                actual,=[v for v in material if v['security_id']==SID]
                need(actual['current']==event['signal_consideration_interval']==expected,
                     'CHINOOK_WHOLE_NEW_CONSIDERATION_RANGE')
        else:need('chinook_event_basis' not in row,'CHINOOK_NO_UNDECLARED_EXTRA_EVENT')
        returns=[]
        for item in material:
            bound=Interval(*item['current'])
            need(selected and item['security_id']==SID or bound.lo==bound.hi,
                 'CHINOOK_ONLY_EXPLICIT_NEW_EVENT_CAN_VARY')
            returns.append(bound.div(Interval.point(item['prior'])).sub(Interval.point(1.)))
        factor=growth(returns);need(factor.pair()==row['material']['factor'],'CHINOOK_INDEPENDENT_FACTOR_ORDER')
        math.advance(factor,row['material']['representative_nav'])
        need(math.snapshot()==row['math'],'CHINOOK_ORIGINAL_AND_NEW_UNCERTAINTY_CONTINUATION')
        bounds={f'recent_r{k}':math.period(k) for k in (20,40)}
        need({k:v.pair() if v is not None else None for k,v in bounds.items()}==row['intervals'],
             'CHINOOK_EVERY_ROUNDING_AWARE_BOUND')
        state=median5.fresh(champion=True);state.update(row['before']);state['last_session']=row['session']
        kwargs=dict(row['scalar_inputs'],state=state)
        need(all(kwargs[k]==row['material']['observed'][k] for k in bounds),'CHINOOK_ACTUAL_OBSERVED_SCALARS')
        (after,decision),checks=certified_recovery(champion_config.recover,kwargs,bounds)
        need(checks==row['comparisons'] and discrete(after)==row['after'] and decision==row['decision'],
             'CHINOOK_ACTUAL_CANONICAL_COMPARISONS_AND_FULL_DISCRETE_STATE')
        actual=financial[row['session']]
        need(actual['decision']['ldrc']==decision and actual['decision']['native_target_core_exposure']==kwargs['native'],
             'CHINOOK_ACTUAL_FINANCIAL_CONTROLLER_DECISION')
        previous=discrete(after);checks_count+=len(checks)
    need(previous==discrete(cp['run']['state']['median5'])
         and math.absolute.contains(cp['run']['state']['median5']['witness_nav'][-1]),'CHINOOK_CURRENT_CANONICAL_WITNESS_STATE')
    if cp['source_cursor']>=DAY:need(resolution is not None,'CHINOOK_EVENT_PROOF_REQUIRED')
    completion_proof=review_positions(root,old,cp,parent,financial)
    save(output.parent/'completion-position-guard-review.json',completion_proof)
    save(output,dict(schema='research.joint-leadership-uncertainty-independent-review/1',
        status='COMMITTED_PREFIX_JOINT_INTERVAL_INVARIANT',rows=len(rows),comparisons=checks_count,
        through=cp['source_cursor'],checkpoint_sha256=cp['sha256'],inherited_rows=n,
        exact_parent_interval_proof_sha256=sha(prior_raw),event_resolution=prior['event_resolution'],
        guarded_completion_events=prior['guarded_completion_events'],
        abiomed_event_resolution=prior['abiomed_event_resolution'],chinook_event_resolution=resolution,
        original_certificate_and_entire_tail_preserved=True,every_actual_comparison_invariant=True,
        every_committed_watch_and_financial_row_bound=True,every_discrete_controller_state_equal=True,
        financial_path_invariant_over_declared_sensor_interval=True,independent_uncertainty_assumption=False,
        witness_valuation_unique=False,representative_is_not_a_valuation=True,no_owned_cvr_accounting_supported=True,
        every_new_abiomed_before_and_after_position_and_intent_checked=True,
        every_new_chinook_before_and_after_position_and_intent_checked=True,
        full_period_complete=cp['completed']==2156,production_contacted=False))


def preserve_parent(old, out, cp, spec):
    """Keep every old proof and any already resolved fourth event verbatim."""
    from research.pooled_vacancy_funding import journal
    proof = preserve_prior_parent(old, out, cp, spec)
    event = proof.get('chinook_event_resolution')
    if event is not None:
        path = Path(event['path'])
        need(not path.is_absolute() and '..' not in path.parts
             and path.parts[:2] == ('book', 'pre-event'), 'CHINOOK_SAFE_PARENT_EVENT_PATH')
        raw = (old / path).read_bytes()
        value = journal.read_checkpoint(old / path)
        need(sha(raw) == event['file_sha256'] and value['sha256'] == event['outer_sha256']
             and value['source_cursor'] == NATIVE, 'CHINOOK_ACTUAL_PARENT_EVENT_BYTES')
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            need(target.read_bytes() == raw, 'CHINOOK_EXISTING_PARENT_EVENT_BYTES')
        else:
            shutil.copyfile(old / path, target)
    save(out / 'chinook-parent-certificate-admission.json', dict(
        checkpoint_sha256=cp['sha256'], through=cp['source_cursor'], rows=proof['rows'],
        exact_parent_interval_proof_sha256=sha((old / 'uncertainty-certificate-review.json').read_bytes()),
        chinook_event_resolution=event, all_old_event_proofs_preserved=True,
        production_contacted=False))
    return proof


def review_positions(root, old, cp, parent, financial_by_day):
    """Original ABIOMED/completion checks plus each new Chinook transition."""
    complete = review_prior_positions(root, old, cp, parent, financial_by_day)
    before = SimpleNamespace(wealth_core=parent['run']['state']['wealth_core'],
                             pending=parent['run']['state']['pending'])
    for day in sorted(financial_by_day):
        if day <= parent['source_cursor']:
            continue
        row = financial_by_day[day]
        audit = row['evidence']['research_entry_audit']
        opening, closing = audit['opening_accounting'], audit['closing_accounting']
        if day >= NATIVE:
            for state in (before,
                SimpleNamespace(wealth_core=opening['wealth_core'], pending=opening['pending']),
                SimpleNamespace(wealth_core=closing['wealth_core'], pending=closing['pending'])):
                require_no_position(state)
            need(all(v['security_id'] != SID for v in row['evidence']['wealth_core']['intents']),
                 'CHINOOK_EVERY_ACTUAL_NEW_INTENT_ABSENT')
        before = SimpleNamespace(wealth_core=closing['wealth_core'], pending=closing['pending'])
    return complete

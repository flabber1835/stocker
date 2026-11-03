"""Hosted-only two-day canonical component qualification; never account replay."""
import argparse
from dataclasses import replace
import gzip
import json
import os
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_discovery_context import material, digest, require_strict_checkpoint
from system_campaign_discovery_replay import source_iterator
from system_campaign_p01_discovery_inputs import retained_inputs
from p01_action_clock_contract import AUTHORITY, SID, OLD, NEW, Clock, proposal
from p01_action_clock_parent import specification, reference


def durable(path, value, *, compressed=False):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(material(value), sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    if compressed:
        raw = gzip.compress(raw, mtime=0)
    pending = path.with_suffix(path.suffix+'.partial')
    with pending.open('wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    os.replace(pending, path)


def roles(checkpoint):
    state = checkpoint['state']
    held = [dict(episode=str(k), **v) for k, v in state['wealth_core']['episodes'].items()
            if v['security_id'] == SID]
    pending = [p for p in state['pending'] if p.get('security_id') == SID]
    median = state['median5']
    return dict(held=held, pending=pending, selected_leadership=SID in median['selected'],
        selected_close=median['selected_closes'].get(SID),
        unresolved_terminal=SID in state['wealth_core'].get('unresolved_terminals', []),
        session=state['last_processed_session'], state_sha256=checkpoint['state_sha256'])


def wrapper(cp, *, parent, transitions):
    value = dict(schema='research.p01-action-clock-qualification-checkpoint/1',
        authority=AUTHORITY, financial_authority=False, financial_predecessor_authorized=False,
        parent_outer_sha256=parent['sha256'], component_transitions=transitions,
        runtime_checkpoint=cp, account_replay_performed=False)
    try:
        require_strict_checkpoint(value)
    except ValueError:
        return value
    raise ValueError('P01_CLOCK_QUALIFICATION_ENTERED_STRICT_FINANCIAL_REPLAY')


def classify(error):
    if error is None:
        return None
    prefix = str(error).partition(':')[0]
    return prefix if prefix in {
        'incomplete leadership cash terminal', 'incomplete leadership conversion',
        'leadership conversion lacks delivered close', 'leadership terminal lacks prior price basis',
        'unsupported leadership terminal'} else 'OTHER_CANONICAL_REFUSAL'


def qualify(root, out, spec):
    hosted()
    from research.pooled_vacancy_funding import runtime, journal
    from system_campaign_acceleration import Execution
    root, out = Path(root), Path(out)
    original = (root/spec['selected_checkpoint']).read_bytes()
    parent = require_strict_checkpoint(journal.read_checkpoint(root/spec['selected_checkpoint']))
    contract = proposal(spec)
    need(parent['sha256'] == contract.parent_outer and parent['completed'] == 438
         and parent['source_cursor'] == '2019-09-27', 'P01_CLOCK_EXACT_OWN438_BEFORE_SOURCE_RESTORE')
    durable(out/'parent-reference.json', reference(spec))
    durable(out/'proposal.json', contract.model_dump())
    proof = dict(schema='research.p01-action-clock-component-qualification/1', authority=AUTHORITY,
        financial_authority=False, financial_predecessor_authorized=False,
        strict_parent_outer_sha256=parent['sha256'], baseline_reproduced=False,
        original_eight_inputs_unchanged=True, financial_source_changed=False,
        baseline_canonical_transitions=0, component_transitions=0, financial_journal_commits=0,
        account_replay_performed=False, exact_exchange_last_trade_notice_admitted=False,
        settlement_terms_supplied=False, production_contacted=False, status='PREPARING')
    durable(out/'qualification-summary.json', proof)
    with retained_inputs(root, parent, out):
        run, buffer, packets, repaired, wanted = source_iterator(parent, root)
        need(wanted[:2] == [OLD, NEW], 'P01_CLOCK_EXACT_NEXT_TWO_DAYS')
        prior = runtime.checkpoint(run)
        need(prior == parent['run'], 'P01_CLOCK_FULL_CANONICAL_PARENT_ROUNDTRIP')
        durable(out/'parent-runtime.json.gz', wrapper(prior, parent=parent, transitions=0), compressed=True)
        proof['parent_roles'] = roles(prior)
        packet = repaired(next(packets))
        need(packet.day == OLD, 'P01_CLOCK_ORIGINAL_FIRST_SESSION')
        buffer.append(packet)
        error = None
        with Execution('FAST', signal_closes=1) as acceleration:
            baseline = buffer.prepare(run.state, run.state.data_version+1, formation=False)
            durable(out/'baseline-publication.json.gz', material(baseline), compressed=True)
            durable(out/'phase.json', dict(authority=AUTHORITY, phase='BEFORE_BASELINE_ADVANCE'))
            try:
                runtime.advance(run, baseline)
            except ValueError as refused:
                error = refused
            need(error is not None and str(error) == 'incomplete leadership cash terminal: '+SID,
                 'P01_CLOCK_REPRODUCE_EXACT_ORIGINAL_REFUSAL')
            need(runtime.checkpoint(run) == prior, 'P01_CLOCK_BASELINE_REFUSAL_ZERO_MUTATION')
            proof.update(baseline_reproduced=True, baseline_refusal=classify(error),
                baseline_original_runtime_unchanged=True, status='BASELINE_REFUSAL_REPRODUCED')
            durable(out/'qualification-summary.json', proof)
            # Restore the original immutable runtime rather than reuse any failed call state.
            run = runtime.restore(parent['run'], policy=parent['base']['policy'],
                                  input_sha256=parent['run']['input_sha256'])
            need(runtime.checkpoint(run) == prior, 'P01_CLOCK_FRESH_CANDIDATE_RESTORE')
            clock = Clock(contract)
            for i, day in enumerate((OLD, NEW)):
                if i:
                    packet = repaired(next(packets)); need(packet.day == day, 'P01_CLOCK_CANDIDATE_AXIS')
                changed = clock.apply(packet)
                if i:
                    buffer.append(changed)
                else:
                    # Same already-appended original quote/window; only the current terminal tuple differs.
                    buffer.current = changed
                cp = runtime.checkpoint(run)
                record = dict(session=day, prior_roles=roles(cp), prior_checkpoint_sha256=cp['checkpoint_sha256'])
                durable(out/f'candidate-{day}-before.json', record)
                published = buffer.prepare(run.state, run.state.data_version+1, formation=False)
                if not i:
                    a, b = material(baseline), material(published)
                    need({k:v for k,v in a.items() if k != 'terminal_events'} ==
                         {k:v for k,v in b.items() if k != 'terminal_events'},
                         'P01_CLOCK_SAME_REAL_PUBLICATION_EXCEPT_TERMINAL')
                durable(out/f'candidate-{day}-publication.json.gz', material(published), compressed=True)
                durable(out/'phase.json', dict(authority=AUTHORITY, phase='BEFORE_CANDIDATE_ADVANCE', session=day))
                error = None
                try:
                    following = runtime.advance(run, published)
                except Exception as refused:
                    error = refused
                if error is not None:
                    need(runtime.checkpoint(run) == cp, 'P01_CLOCK_CANDIDATE_REFUSAL_NO_PRIOR_MUTATION')
                    record.update(outcome='REFUSED', error_class=type(error).__name__,
                        refusal_class=classify(error), error_value=str(error))
                    durable(out/f'candidate-{day}-result.json', record)
                    proof.update(status='CLOCK_CANDIDATE_REFUSED', refused_session=day,
                        refusal_class=classify(error), last_roles=roles(cp))
                    break
                run = following
                cp = runtime.checkpoint(run)
                need(cp['state']['last_processed_session'] == day, 'P01_CLOCK_EXACT_CANONICAL_SESSION_ADVANCED')
                proof['component_transitions'] += 1
                record.update(outcome='ADVANCED', next_roles=roles(cp),
                    next_checkpoint_sha256=cp['checkpoint_sha256'])
                durable(out/f'candidate-{day}-result.json', record)
                durable(out/f'candidate-{day}-runtime.json.gz',
                    wrapper(cp, parent=parent, transitions=proof['component_transitions']), compressed=True)
                proof.update(status='CANDIDATE_COMPONENT_PROGRESS', last_roles=roles(cp))
                durable(out/'qualification-summary.json', proof)
            proof['clock'] = clock.proof()
        durable(out/'acceleration-proof.json', acceleration.proof())
    need((root/spec['selected_checkpoint']).read_bytes() == original, 'P01_CLOCK_PARENT_GZIP_STILL_EXACT')
    need(not (out/'book').exists(), 'P01_CLOCK_NO_FINANCIAL_BOOK_OR_JOURNAL')
    if proof['component_transitions'] == 2:
        proof['status'] = 'TWO_DAY_COMPONENT_OBSERVED_NOT_FINANCIAL_ADMISSION'
    proof['strict_parent_unchanged'] = True
    durable(out/'qualification-summary.json', proof)
    durable(out/'phase.json', dict(authority=AUTHORITY, phase='COMPONENT_OBSERVATION_FINISHED'))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--spec', type=Path, required=True)
    args = p.parse_args(); hosted()
    spec = specification(); need(json.loads(args.spec.read_bytes()) == spec, 'P01_CLOCK_EXACT_MOUNTED_SPEC')
    qualify(Path('/old'), Path('/out'), spec)

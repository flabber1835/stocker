"""Hosted three-path RW1 experiment; original Core and canonical accounting only."""
import argparse
from copy import deepcopy
from datetime import date
from decimal import Decimal as D, localcontext
from fractions import Fraction as Q
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

from p00_recovery_watch_policy import (
    BASELINE, NO_EXTRA, CANDIDATE, RecoveryWatch, canary, hosted, need,
    profiles, parent_module, targets, independent_targets,
)
from p00_recovery_hold_worker import load, monthly, changed_scope, windows


BLOCKS = (('2018-2020', '2018-01-02', '2020-12-31'),
          ('2021-2022', '2021-01-01', '2022-12-30'),
          ('2023-2024', '2023-01-01', '2024-12-31'),
          ('2025-2026Jul', '2025-01-01', '2026-07-31'))
CONTROL_JOURNALS = {
    BASELINE: dict(bytes=3166200, records=2156,
                   prefix_sha256='24c335da2a239c05bdd74f9ab661a926c3e8c430f4db6bd0ef7232af9ecb6c26'),
    NO_EXTRA: dict(bytes=3167118, records=2156,
                   prefix_sha256='8c8b823e8220c92b31fb339a2618b4aee14faa6ade8216903c4a7f8f3ee9ce78'),
}


def write(path, value):
    need(not path.exists(), 'OUTPUT_COLLISION')
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False) + '\n')


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'


def read_journal(path):
    with gzip.open(path, 'rt') as stream:
        return [json.loads(line) for line in stream]


def reference_controls(paths, commitments=None):
    hosted()
    import numpy as np
    refs = json.loads(Path('/driver/p00-sentinel-grid-references.json').read_bytes())
    need(refs['schema'] == 'research.p00-sentinel-grid-references/1', 'CONTROL_REFERENCE_SCHEMA')
    for index, pid in enumerate((BASELINE, NO_EXTRA)):
        actual = hashlib.sha256(np.asarray(paths[index], dtype='<f8').tobytes()).hexdigest()
        need(actual == refs['profiles'][pid]['measured_target_sha256'], 'PRIOR_COMPLETE_CONTROL_TARGET_HASH')
        if commitments is not None:
            need(commitments[pid] == CONTROL_JOURNALS[pid], 'PRIOR_COMPLETE_CONTROL_ACCOUNT_JOURNAL')


def state_transition(before, after):
    keys = ('mode', 'active_cap')
    return any(before[key] != after[key] for key in keys)


def controller_paths(rows, out):
    hosted()
    import numpy as np
    from owned_grid import canonical_leaf, configure
    from selective_journal import Journal
    from full_system_controller_worker import KEYS
    registered = profiles()
    need([p['id'] for p in registered] == [BASELINE, NO_EXTRA, CANDIDATE], 'EXACT_THREE_PROFILES')
    raw = Path('/variant/sentinel/controller/champion_frozen.py').read_bytes()
    parent_sha = hashlib.sha256(raw).hexdigest()
    leafpath = '/variant/sentinel/controller/owned_impairment.py'
    leaf_sha = hashlib.sha256(Path(leafpath).read_bytes()).hexdigest()
    need(leaf_sha == '699286647502b99ea9a3bf7c02b3bd839a43523d613ed3c62ad71271c2de092b',
         'FROZEN_OWNED_SOURCE')
    vector, independent_states = independent_targets(rows, registered)
    need(vector.shape == (3, len(rows)) and len(independent_states) == len(rows), 'INDEPENDENT_TRACE_SHAPE')
    journal = Journal(out / 'controller-checkpoints.jsonl.gz')
    trace = Journal(out / 'watch-trace.jsonl.gz')
    paths, restores, transition_restores = [], 0, 0
    try:
        for index, profile in enumerate(registered):
            module = parent_module(raw, profile, parent_sha)
            native, candidate = module.Native(), module.CandidateA()
            leaf = canonical_leaf(leafpath, leaf_sha, name='_private_sharadar_owned_grid_rw1_' + str(index))
            configure(leaf, profile['owned'])
            state = leaf.fresh()
            watch = RecoveryWatch() if index == 2 else None
            effective = previous = 1.
            values = []
            for i, row in enumerate(rows):
                ob, leadership = row['evidence']['observation'], row['evidence']['recent_leadership']
                n, _, _ = native.step(tuple(ob[k] for k in KEYS))
                desired, _ = candidate.step(n, effective, ob['shadow_drawdown'], leadership['recent_r20'],
                                             leadership['recent_r40'], ob['spy_r20'], ob['shadow_r20'])
                effective, previous = previous, n
                state, owned_evidence = leaf.step(observation=SimpleNamespace(**ob), base_target=desired, state=state)
                target = owned_evidence['target']
                transition = False
                if watch is not None:
                    before = watch.snapshot()
                    stress = any(getattr(native, key) for key in ('ordinary', 'base_fast', 'fast', 'slow'))
                    need(ob.get('session', row['session']) == row['session'], 'OBSERVATION_SESSION_ALIGNMENT')
                    audit = watch.step(session=row['session'], observation={**ob, 'session': row['session']}, native_stress=stress)
                    after = watch.snapshot()
                    need(after == audit['state'] == independent_states[i], 'EVERY_INDEPENDENT_WATCH_STATE')
                    target = min(target, audit['ceiling'])
                    transition = state_transition(before, after)
                    trace.write(dict(session=row['session'], state=after, audit=audit,
                                     no_extra_target=float(vector[1, i]), target=float(target)))
                need(target == float(vector[index, i]), 'EVERY_INDEPENDENT_CONTROLLER_TARGET')
                if index == 0:
                    need(target == row['decision']['target_core_exposure'], 'EXACT_ORIGINAL_BASELINE_TARGET')
                values.append(target)
                month = i == len(rows) - 1 or row['session'][:7] != rows[i + 1]['session'][:7]
                if month or transition:
                    checkpoint = dict(profile=profile['id'], session=row['session'], native=native.snapshot(),
                                      candidate=candidate.snapshot(), owned=state, effective=effective, previous=previous,
                                      target_prefix_sha256=hashlib.sha256(np.asarray(values, dtype='<f8').tobytes()).hexdigest(),
                                      watch=None if watch is None else watch.snapshot(), watch_transition=transition,
                                      watch_trace=None if watch is None else trace.commitment())
                    journal.write(checkpoint)
                    material = json.loads(json.dumps(checkpoint, allow_nan=False))
                    native = module.Native.from_snapshot(material['native'])
                    candidate = module.CandidateA.from_snapshot(material['candidate'])
                    state = material['owned']
                    if watch is not None:
                        watch = RecoveryWatch.from_snapshot(material['watch'])
                        need(watch.snapshot() == independent_states[i], 'ACTUAL_WATCH_RESTORE_EQUIVALENCE')
                    restores += 1
                    transition_restores += int(transition)
            paths.append(values)
        journal.flush()
        trace.flush()
        proof = dict(profiles=registered, parent_source_sha256=parent_sha, owned_source_sha256=leaf_sha,
                     actual_canonical_steps=len(rows) * 3, independent_vector_exact=True,
                     every_watch_state_independently_equal=True, actual_serialized_restores=restores,
                     watch_transition_restores=transition_restores, journal=journal.commitment(),
                     watch_journal=trace.commitment(), baseline_full_formation_and_measured_targets_exact=True)
        write(out / 'controller-proof.json', proof)
    finally:
        journal.close()
        trace.close()
    return registered, np.asarray(paths), independent_states


def duration_record(series, peak, first, last, recovery):
    end = last if recovery is None else recovery
    return dict(peak=series[peak][0], first_underwater=series[first][0], last_underwater=series[last][0],
                recovery=None if recovery is None else series[recovery][0], censored=recovery is None,
                underwater_closes=last - first + 1, peak_to_end_sessions=end - peak,
                peak_to_end_calendar_days=(date.fromisoformat(series[end][0]) - date.fromisoformat(series[peak][0])).days)


def drawdown_stats(series):
    """Decimal worker calculation; exact products choose the worst episode."""
    peak = worst_peak = worst_trough = 0
    worst_nav = worst_high = D(series[0][1])
    underway = None
    episodes = []
    for i, (_, value) in enumerate(series):
        nav, high = D(value), D(series[peak][1])
        with localcontext() as ctx:
            ctx.prec = 80
            worse = nav * worst_high < worst_nav * high
        if worse:
            worst_peak, worst_trough, worst_nav, worst_high = peak, i, nav, high
        if nav >= high:
            if underway is not None:
                episodes.append(duration_record(series, peak, underway, i - 1, i))
                underway = None
            peak = i
        elif underway is None:
            underway = i
    if underway is not None:
        episodes.append(duration_record(series, peak, underway, len(series) - 1, None))
    recovery = next((i for i in range(worst_trough + 1, len(series))
                     if D(series[i][1]) >= D(series[worst_peak][1])), None) if worst_trough else 0
    end = len(series) - 1 if recovery is None else recovery
    longest = max(episodes, key=lambda e: e['underwater_closes'], default=None)
    return dict(maximum_drawdown_magnitude=str(1 - Q(series[worst_trough][1]) / Q(series[worst_peak][1])),
                peak=series[worst_peak][0], trough=series[worst_trough][0],
                recovery=None if recovery is None else series[recovery][0], censored=recovery is None,
                peak_to_trough_sessions=worst_trough - worst_peak, peak_to_end_sessions=end - worst_peak,
                peak_to_end_calendar_days=(date.fromisoformat(series[end][0]) - date.fromisoformat(series[worst_peak][0])).days,
                underwater_closes=sum(e['underwater_closes'] for e in episodes),
                longest_underwater=longest, underwater_episodes=episodes)


def independent_drawdown_stats(series):
    """Separately reconstructed rational drawdowns and maximal underwater runs."""
    values = [Q(value) for _, value in series]
    high = values[0]
    high_index = 0
    worst = Q(0)
    peak_index = trough_index = 0
    runs = []
    run_peak = None
    for i, value in enumerate(values):
        loss = 1 - value / high
        if loss > worst:
            worst, peak_index, trough_index = loss, high_index, i
        if value < high:
            if run_peak is None:
                run_peak = high_index
        else:
            if run_peak is not None:
                runs.append((run_peak, run_peak + 1, i - 1, i))
                run_peak = None
            high, high_index = value, i
    if run_peak is not None:
        runs.append((run_peak, run_peak + 1, len(values) - 1, None))
    episodes = []
    for p, first, last, recovered in runs:
        final = len(values) - 1 if recovered is None else recovered
        episodes.append(dict(peak=series[p][0], first_underwater=series[first][0], last_underwater=series[last][0],
                             recovery=None if recovered is None else series[recovered][0], censored=recovered is None,
                             underwater_closes=last - first + 1, peak_to_end_sessions=final - p,
                             peak_to_end_calendar_days=(date.fromisoformat(series[final][0]) - date.fromisoformat(series[p][0])).days))
    recovered = next((i for i in range(trough_index + 1, len(values)) if values[i] >= values[peak_index]), None) if worst else 0
    final = len(values) - 1 if recovered is None else recovered
    return dict(maximum_drawdown_magnitude=str(worst), peak=series[peak_index][0], trough=series[trough_index][0],
                recovery=None if recovered is None else series[recovered][0], censored=recovered is None,
                peak_to_trough_sessions=trough_index - peak_index, peak_to_end_sessions=final - peak_index,
                peak_to_end_calendar_days=(date.fromisoformat(series[final][0]) - date.fromisoformat(series[peak_index][0])).days,
                underwater_closes=sum(e['underwater_closes'] for e in episodes),
                longest_underwater=max(episodes, key=lambda e: e['underwater_closes'], default=None), underwater_episodes=episodes)


def report(series, daily):
    hosted()
    from full_system_controller_worker import metrics
    from p00_recovery_hold_worker import report as previous_report
    result = previous_report(series, daily)
    result['blocks'] = {name: metrics(series, start, end) for name, start, end in BLOCKS}
    result['drawdown'] = drawdown_stats(series)
    need(result['drawdown']['maximum_drawdown_magnitude'] == result['full']['maximum_drawdown_magnitude'], 'DRAWDOWN_METRIC_AGREEMENT')
    return result


def watch_scope(rows, paths, states):
    changed = []
    for i, row in enumerate(rows):
        base, actual, state = float(paths[1, i]), float(paths[2, i]), states[i]
        need(actual == min(base, .55 if state['active_cap'] else 1.) and actual <= base,
             'WATCH_REDUCTION_ONLY_AT_DECLARED_CEILING')
        if actual != base:
            changed.append(dict(session=row['session'], no_extra=base, recovery_watch=actual, state=state))
    return changed


def spans(states, predicate, initially_active=False):
    result, start = [], 0 if initially_active else None
    for i, state in enumerate(states):
        active = predicate(state)
        if active and start is None:
            start = i
        elif not active and start is not None:
            result.append((start, i, True))
            start = None
    if start is not None:
        result.append((start, len(states) - 1, False))
    return result


def episode_reports(rows, states, paths, all_series, period, formation_rows=(), formation_states=()):
    # A recovery can start and clear on one close. Include it even though the
    # committed post-close mode never reads WATCH. Formation-started episodes
    # retain their true signal date; their account window begins at the common
    # funded measurement anchor, never a fabricated formation NAV.
    complete_rows = list(formation_rows) + rows
    complete_states = list(formation_states) + states
    offset = len(formation_rows)
    intervals, active_start, previous_mode = [], None, 'NORMAL'
    for i, state in enumerate(complete_states):
        if previous_mode == 'PENDING' and state['mode'] != 'PENDING':
            need(active_start is None, 'WATCH_EPISODE_START_UNIQUE')
            active_start = i
        if active_start is not None and state['mode'] == 'NORMAL':
            intervals.append((active_start, i, True))
            active_start = None
        previous_mode = state['mode']
    if active_start is not None:
        intervals.append((active_start, len(complete_states) - 1, False))
    cap_intervals = spans(complete_states, lambda s: s['active_cap'])
    result = {}
    for kind, selected in (('watch', intervals), ('cap', cap_intervals)):
        reports = []
        for first, last, complete in selected:
            measured_first, measured_last = max(0, first - offset), last - offset
            outcomes = ({pid: period(series, measured_first, measured_last) for pid, series in all_series.items()}
                        if measured_last >= 0 else {pid: dict(status='FORMATION_ONLY_NO_FUNDED_ACCOUNT') for pid in all_series})
            change = None
            if 'multiple' in outcomes[CANDIDATE] and 'multiple' in outcomes[NO_EXTRA]:
                change = dict(relative_wealth_change=str(Q(outcomes[CANDIDATE]['multiple']) / Q(outcomes[NO_EXTRA]['multiple']) - 1),
                              return_fraction_difference=str(Q(outcomes[CANDIDATE]['total_return']) - Q(outcomes[NO_EXTRA]['total_return'])))
            reports.append(dict(signal=complete_rows[first]['session'],
                                first_effective_session=None if first + 1 == len(complete_rows) else complete_rows[first + 1]['session'],
                                end=complete_rows[last]['session'], complete=complete, censored=not complete,
                                started_during_formation=first < offset, measurement_overlap=measured_last >= 0,
                                account_anchor=None if measured_last < 0 else rows[measured_first]['session'],
                                instantaneous=first == last, cap_signal_closes=sum(s['active_cap'] for s in complete_states[first:last + 1]),
                                changed_target_closes=sum(bool(paths[1, i] != paths[2, i]) for i in range(max(0, first - offset), max(0, last - offset + 1))),
                                incremental_vs_no_extra=change, profiles=outcomes))
        result[kind] = reports
    return result


def account_gap_canary(rows, events):
    """Actual recorded gap: a current-close cut cannot rewrite its held overnight loss."""
    hosted()
    from full_system_controller_worker import actual_account, independently_check
    for i in range(1, len(rows)):
        prior, row = rows[i - 1]['economics'], rows[i]
        if prior['held_allocation'] is None or D(prior['held_allocation']) <= 0:
            continue
        old = D(prior['held_allocation'])
        e = row['economics']
        gap = old * D(e['parent_core_open_equity']) / D(prior['parent_core_close_equity']) + (1 - old) * D(e['bil_open_adjusted']) / D(e['bil_previous_close_adjusted_current_publication'])
        if gap >= 1:
            continue
        cut, full = actual_account(prior, row, 0., events), actual_account(prior, row, 1., events)
        independently_check(prior, row, cut, events)
        independently_check(prior, row, full, events)
        need({k: v for k, v in cut.items() if k != 'pending_allocation'} ==
             {k: v for k, v in full.items() if k != 'pending_allocation'}, 'SAME_CLOSE_CANNOT_ERASE_HELD_GAP')
        need(D(cut['pending_allocation']) == 0 and D(full['pending_allocation']) == 1, 'GAP_NEXT_OPEN_TARGETS_DISTINCT')
        return dict(session=row['session'], input='ADMITTED_ORIGINAL_RECORDED_GAP', held_overnight=str(old),
                    overnight_factor=str(gap), current_nav=cut['strategy_nav'], current_factors_equal=True,
                    distinct_targets_only_effective_next_open=True, canonical_account_calls=2,
                    independent_factor_checks=2)
    need(False, 'RECORDED_EXPOSED_OVERNIGHT_GAP_REQUIRED')


def review_gap_canary(rows, events, receipt):
    """Independent rational reconstruction of the recorded gap and current NAV."""
    hosted()
    from full_system_controller_review import independent_factor, value_step
    found = None
    for i in range(1, len(rows)):
        previous, current = rows[i - 1]['economics'], rows[i]['economics']
        if previous['held_allocation'] is None or Q(previous['held_allocation']) <= 0:
            continue
        allocation = Q(previous['held_allocation'])
        gap = allocation * Q(current['parent_core_open_equity']) / Q(previous['parent_core_close_equity']) + (1 - allocation) * Q(current['bil_open_adjusted']) / Q(current['bil_previous_close_adjusted_current_publication'])
        if gap < 1:
            found = i, allocation, gap
            break
    need(found is not None, 'INDEPENDENT_EXPOSED_GAP_EXISTS')
    i, allocation, gap = found
    previous, current = rows[i - 1]['economics'], rows[i]['economics']
    factor = independent_factor(previous, rows[i], events)
    need(receipt['session'] == rows[i]['session'] and Q(receipt['held_overnight']) == allocation
         and abs(Q(receipt['overnight_factor']) - gap) < Q('1e-25') and gap < 1
         and receipt['current_nav'] == value_step(previous['strategy_nav'], str(factor['net'])) == current['strategy_nav']
         and receipt['current_factors_equal'] is True and receipt['distinct_targets_only_effective_next_open'] is True
         and receipt['canonical_account_calls'] == receipt['independent_factor_checks'] == 2
         and receipt['input'] == 'ADMITTED_ORIGINAL_RECORDED_GAP', 'INDEPENDENT_RECORDED_GAP_AND_NEXT_OPEN_TIMING')


def check_account_fields(account, original, prior):
    # These are the complete account-owned scalar fields. All other fields
    # remain the admitted dated Core/BIL/price-domain evidence on every path.
    changing = {'gross_factor', 'net_factor', 'held_allocation', 'pending_allocation',
                'previous_strategy_nav', 'strategy_cumulative_return', 'strategy_nav',
                'transaction_cost_factor', 'turnover'}
    need(set(account) == set(original), 'COMPLETE_ACCOUNT_FIELD_SCHEMA')
    need({k: v for k, v in account.items() if k not in changing} ==
         {k: v for k, v in original.items() if k not in changing}, 'ALL_DATED_CORE_BIL_AND_PRICE_FIELDS_EXACT')
    need(account['previous_strategy_nav'] == (original['previous_strategy_nav'] if prior is None else prior['strategy_nav']),
         'INDEPENDENT_PREVIOUS_FUNDED_NAV')
    need(D(account['strategy_cumulative_return']) == D(account['strategy_nav']) / D(account['starting_cash']) - 1,
         'INDEPENDENT_FUNDED_CUMULATIVE_RETURN')


def run(root, out):
    hosted()
    from selective_journal import Journal
    import full_system_controller_worker as existing
    started = time.monotonic()
    cp, formation, rows = load(root)
    out.mkdir(exist_ok=False)
    write(out / 'constructor-canary.json', canary(Path('/variant/sentinel/controller/champion_frozen.py').read_bytes()))
    registered, allpaths, allstates = controller_paths(formation + rows, out)
    paths, states = allpaths[:, 126:], allstates[126:]
    reference_controls(paths)
    old_scope = changed_scope(rows, paths[:2])
    changes = watch_scope(rows, paths, states)
    need((allpaths[0, :126] == allpaths[1, :126]).all(), 'ORIGINAL_FORMATION_NO_HOLD_TARGETS_EXACT')
    write(out / 'original-no-hold-scope.json', old_scope)
    write(out / 'watch-changed-targets.json', changes)
    events = cp['run']['state']['ledger']['events']
    write(out / 'account-gap-canary.json', account_gap_canary(rows, events))
    reports, commitments, all_series = {}, {}, {}
    for index, profile in enumerate(registered):
        pid = profile['id']
        journal = Journal(out / (pid + '.jsonl.gz'))
        prior, daily, series, checkpoints = None, [], [], []
        try:
            for i, row in enumerate(rows):
                target = float(paths[index, i])
                actual = deepcopy(row['economics']) if i == 0 else existing.actual_account(prior, row, target, events)
                if i == 0:
                    if D(actual['pending_allocation']) != D(str(target)):
                        actual['pending_allocation'] = str(target)
                else:
                    existing.independently_check(prior, row, actual, events)
                need(D(actual['strategy_nav']).is_finite() and D(actual['strategy_nav']) > 0, 'POSITIVE_UNLEVERED_ACCOUNT')
                need(D(actual['pending_allocation']) in (D(0), D('.55'), D(1)), 'LONG_ONLY_EXPOSURE')
                if index == 0:
                    need(actual == row['economics'], 'EXACT_ALL_BASELINE_ACCOUNT_FIELDS')
                check_account_fields(actual, row['economics'], prior)
                item = dict(session=row['session'], close_target=target, account=actual)
                journal.write(item)
                daily.append(item)
                series.append((row['session'], actual['strategy_nav']))
                prior = actual
                if i == len(rows) - 1 or row['session'][:7] != rows[i + 1]['session'][:7]:
                    prior = json.loads(json.dumps(actual, allow_nan=False))
                    need(prior == actual, 'MONTHLY_ACCOUNT_CONTINUATION')
                    checkpoints.append(dict(completed=i + 1, session=row['session'], account=prior))
            journal.flush()
            commitments[pid] = journal.commitment()
            write(out / (pid + '-checkpoints.json'), checkpoints)
            write(out / (pid + '-monthly.json'), monthly(series))
            reports[pid] = report(series, daily)
            all_series[pid] = series
            print(json.dumps(dict(profile=pid, measured_closes=len(rows), status='ACCOUNT_COMPLETE_REVIEW_REQUIRED')), flush=True)
        finally:
            journal.close()
    reference_controls(paths, commitments)
    from full_system_controller_worker import metrics
    def period(series, first, last):
        if last == first:
            return dict(anchor=series[first][0], end=series[last][0], measured_closes=0, status='NO_SUBSEQUENT_CLOSE')
        return metrics(series, rows[first + 1]['session'], rows[last]['session'])
    original = [dict(anchor=rows[first]['session'], end=rows[last]['session'], complete=complete,
                     profiles={pid: period(series, first, last) for pid, series in all_series.items()})
                for first, last, complete in windows(rows)]
    episodes = episode_reports(rows, states, paths, all_series, period, formation, allstates[:126])
    write(out / 'summary.json', dict(status='P00_RECOVERY_WATCH_REVIEW_REQUIRED', reports=reports, profiles=registered,
          journal_commitments=commitments, baseline_targets_and_accounts_exact=True, prior_no_extra_path_exact=True,
          original_no_hold_changed_closes=len(old_scope), watch_changed_close_targets=len(changes),
          watch_cap_signal_closes=sum(s['active_cap'] for s in states), watch_episodes=episodes,
          original_defensive_windows=original, canonical_core_transitions=0, native_rules_unchanged=True,
          original_core_backtests_resumed=False, same_core_and_source_epoch=True, known_history_not_unseen=True,
          no_postselection_or_parameter_grid=True, production_contacted=False, elapsed_seconds=time.monotonic() - started))


def review(root, evidence, out):
    hosted()
    import numpy as np
    from selective_journal import verify_prefixes
    from full_system_controller_review import independent_factor, value_step, check_factor
    from owned_grid import metric as independent_metric
    started = time.monotonic()
    cp, formation, rows = load(root)
    complete_rows = formation + rows
    events = cp['run']['state']['ledger']['events']
    summary = json.loads((evidence / 'summary.json').read_bytes())
    proof = json.loads((evidence / 'controller-proof.json').read_bytes())
    need(summary['status'] == 'P00_RECOVERY_WATCH_REVIEW_REQUIRED' and summary['profiles'] == profiles()
         and proof['profiles'] == profiles() and summary['canonical_core_transitions'] == 0, 'INDEPENDENT_REGISTERED_EXPERIMENT')
    need(json.loads((evidence / 'constructor-canary.json').read_bytes()) ==
         canary(Path('/variant/sentinel/controller/champion_frozen.py').read_bytes()), 'REVIEWER_REPEATED_HOSTED_CANONICAL_FALSIFIERS')
    review_gap_canary(rows, events, json.loads((evidence / 'account-gap-canary.json').read_bytes()))
    vector, allstates = independent_targets(complete_rows, profiles())
    paths, states = vector[:, 126:], allstates[126:]
    reference_controls(paths, summary['journal_commitments'])
    scope = changed_scope(rows, paths[:2])
    changes = watch_scope(rows, paths, states)
    need(json.loads((evidence / 'original-no-hold-scope.json').read_bytes()) == scope, 'INDEPENDENT_ORIGINAL_43_17_HOLD_SCOPE')
    need(json.loads((evidence / 'watch-changed-targets.json').read_bytes()) == changes, 'INDEPENDENT_EVERY_WATCH_CHANGE')
    for i, row in enumerate(complete_rows):
        need(vector[0, i] == row['decision']['target_core_exposure'], 'INDEPENDENT_BASELINE_TARGET')
    trace = read_journal(evidence / 'watch-trace.jsonl.gz')
    verify_prefixes(evidence / 'watch-trace.jsonl.gz', [proof['watch_journal']])
    need(len(trace) == len(complete_rows), 'COMPLETE_FORMATION_AND_MEASURED_WATCH_TRACE')
    for i, (item, row) in enumerate(zip(trace, complete_rows)):
        need(item['session'] == row['session'] and item['state'] == item['audit']['state'] == allstates[i]
             and item['target'] == vector[2, i] and item['no_extra_target'] == vector[1, i], 'INDEPENDENT_EVERY_WATCH_TRACE_RECORD')
    verify_prefixes(evidence / 'controller-checkpoints.jsonl.gz', [proof['journal']])
    checkpoints = read_journal(evidence / 'controller-checkpoints.jsonl.gz')
    profile_ids = [p['id'] for p in profiles()]
    positions = {r['session']: i for i, r in enumerate(complete_rows)}
    observed_cp = set()
    trace_specs = []
    for item in checkpoints:
        index, end = profile_ids.index(item['profile']), positions[item['session']] + 1
        key = (index, end - 1)
        need(key not in observed_cp, 'UNIQUE_CONTROLLER_CHECKPOINT')
        observed_cp.add(key)
        need(hashlib.sha256(np.asarray(vector[index, :end], dtype='<f8').tobytes()).hexdigest() == item['target_prefix_sha256'],
             'EVERY_CONTROLLER_CONTINUATION_PREFIX')
        if index == 2:
            need(item['watch'] == allstates[end - 1], 'INDEPENDENT_WATCH_CONTINUATION_STATE')
            trace_specs.append(item['watch_trace'])
        else:
            need(item['watch'] is None and item['watch_trace'] is None, 'CONTROL_HAS_NO_WATCH')
    required_cp = set()
    for index in range(3):
        for i, row in enumerate(complete_rows):
            transition = index == 2 and (state_transition(allstates[i - 1], allstates[i]) if i > 0
                                          else allstates[i]['mode'] != 'NORMAL' or allstates[i]['active_cap'])
            month = i == len(complete_rows) - 1 or row['session'][:7] != complete_rows[i + 1]['session'][:7]
            if transition or month:
                required_cp.add((index, i))
    need(observed_cp == required_cp, 'EVERY_MONTH_AND_WATCH_TRANSITION_RESTORED')
    verify_prefixes(evidence / 'watch-trace.jsonl.gz', trace_specs)
    observed_reports, observed_series = {}, {}
    for index, profile in enumerate(profiles()):
        pid = profile['id']
        verify_prefixes(evidence / (pid + '.jsonl.gz'), [summary['journal_commitments'][pid]])
        actual = read_journal(evidence / (pid + '.jsonl.gz'))
        need(len(actual) == len(rows), 'COMPLETE_FUNDED_PATH')
        prior, nav, series, account_cps = None, rows[0]['economics']['strategy_nav'], [], []
        for i, (item, row) in enumerate(zip(actual, rows)):
            e = item['account']
            need(item['session'] == row['session'] and item['close_target'] == paths[index, i]
                 and D(e['pending_allocation']) == D(str(item['close_target'])), 'NEXT_OPEN_TARGET_ALIGNMENT')
            if i:
                need(D(e['held_allocation']) == D(prior['pending_allocation']), 'NO_CLOSE_LOOKAHEAD')
                expected = independent_factor(prior, row, events)
                check_factor(dict(gross=e['gross_factor'], net=e['net_factor'], turnover=e['turnover'], cost=e['transaction_cost_factor']), expected)
                nav = value_step(nav, e['net_factor'])
            else:
                expected = deepcopy(row['economics'])
                expected['pending_allocation'] = e['pending_allocation']
                need(e == expected and D(e['strategy_nav']) == D('50000'), 'ORIGINAL_MEASUREMENT_ANCHOR')
            need(e['strategy_nav'] == nav, 'INDEPENDENT_EVERY_FUNDED_NAV')
            if index == 0:
                need(e == row['economics'], 'INDEPENDENT_ALL_BASELINE_FIELDS')
            check_account_fields(e, row['economics'], prior)
            series.append((row['session'], nav))
            prior = e
            if i == len(rows) - 1 or row['session'][:7] != rows[i + 1]['session'][:7]:
                account_cps.append(dict(completed=i + 1, session=row['session'], account=e))
        need(json.loads((evidence / (pid + '-checkpoints.json')).read_bytes()) == account_cps, 'ALL_MONTHLY_FUNDED_CONTINUATIONS')
        months = json.loads((evidence / (pid + '-monthly.json')).read_bytes())
        ends = [(d, n) for j, (d, n) in enumerate(series) if j + 1 == len(series) or d[:7] != series[j + 1][0][:7]]
        need(len(months) == len(ends) == 103, 'ALL_103_MONTHLY_REPORTS')
        previous_nav = Q(series[0][1])
        for item, (day, value) in zip(months, ends):
            need((item['month'], item['through'], item['nav']) == (day[:7], day, value)
                 and abs(Q(item['return_fraction']) - (Q(value) / previous_nav - 1)) < Q('1e-25'), 'INDEPENDENT_MONTHLY_RETURN')
            previous_nav = Q(value)
        def independent_period(start, end):
            chosen = [(d, n) for d, n in series if start <= d <= end]
            anchor = next(((d, n) for d, n in reversed(series) if d < start), series[0])
            return dict(independent_metric([v for v in chosen if v[0] > anchor[0]], anchor), measured_closes=len(chosen))
        observed_reports[pid] = dict(full=independent_period('2018-01-02', '2026-07-31'),
            annual={str(y): independent_period(f'{y}-01-01', max(d for d, _ in series if d[:4] == str(y))) for y in range(2018, 2027)},
            blocks={name: independent_period(start, end) for name, start, end in BLOCKS},
            drawdown=independent_drawdown_stats(series), turnover=str(sum((D(v['account']['turnover']) for v in actual[1:]), D(0))),
            allocation_changes=sum(v['account']['held_allocation'] != actual[j - 1]['account']['held_allocation'] for j, v in enumerate(actual) if j > 1))
        need(summary['reports'][pid] == observed_reports[pid], 'ALL_REPORTED_METRICS_AND_DRAWDOWN_DURATIONS')
        observed_series[pid] = series
    def checked_period(series, first, last):
        if first == last:
            return dict(anchor=series[first][0], end=series[last][0], measured_closes=0, status='NO_SUBSEQUENT_CLOSE')
        return dict(independent_metric(series[first + 1:last + 1], series[first]), measured_closes=last - first)
    original = [dict(anchor=rows[first]['session'], end=rows[last]['session'], complete=complete,
                     profiles={pid: checked_period(series, first, last) for pid, series in observed_series.items()})
                for first, last, complete in windows(rows)]
    checked_episodes = episode_reports(rows, states, paths, observed_series, checked_period,
                                       formation, allstates[:126])
    need(summary['original_defensive_windows'] == original and summary['watch_episodes'] == checked_episodes,
         'INDEPENDENT_EVERY_DEFENSIVE_WATCH_AND_CAP_EPISODE')
    need(summary['original_no_hold_changed_closes'] == 43 and summary['watch_changed_close_targets'] == len(changes)
         and summary['watch_cap_signal_closes'] == sum(s['active_cap'] for s in states), 'INDEPENDENT_EVENT_COUNTS')
    out.mkdir(exist_ok=False)
    write(out / 'independent-review.json', dict(status='P00_RECOVERY_WATCH_INDEPENDENT_REVIEW_PASSED',
          verified_profiles=3, measured_closes_per_profile=len(rows), monthly_reports_per_profile=103,
          every_target_watch_state_factor_nav_and_baseline_field_checked=True, prior_control_journals_exact=True,
          controller_checkpoints=len(checkpoints), watch_trace_rows=len(trace), reports=observed_reports,
          original_no_hold_changed_closes=len(scope), watch_changed_close_targets=len(changes),
          original_defensive_windows=original, watch_episodes=checked_episodes, native_rules_unchanged=True,
          elapsed_seconds=time.monotonic() - started, production_contacted=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--mode', choices=('worker', 'review'), required=True)
    args = parser.parse_args()
    review(args.root, args.evidence, args.output) if args.mode == 'review' else run(args.root, args.output)

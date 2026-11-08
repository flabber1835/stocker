"""Hosted paired controller/account experiment over the admitted P10 Core path."""
import argparse
from copy import deepcopy
from decimal import Decimal as D
import gzip
import hashlib
import json
from pathlib import Path
import time

from p10_reentry_policy import BASELINE, CANDIDATE, canary, hosted, need, profiles, parent_module, targets


def write(path, value):
    need(not path.exists(), 'OUTPUT_COLLISION')
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False) + '\n')


def load(root):
    hosted()
    from research.pooled_vacancy_funding.journal import read_checkpoint
    cp = read_checkpoint(root / 'checkpoint.json.gz')
    formation = [json.loads(v) for v in (root / 'formation.jsonl').read_bytes().splitlines()]
    rows = [json.loads(v) for v in (root / 'daily.jsonl').read_bytes().splitlines()]
    need(len(formation) == 126 and len(rows) == cp['completed'] == 2156
         and rows[0]['session'] == '2018-01-02'
         and rows[-1]['session'] == cp['source_cursor'] == '2026-07-31', 'COMPLETE_OWN_AXIS')
    # P10 has exact stored observation inputs and no bounded-sensor certificates.
    # Any later input epoch with such certificates needs separate qualification.
    need(not any('uncertainty' in p.name.lower() or 'certificate' in p.name.lower()
                 for p in root.parent.iterdir()), 'UNCERTAINTY_SCOPE_REQUIRES_SEPARATE_PROOF')
    for row in formation + rows:
        need(set(row['evidence']['recent_leadership']) == {'recent_r20', 'recent_r40'},
             'EXACT_ORIGINAL_LEADERSHIP_INPUT_SCHEMA')
    return cp, formation, rows


def report(series, daily):
    from full_system_controller_worker import metrics
    return dict(full=metrics(series, '2018-01-02', '2026-07-31'),
                annual={str(y): metrics(series, f'{y}-01-01', max(d for d, _ in series if d[:4] == str(y)))
                        for y in range(2018, 2027)},
                turnover=str(sum((D(v['account']['turnover']) for v in daily[1:]), D(0))),
                allocation_changes=sum(v['account']['held_allocation'] != daily[i - 1]['account']['held_allocation']
                                       for i, v in enumerate(daily) if i > 1))


def monthly(series):
    prior = D(series[0][1])
    reports = []
    for i, (day, nav) in enumerate(series):
        if i == len(series) - 1 or day[:7] != series[i + 1][0][:7]:
            reports.append(dict(month=day[:7], through=day, nav=nav, return_fraction=str(D(nav) / prior - 1)))
            prior = D(nav)
    need(len(reports) == 103, 'ALL_MONTHLY_REPORTS')
    return reports


def run(root, out):
    hosted()
    from selective_journal import Journal
    import full_system_controller_worker as existing
    started = time.monotonic()
    cp, formation, rows = load(root)
    out.mkdir(exist_ok=False)
    raw = Path('/variant/sentinel/controller/champion_frozen.py').read_bytes()
    write(out / 'constructor-canary.json', canary(raw))
    existing.profiles = profiles
    existing.parent_module = parent_module
    existing.independent_targets = targets
    registered, allpaths = existing.controller_paths(formation + rows, out)
    paths = allpaths[:, 126:]
    need(registered == profiles(), 'TWO_CONTROLLER_PATHS')
    controller_seconds = time.monotonic() - started
    events = cp['run']['state']['ledger']['events']
    reports, commitments = {}, {}
    for index, profile in enumerate(registered):
        pid = profile['id']
        journal = Journal(out / (pid + '.jsonl.gz'))
        prior, daily, series, checkpoints = None, [], [], []
        try:
            for i, row in enumerate(rows):
                target = float(paths[index, i])
                actual = deepcopy(row['economics']) if i == 0 else existing.actual_account(prior, row, target, events)
                if i == 0:
                    actual['pending_allocation'] = str(target) if D(actual['pending_allocation']) != D(str(target)) else actual['pending_allocation']
                else:
                    existing.independently_check(prior, row, actual, events)
                need(D(actual['strategy_nav']).is_finite() and D(actual['strategy_nav']) > 0,
                     'POSITIVE_UNLEVERED_ACCOUNT')
                need(D(actual['pending_allocation']) in (D(0), D('.55'), D(1)), 'LONG_ONLY_EXPOSURE')
                if index == 0:
                    need(actual == row['economics'], 'EXACT_ALL_BASELINE_ACCOUNT_FIELDS')
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
            print(json.dumps(dict(profile=pid, measured_closes=len(rows), status='ACCOUNT_COMPLETE_REVIEW_REQUIRED')), flush=True)
        finally:
            journal.close()
    write(out / 'summary.json', dict(status='P10_REENTRY_REVIEW_REQUIRED', reports=reports,
          profiles=registered, journal_commitments=commitments, baseline_targets_and_accounts_exact=True,
          changed_close_targets=int((paths[0] != paths[1]).sum()), canonical_core_transitions=0,
          timing=dict(controller_seconds=controller_seconds,
                      controller_and_account_seconds=time.monotonic() - started),
          same_core_and_source_epoch=True, known_history_not_unseen=True, production_contacted=False))


def review(root, evidence, out):
    hosted()
    from selective_journal import verify_prefixes
    from full_system_controller_review import independent_factor, value_step, check_factor
    from owned_grid import metric as independent_metric
    from fractions import Fraction as Q
    started = time.monotonic()
    cp, formation, rows = load(root)
    events = cp['run']['state']['ledger']['events']
    summary = json.loads((evidence / 'summary.json').read_bytes())
    proof = json.loads((evidence / 'controller-proof.json').read_bytes())
    need(summary['status'] == 'P10_REENTRY_REVIEW_REQUIRED' and summary['profiles'] == profiles()
         and proof['profiles'] == profiles() and summary['canonical_core_transitions'] == 0,
         'INDEPENDENT_REGISTERED_EXPERIMENT')
    vector = targets(formation + rows, profiles())
    for i, row in enumerate(formation + rows):
        need(vector[0, i] == row['decision']['target_core_exposure'], 'INDEPENDENT_BASELINE_TARGET')
    verify_prefixes(evidence / 'controller-checkpoints.jsonl.gz', [proof['journal']])
    with gzip.open(evidence / 'controller-checkpoints.jsonl.gz', 'rt') as stream:
        for line in stream:
            item = json.loads(line)
            index = [v['id'] for v in profiles()].index(item['profile'])
            end = next(i for i, r in enumerate(formation + rows) if r['session'] == item['session']) + 1
            need(hashlib.sha256(vector[index, :end].astype('<f8').tobytes()).hexdigest()
                 == item['target_prefix_sha256'], 'EVERY_CONTROLLER_CONTINUATION_PREFIX')
    observed_reports = {}
    for index, profile in enumerate(profiles()):
        pid = profile['id']
        verify_prefixes(evidence / (pid + '.jsonl.gz'), [summary['journal_commitments'][pid]])
        with gzip.open(evidence / (pid + '.jsonl.gz'), 'rt') as stream:
            actual = [json.loads(line) for line in stream]
        need(len(actual) == len(rows), 'COMPLETE_FUNDED_PATH')
        prior, nav, series, checkpoints = None, rows[0]['economics']['strategy_nav'], [], []
        for i, (item, row) in enumerate(zip(actual, rows)):
            e = item['account']
            need(item['session'] == row['session'] and item['close_target'] == vector[index, i + 126]
                 and D(e['pending_allocation']) == D(str(item['close_target'])), 'NEXT_OPEN_TARGET_ALIGNMENT')
            if i:
                need(D(e['held_allocation']) == D(prior['pending_allocation']), 'NO_CLOSE_LOOKAHEAD')
                expected = independent_factor(prior, row, events)
                check_factor(dict(gross=e['gross_factor'], net=e['net_factor'],
                                  turnover=e['turnover'], cost=e['transaction_cost_factor']), expected)
                nav = value_step(nav, e['net_factor'])
            else:
                expected = deepcopy(row['economics'])
                expected['pending_allocation'] = e['pending_allocation']
                need(e == expected and D(e['strategy_nav']) == D('50000'), 'ORIGINAL_MEASUREMENT_ANCHOR')
            need(e['strategy_nav'] == nav, 'INDEPENDENT_EVERY_FUNDED_NAV')
            if index == 0:
                need(e == row['economics'], 'INDEPENDENT_ALL_BASELINE_FIELDS')
            series.append((row['session'], nav))
            prior = e
            if i == len(rows) - 1 or row['session'][:7] != rows[i + 1]['session'][:7]:
                checkpoints.append(dict(completed=i + 1, session=row['session'], account=e))
        need(json.loads((evidence / (pid + '-checkpoints.json')).read_bytes()) == checkpoints,
             'ALL_MONTHLY_FUNDED_CONTINUATIONS')
        months = json.loads((evidence / (pid + '-monthly.json')).read_bytes())
        ends = [(d, n) for j, (d, n) in enumerate(series)
                if j + 1 == len(series) or d[:7] != series[j + 1][0][:7]]
        need(len(months) == len(ends) == 103, 'ALL_103_MONTHLY_REPORTS')
        previous_nav = Q(series[0][1])
        for item, (day, value) in zip(months, ends):
            need((item['month'], item['through'], item['nav']) == (day[:7], day, value)
                 and abs(Q(item['return_fraction']) - (Q(value) / previous_nav - 1)) < Q('1e-25'),
                 'INDEPENDENT_MONTHLY_RETURN')
            previous_nav = Q(value)
        def independent_period(start, end):
            chosen = [(d, n) for d, n in series if start <= d <= end]
            anchor = next(((d, n) for d, n in reversed(series) if d < start), series[0])
            expected = independent_metric([v for v in chosen if v[0] > anchor[0]], anchor)
            return dict(expected, measured_closes=len(chosen))
        observed_reports[pid] = dict(full=independent_period('2018-01-02', '2026-07-31'),
            annual={str(y): independent_period(f'{y}-01-01', max(d for d, _ in series if d[:4] == str(y)))
                    for y in range(2018, 2027)},
            turnover=str(sum((D(v['account']['turnover']) for v in actual[1:]), D(0))),
            allocation_changes=sum(v['account']['held_allocation'] != actual[j - 1]['account']['held_allocation']
                                   for j, v in enumerate(actual) if j > 1))
        need(summary['reports'][pid] == observed_reports[pid], 'ALL_REPORTED_METRICS')
    out.mkdir(exist_ok=False)
    write(out / 'independent-review.json', dict(status='P10_REENTRY_INDEPENDENT_REVIEW_PASSED',
          verified_profiles=2, measured_closes_per_profile=len(rows), monthly_reports_per_profile=103,
          every_target_factor_nav_and_baseline_field_checked=True, reports=observed_reports,
          elapsed_seconds=time.monotonic() - started, production_contacted=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--evidence', type=Path)
    p.add_argument('--mode', choices=('worker', 'review'), required=True)
    a = p.parse_args()
    review(a.root, a.evidence, a.output) if a.mode == 'review' else run(a.root, a.output)

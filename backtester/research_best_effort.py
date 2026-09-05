#!/usr/bin/env python3
"""Explicitly uncertified Champion replay and assumption sensitivity scenarios."""
from __future__ import annotations
import argparse
import atexit
from collections import Counter
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATUS = 'UNCERTIFIED_BEST_EFFORT'
SCENARIOS = {
    'baseline': {'terminal_recovery': 1.0, 'include_unknown': False},
    'terminal_50': {'terminal_recovery': 0.5, 'include_unknown': False},
    'terminal_0': {'terminal_recovery': 0.0, 'include_unknown': False},
    'unknown_inclusion': {'terminal_recovery': 1.0, 'include_unknown': True},
}
LIMITATIONS = [
    'The canonical corpus has unresolved security classifications and terminal terms.',
    'Terminal recovery fractions are assumptions; sensitivity results are not error bounds.',
    'Missing ordinary leadership closes receive a logged zero return; held-price gaps carry prior marks.',
    'Unknown-inclusion stress may admit non-common instruments and does not establish their classification.',
    'Full exact-Champion dynamic causality and intraday execution timing remain uncertified.',
]


def positive(value):
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (ValueError, TypeError):
        return False


def terminal_claim(quantity, prior_raw, split_ratio, recovery):
    if not all(positive(v) for v in (quantity, prior_raw, split_ratio)):
        raise ValueError('terminal assumption requires a real positive prior mark, quantity, and split ratio')
    if not math.isfinite(float(recovery)) or not 0 <= float(recovery) <= 1:
        raise ValueError('terminal recovery must be in [0,1]')
    return float(quantity) * float(prior_raw) / float(split_ratio) * float(recovery)


class Audit:
    def __init__(self, output, scenario):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.scenario = scenario
        self.config = dict(SCENARIOS[scenario])
        self.counts = Counter()
        self.affected = Counter()
        self.haircut_value = 0.0
        self.handle = gzip.open(self.output / 'assumptions.jsonl.gz', 'wt', encoding='utf-8', compresslevel=1)
        atexit.register(self.close)

    def event(self, kind, session, security_id='', **detail):
        self.counts[kind] += 1
        self.affected[kind] += int(detail.get('count', 1))
        self.haircut_value += float(detail.get('assumed_haircut_value', 0.0))
        self.handle.write(json.dumps({'kind': kind, 'session': str(session),
                                     'security_id': str(security_id), **detail}, sort_keys=True, allow_nan=False) + '\n')

    def summary(self):
        self.handle.flush()
        return {'scenario': self.scenario, 'config': self.config,
                'event_counts': dict(self.counts), 'affected_observations': dict(self.affected),
                'nominal_portfolio_terminal_haircut_sum': self.haircut_value}

    def close(self):
        if not self.handle.closed:
            summary = self.summary()
            self.handle.close()
            (self.output / 'assumption-audit.json').write_text(json.dumps(summary, indent=2) + '\n')


def leadership_return(strict_function, *, audit, **kwargs):
    if not positive(kwargs.get('prior_signal')):
        raise ValueError('leadership return requires a valid prior signal basis')
    terminal = kwargs.get('terminal')
    if terminal is not None:
        if (str(terminal.get('security_id')) != str(kwargs['security_id']) or
                str(terminal.get('effective_session')) != str(kwargs['session'])):
            raise ValueError('terminal assumption identity/session mismatch')
        if terminal.get('disposition') == 'EXACT_EVIDENCE':
            return strict_function(**kwargs)
        # The prior cohort owns a terminal claim valued at a stated fraction of
        # its real prior close. The current-session print is not a settlement.
        prior = kwargs.get('prior_raw')
        ratio = kwargs.get('split_ratio', 1.0)
        recovery = audit.config['terminal_recovery']
        value = terminal_claim(ratio, prior, ratio, recovery)
        result = value / float(prior) - 1.0
        audit.event('ASSUMED_TERMINAL_LEADERSHIP', kwargs['session'], kwargs['security_id'], recovery=recovery)
        return result, 'ASSUMED_TERMINAL_LEADERSHIP'
    if not positive(kwargs.get('current_signal')):
        if not positive(kwargs.get('prior_signal')):
            raise ValueError('missing leadership return has no valid prior basis')
        audit.event('MISSING_LEADERSHIP_CLOSE_CARRIED', kwargs['session'], kwargs['security_id'])
        return 0.0, 'MISSING_LEADERSHIP_CLOSE_CARRIED'
    return strict_function(**kwargs)


def capacity(strict_function, audit, shares, history, **kwargs):
    result = strict_function(shares, history, **kwargs)
    if result is None:
        audit.event('CAPACITY_DEFERRED', kwargs['session'], kwargs['security_id'], requested_shares=float(shares))
    return result


def once(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError(f'{label}: expected one source seam; found {text.count(old)}')
    return text.replace(old, new, 1)


def install(text):
    text = once(text, 'from collections import defaultdict\n',
                'from collections import defaultdict\nfrom backtester import research_best_effort as _be\n', 'best-effort import')
    anchor = 'actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()'
    text = once(text, anchor, anchor + "\n    _BE=_be.Audit(OUT,os.environ['BEST_EFFORT_SCENARIO'])\n", 'assumption journal')
    old = '            elig=_sec_ok&_base_elig'
    new = """            _be_unknown=np.zeros(len(tids),dtype=bool)
            for _j in np.flatnonzero(_base_elig):
                _mr=_metadata(int(tids[_j]),ds)
                _be_unknown[_j]=_mr is None or str(_mr.get('security_type','')) not in ('common','non_common')
            _be_count=int(_be_unknown.sum())
            if _be_count: _BE.event('UNKNOWN_PRICE_ELIGIBLE',ds,count=_be_count,sample=[str(sid[int(tids[j])]) for j in np.flatnonzero(_be_unknown)[:25]])
            elig=_base_elig&(_sec_ok|(_be_unknown if _BE.config['include_unknown'] else False))"""
    text = once(text, old, new, 'unknown-classification scenario')
    text = once(text, '_lead_ret,_lead_source=_lead_return(',
                '_lead_ret,_lead_source=_be.leadership_return(_lead_return,audit=_BE,', 'leadership assumptions')
    text = once(text, '_lead_terminal_counts[_lead_source]+=1',
                '_lead_terminal_counts[_lead_source]=_lead_terminal_counts.get(_lead_source,0)+1', 'assumed return counts')
    text = once(text, '            term_tids.update(_exact_terms)\n',
                '            term_tids.update(_exact_terms)\n            term_tids.update(_SID_TO_TID[z] for z in _lead_events if z in _SID_TO_TID)\n', 'canonical terminal membership')
    start = text.index('                # Production C1: incomplete documented terms become a carried')
    end = text.index('            open_eq,_=book.equity(opraw)\n', start)
    text = text[:start] + """                _prior=book.last_raw.get(s.tid,np.nan)
                _ratio=float(canonicalsplit[s.tid]); _recovery=_BE.config['terminal_recovery']
                _claim=_be.terminal_claim(s.qty,_prior,_ratio,_recovery)
                _nominal=_be.terminal_claim(s.qty,_prior,_ratio,1.0)
                _BE.event('ASSUMED_PORTFOLIO_TERMINAL',ds,str(sid[s.tid]),quantity=float(s.qty),prior_raw=float(_prior),split_ratio=_ratio,recovery=_recovery,assumed_claim=_claim,assumed_haircut_value=_nominal-_claim)
                # Recognize the claim today; cash becomes available next session.
                book.receivables.append((gday+1,_claim)); book.terminal_pending.pop(s.tid,None)
                book.sec_ready[s.tid]=gday+COOLDOWN
                s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
""" + text[end:]
    old = """            if unresolved and date>=START:
                raise RuntimeError(f'financial-grade NAV unresolved on {ds}')
"""
    new = """            if unresolved:
                for _slot in book.slots:
                    if _slot.held() and not _be.positive(clraw[_slot.tid]):
                        _mark=book.last_raw.get(_slot.tid)
                        if not _be.positive(_mark): raise RuntimeError(f'held security has no historical mark: {ds} {sid[_slot.tid]}')
                        _BE.event('PORTFOLIO_MARK_CARRIED',ds,str(sid[_slot.tid]),quantity=float(_slot.qty),mark=float(_mark))
            if not np.isfinite(eq) or eq<=0: raise RuntimeError(f'invalid best-effort NAV: {ds} {eq}')
"""
    text = once(text, old, new, 'disclosed prior-mark valuation')
    for quantity in ('s.qty', 's.pending_shares'):
        text = once(text, '_research_capacity_guard(' + quantity + ',',
                    '_be.capacity(_research_capacity_guard,_BE,' + quantity + ',', 'capacity audit ' + quantity)
    text = once(text, "'financial_grade_requires_resolved_nav':True,",
                "'financial_grade_requires_resolved_nav':False,", 'uncertified mark policy')
    text = once(text, "'financial_grade_missing_leadership_return_policy':'FAIL_CLOSED',",
                "'financial_grade_missing_leadership_return_policy':'LOGGED_BEST_EFFORT_ASSUMPTIONS',\n        'best_effort_assumptions':_BE.summary(),\n        'certification_status':'NOT_CERTIFIED',", 'uncertified summary')
    old = "'evidence_level':('full_stack_PIT_SEC_CIK_SIC_plus_PIT_ACTIONS' if PIT_MODE else 'research_non_PIT_current_TICKERS_and_ACTIONS'),"
    text = once(text, old, "'evidence_level':'UNCERTIFIED_BEST_EFFORT',", 'best-effort evidence label')
    anchor = "                _rank_ids=[str(sid[int(x)]) for x in durable]\n"
    telemetry = """                _be_unknown_ids={int(tids[j]) for j in np.flatnonzero(_be_unknown)}
                _be_witness=[str(sid[int(t)]) for t in recsel if int(t) in _be_unknown_ids]
                _be_positions=[str(sid[int(s.tid)]) for s in book.slots if s.held() and int(s.tid) in _be_unknown_ids]
                if _be_witness: _BE.event('UNKNOWN_LEADERSHIP_SELECTED',ds,count=len(_be_witness),security_ids=_be_witness)
                if _be_positions: _BE.event('UNKNOWN_POSITIONS_HELD',ds,count=len(_be_positions),security_ids=_be_positions)
"""
    text = once(text, anchor, telemetry + anchor, 'selected unknown exposure audit')
    text = text.replace('[CERT_CAGR]', '[BEST_EFFORT_CAGR]').replace('[CERT_PROGRESS]', '[BEST_EFFORT_PROGRESS]')
    compile(text, '<best-effort-Champion>', 'exec')
    return text


def build_source(output):
    from backtester import run_research_champion_terminal_pit_20y as fixed
    champion = fixed.champion
    if champion.PROFILE_SHA256 != '1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26':
        raise RuntimeError('frozen Champion parameter identity changed')
    original = fixed._terminal_aware_source('fullpit', output)
    return install(original), champion


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def run(args):
    if os.environ.get('PIT_OFFICIAL_BACKTEST', '0') not in ('', '0'):
        raise RuntimeError('best-effort replay requires PIT_OFFICIAL_BACKTEST=0')
    if not os.environ.get('CANONICAL_PIT_DATASET'):
        raise RuntimeError('an authenticated canonical dataset is required')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['BEST_EFFORT_SCENARIO'] = args.scenario
    source, champion = build_source(output)
    generated = output / 'generated-replay.py'
    generated.write_text(source, encoding='utf-8')
    identity = {'status': STATUS, 'certification_status': 'NOT_CERTIFIED',
                'scenario': args.scenario, 'assumptions': SCENARIOS[args.scenario],
                'profile': champion.PROFILE, 'profile_sha256': champion.PROFILE_SHA256,
                'source_sha': os.environ.get('GITHUB_SHA'),
                'runtime_main_sha': '887f479b15ad861313da666ad698034d3847121c',
                'generated_source_sha256': hashlib.sha256(source.encode()).hexdigest(),
                'limitations': LIMITATIONS}
    if not args.self_test:
        manifest=json.loads((Path(os.environ['CANONICAL_PIT_DATASET'])/'manifest.json').read_text())
        identity['canonical_dataset_hash']=manifest['dataset_hash']
        identity['canonical_counts']=manifest['counts']
        identity['measurement_window']=manifest['window']
    write_json(output / 'best-effort-identity.json', identity)
    if args.self_test:
        print('[BEST_EFFORT_ASSEMBLY] PASS; profile unchanged; output UNCERTIFIED')
        return 0
    print(f'[UNCERTIFIED BEST EFFORT] scenario={args.scenario} assumptions={SCENARIOS[args.scenario]}', flush=True)
    rc = subprocess.run([sys.executable, str(generated)], env=dict(os.environ, RESEARCH_REPLAY_MODE='fullpit')).returncode
    if rc:
        write_json(output / 'run-status.json', {**identity, 'completion_status': 'FAILED', 'exit_code': rc})
        return rc
    champion.strict20.old.postprocess('fullpit', output)
    import pandas as pd
    daily = pd.read_csv(output / 'daily.csv.gz')
    gaps = [(daily['research_nav']-daily['A_nav']).abs().max(),
            (daily['research_allocation']-daily['A_allocation']).abs().max()]
    if not all(math.isfinite(float(x)) and float(x)<=1e-12 for x in gaps):
        raise RuntimeError(f'Champion authoritative promotion parity failure: {gaps}')
    expected_end = os.environ.get('CERTIFICATION_END_SESSION', '2026-07-31')
    if str(daily['date'].iloc[-1]) != expected_end:
        raise RuntimeError('best-effort replay is incomplete')
    summary = json.loads((output / 'summary.json').read_text())
    summary.update(identity)
    summary.update(completion_status='COMPLETED', full_stack_pit=False,
                   mode='best_effort', evidence_level=STATUS,
                   promotion_nav_gap=float(gaps[0]), promotion_allocation_gap=float(gaps[1]))
    summary['pit_authority'] = {'classification': 'known canonical classifications; unknown policy recorded in scenario',
                                'issuer_and_sector': 'Champion independent-security / residual-correlation mechanics',
                                'terminal': 'authenticated exact terms when present; recorded recovery assumptions otherwise'}
    summary['best_effort_assumptions'] = json.loads((output/'assumption-audit.json').read_text())
    write_json(output/'summary.json', summary)
    write_json(output/'run-status.json', {**identity, 'completion_status':'COMPLETED'})
    metrics = pd.read_csv(output/'metrics.csv')
    metrics['certification_status']='NOT_CERTIFIED'; metrics['scenario']=args.scenario
    metrics.to_csv(output/'metrics.csv',index=False)
    daily['certification_status']='NOT_CERTIFIED'; daily['scenario']=args.scenario
    daily.to_csv(output/'daily.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    main = metrics[metrics.window_years.astype(str)=='max']
    report = ['# Research Champion — UNCERTIFIED BEST-EFFORT BACKTEST', '',
              f'Scenario: {args.scenario}', f'Source: {identity["source_sha"]}',
              f'Measurement: {daily.date.iloc[0]} to {daily.date.iloc[-1]}', '',
              '## Full-window results', '', '| Series | CAGR | Maximum drawdown | Ending multiple |',
              '|---|---:|---:|---:|']
    for row in main.itertuples():
        report.append(f'| {row.variant} | {row.cagr:.2%} | {row.max_drawdown:.2%} | {row.ending_multiple:.3f} |')
    report += ['', '## Assumptions', '', json.dumps(summary['best_effort_assumptions'], indent=2), '',
               '## Limitations', '', *LIMITATIONS]
    (output/'REPORT.md').write_text('\n'.join(report)+'\n', encoding='utf-8')
    files = sorted(p for p in output.iterdir() if p.is_file() and p.name not in ('SHA256SUMS.txt','replay.log'))
    (output/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in files))
    print('[BEST_EFFORT_COMPLETED] UNCERTIFIED; metrics and assumptions retained', flush=True)
    return 0


def compare(root):
    records=[]
    for path in sorted(Path(root).rglob('summary.json')):
        value=json.loads(path.read_text())
        if value.get('status') != STATUS or value.get('completion_status') != 'COMPLETED':
            continue
        with (path.parent/'metrics.csv').open(newline='') as handle:
            for metric in csv.DictReader(handle):
                if metric['window_years']=='max':
                    records.append({'scenario':value['scenario'], 'certification_status':'NOT_CERTIFIED', **metric})
    dest=Path(root)/'comparison.csv'
    if records:
        with dest.open('w',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
    completed={row['scenario'] for row in records}
    write_json(Path(root)/'comparison-status.json', {'certification_status':'NOT_CERTIFIED',
        'completed_scenarios':sorted(completed), 'missing_scenarios':sorted(set(SCENARIOS)-completed),
        'limitations':LIMITATIONS})
    lines=['# Champion 20-year best-effort comparison — UNCERTIFIED', '', '| Scenario | Series | CAGR | Max drawdown | Ending multiple |', '|---|---|---:|---:|---:|']
    for r in records:
        lines.append(f"| {r['scenario']} | {r['variant']} | {float(r['cagr']):.2%} | {float(r['max_drawdown']):.2%} | {float(r['ending_multiple']):.3f} |")
    lines += ['', 'Missing or failed scenarios: '+', '.join(sorted(set(SCENARIOS)-completed)), '', *LIMITATIONS]
    (Path(root)/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'completed':sorted(completed),'certification_status':'NOT_CERTIFIED'}))
    return 0 if completed==set(SCENARIOS) else 2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--scenario',choices=SCENARIOS,default='baseline')
    parser.add_argument('--output',type=Path,default=Path('best-effort-results'))
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--compare',type=Path)
    args=parser.parse_args()
    if args.compare:
        return compare(args.compare)
    return run(args)

if __name__=='__main__':
    raise SystemExit(main())

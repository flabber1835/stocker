"""Current-code scoped diagnostic. This does not admit the failed input source."""
from collections import defaultdict, deque
from dataclasses import replace
from decimal import Decimal
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile
import argparse
import inspect

from research.bounded_20y.run import vendor
from sentinel.controller import median5 as controller
from sentinel.feed.calendar import previous_sessions
from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core import median5
from stock_strategy_shared.wealth_core.engine import score_universe

parser = argparse.ArgumentParser()
parser.add_argument('--mutation', choices=('adv20', 'both'))
parser.add_argument('--inputs', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
ROOT, OUT = args.inputs, args.output
if args.mutation:
    code = inspect.getsource(median5.advance_signals)
    assert 'sums[i, 6]/20 >= 20_000_000' in code
    code = code.replace('sums[i, 6]/20 >= 20_000_000', 'True')
    if args.mutation == 'both':
        assert 'dv[i] >= 5_000_000' in code
        code = code.replace('dv[i] >= 5_000_000', 'True')
    namespace = dict(median5.__dict__)
    exec(compile(code, '<isolated-eligibility-falsifier>', 'exec'), namespace)
    median5.advance_signals = namespace['advance_signals']
TARGETS = {'FSNMQ': '750813509120092497', 'FCEC': '506347706538298975'}
probe_path = OUT/'reachability-probe.json'
probe = json.loads(probe_path.read_text())
rows = probe['selected_rows']
axis = [s for s in previous_sessions('2026-07-31', 6000) if s >= '2005-01-28']
assert len(axis) == 5410
by_day = defaultdict(list)
for row in rows:
    if row['session'] >= axis[0]:
        if row['security_id'] not in TARGETS.values() or row['ticker'] not in TARGETS:
            raise ValueError('unexpected identity alias needs independent review')
        by_day[row['session']].append(row)

incoming = []
def inspect(stream, member):
    for row in csv.DictReader(stream):
        # Look for explicit target identities as delivered/child securities,
        # plus raw contra-symbol references requiring human adjudication.
        for key in ('delivered_security_id', 'child_security_id', 'delivered_ticker',
                    'child_ticker', 'contraticker'):
            if row.get(key) in set(TARGETS) | set(TARGETS.values()):
                incoming.append(dict(member=member, field=key, row=row))

prefix = ROOT/'pit-prefix-evidence/canonical-2005'
with zipfile.ZipFile(ROOT/'pit-source-5bdc6b39.zip') as z:
    for member in ('actions.csv.gz', 'terminal-events.csv.gz'):
        with z.open(member) as b, gzip.GzipFile(fileobj=b) as g:
            inspect(io.TextIOWrapper(g, encoding='utf8'), 'base/'+member)
        with gzip.open(prefix/member, 'rt', encoding='utf8') as s:
            inspect(s, 'prefix/'+member)
supplement_path = ROOT/'owned55-20y-run/supplements.json'
supplements = json.loads(supplement_path.read_text())
for row in supplements:
    for key in ('delivered_security_id', 'child_security_id', 'delivered_ticker', 'child_ticker'):
        if row.get(key) in set(TARGETS) | set(TARGETS.values()):
            incoming.append(dict(member='supplements', field=key, row=row))

independent = {}
for ticker, sid in TARGETS.items():
    history = deque(maxlen=20)
    maximum = Decimal(0)
    eligible_liquidity_days = []
    for day in axis:
        day_rows = [r for r in by_day[day] if r['security_id'] == sid]
        if len(day_rows) > 1:
            raise ValueError('duplicate identity')
        dv = Decimal(0)
        if day_rows:
            r = day_rows[0]
            if r['raw_close'] and r['raw_compatible_volume']:
                dv = Decimal(r['raw_close'])*Decimal(r['raw_compatible_volume'])
                if not dv.is_finite() or dv < 0:
                    raise ValueError('invalid liquidity inputs')
        history.append(dv)
        adv = sum(history)/20
        maximum = max(maximum, adv)
        if len(history) == 20 and adv >= 20_000_000 and dv >= 5_000_000:
            eligible_liquidity_days.append(day)
    independent[ticker] = dict(max_adv20=str(maximum), liquidity_pass_days=eligible_liquidity_days)

variants = {}
for variant in ('original', 'stated_ratio', 'perturbed_signal'):
    meta = {sid: SecurityMeta(sid, ticker, 'Domestic Common Stock', sid,
                             first_session=axis[0]) for ticker, sid in TARGETS.items()}
    meta['CONTROL'] = SecurityMeta('CONTROL', 'CONTROL', 'Domestic Common Stock',
                                   'CONTROL', first_session=axis[0])
    feed = Feed(meta)
    feed.median5_state = median5.fresh()
    feed.restart_sessions = 260
    witness = controller.fresh()
    consumed = hashlib.sha256()
    eligible = defaultdict(list)
    max_actual_adv = defaultdict(float)
    for index, day in enumerate(axis):
        bars = []
        for row in by_day[day]:
            bar = vendor(row)
            if variant != 'original':
                if (bar.ticker, day) == ('FSNMQ', '2005-02-09'):
                    bar = replace(bar, split_ratio=2.)
                if (bar.ticker, day) == ('FCEC', '2005-04-28'):
                    bar = replace(bar, split_ratio=1.1)
            if variant == 'perturbed_signal' and bar.signal_close:
                # Deliberately extreme finite signal corruption persists for
                # the full lifetime, exceeding either disputed split treatment.
                bar = replace(bar, signal_close=bar.signal_close*(1. + index%7))
            bars.append(bar)
        price = 100.*math.exp(index*.0002 + .01*math.sin(index*.3))
        bars.append(VendorBar(day, 'CONTROL', 'CONTROL', price, price,
                              1e8/price, signal_close=price))
        normalized = feed.advance(day, bars)
        scored = score_universe(normalized.security_bars, median5.config())
        reached = [b.security_id for b in normalized.security_bars
                   if b.eligible and b.security_id in TARGETS.values()]
        if reached:
            failure = dict(status='REFUSED', reason='TARGET_BECAME_ELIGIBLE',
                           session=day, identities=reached, mutation=args.mutation)
            name = 'reachability-refusal-' + (args.mutation or 'baseline')
            (OUT/(name+'.json')).write_text(json.dumps(failure, indent=2)+'\n')
            print(json.dumps(failure), flush=True)
            raise SystemExit(2)
        ranking = median5.rank(scored, feed.median5_state)
        candidates = [s for s in scored if s.momentum is not None and s.recent is not None]
        witness, _ = controller.witness(witness, session=day, candidates=candidates,
            closes={b.security_id: b.closes[-1] for b in normalized.security_bars if b.closes})
        for bar in normalized.security_bars:
            if bar.eligible:
                eligible[bar.security_id].append(day)
        for sid in TARGETS.values():
            sums = feed.median5_state['sums'].get(sid)
            if sums:
                max_actual_adv[sid] = max(max_actual_adv[sid], sums[6]/20)
        consumed.update(json.dumps(dict(
            rank=[s.__dict__ for s in ranking],
            candidates=[s.__dict__ for s in candidates],
            witness=witness), sort_keys=True, allow_nan=False).encode())
    variants[variant] = dict(eligible_days=dict(eligible),
        max_actual_adv20=dict(max_actual_adv), consumed_sha256=consumed.hexdigest())

passed = (not incoming
    and all(not row['liquidity_pass_days'] for row in independent.values())
    and all(not value['eligible_days'].get(sid) for value in variants.values() for sid in TARGETS.values())
    and all(len(value['eligible_days'].get('CONTROL', [])) > 100 for value in variants.values())
    and len({value['consumed_sha256'] for value in variants.values()}) == 1)
result = dict(schema='owned55.current-code-split-scope-diagnostic/1',
    status='PASS_DIAGNOSTIC' if passed else 'REFUSED',
    source_admission_changed=False, source_status='FAIL',
    selected_rows_sha256=hashlib.sha256(probe_path.read_bytes()).hexdigest(),
    supplements_sha256=hashlib.sha256(supplement_path.read_bytes()).hexdigest(),
    sessions=len(axis), independent=independent, variants=variants, incoming=incoming,
    limitations=['Not a general data correction or admission',
      'Requires full source binding, executable falsifiers and review before research use'])
name = 'current-code-reachability' + ('-mutant-'+args.mutation if args.mutation else '')
(OUT/(name+'.json')).write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
print(json.dumps(dict(status=result['status'], independent=independent,
    variants={k:{'max_actual_adv20':v['max_actual_adv20'],
       'eligible_counts':{sid:len(days) for sid,days in v['eligible_days'].items()},
       'consumed_sha256':v['consumed_sha256']} for k,v in variants.items()}, incoming=incoming)), flush=True)
raise SystemExit(0 if passed else 2)

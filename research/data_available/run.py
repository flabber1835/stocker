"""Stream retained real observations through four canonical research books."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date
import gzip
import hashlib
import io
import itertools
import json
import math
from pathlib import Path
import time
import traceback
import zipfile
from contextlib import nullcontext
from functools import partial
from unittest.mock import patch

from stock_strategy_shared.wealth_core.adapter import step_session
from stock_strategy_shared.wealth_core.feed import Feed
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.median5 import fresh
from stock_strategy_shared.wealth_core.run import STRATEGY_ID, STRATEGY_VERSION
from stock_strategy_shared.wealth_core.state import PortfolioState
from stock_strategy_shared.wealth_core.v5 import config, PROFILE
from sentinel.core.spinoffs import apply_supported_entitlements, SpinoffDistribution, LIQUIDATE_CHILD_AT_OPEN
from research.bounded_20y.inputs import BASE_ARCHIVE_SHA256, sha256
from research.bounded_20y.run import metadata, vendor, terminals, distributions
from research.economic_replay60.inputs import Classification
from .policy import VARIANTS, RollingState, snapshot_bars, trim


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf8')
    temporary.replace(path)


class Data:
    def __init__(self, archive, supplements):
        self.sha = sha256(archive)
        if self.sha != BASE_ARCHIVE_SHA256:
            raise ValueError('retained archive differs')
        self.archive = zipfile.ZipFile(archive)
        self.benchmark = {r['session']:float(r['level']) for r in self.rows('benchmark.csv.gz')}
        self.terminal = terminals(self.rows('terminal-events.csv.gz'))
        self.spins = distributions(self.rows('actions.csv.gz'))
        self.supplements_sha = sha256(supplements)
        self.records = json.loads(supplements.read_text())
        grouped = {}
        for row in self.records:
            day, sid = row['effective_session'], row['security_id']
            if row.get('known_by', day) > day:
                raise ValueError('supplement is not known by its effective session')
            if row['kind'] == 'SPINOFF':
                grouped.setdefault((day,sid), []).append(SpinoffDistribution(
                    session=day,parent_ticker=row['ticker'],parent_security_id=sid,
                    child_ticker=row['child_ticker'],child_security_id=row['child_security_id'],
                    source_row_id=row['id'],value_evidence=row.get('value_evidence'),
                    child_shares_per_parent=row['child_shares_per_parent'],child_price=row.get('child_price'),
                    cash_in_lieu_price=row.get('cash_in_lieu_price'),policy=LIQUIDATE_CHILD_AT_OPEN))
            else:
                self.terminal[day] = [r for r in self.terminal.get(day, ()) if r.security_id != sid] + terminals([row])[day]
        for (day,sid), events in grouped.items():
            self.spins[day] = [r for r in self.spins.get(day, ()) if r.parent_security_id != sid] + events

    def rows(self, member):
        with self.archive.open(member) as binary, gzip.GzipFile(fileobj=binary) as compressed:
            yield from csv.DictReader(io.TextIOWrapper(compressed, encoding='utf8', newline=''))

    def sessions(self, end):
        last = None
        for year in range(2006, int(end[:4])+1):
            for day, group in itertools.groupby(self.rows(f'observations-{year}.csv.gz'),key=lambda r:r['session']):
                if day > end:
                    return
                if last is not None and day <= last:
                    raise ValueError('unordered sessions')
                last = day
                rows = list(group)
                if len({r['security_id'] for r in rows}) != len(rows):
                    raise ValueError('duplicate security')
                yield day, rows


class Arm:
    def __init__(self, variant):
        self.variant = variant
        cls = RollingState if variant == 'rolling300' else PortfolioState
        self.state = cls.fresh(50_000,20,entry_sizing_profile=PROFILE)
        if isinstance(self.state, RollingState):
            self.state.initialize_research()
        self.state.median5 = fresh()
        self.pending, self.last_known, self.ledger = [], {}, Ledger()
        self.counters, self.rows, self.events = {}, [], Counter()

    def step(self, day, norm, signals, events=(), spins=(), vendor_bars=(), bases=None, windows=None):
        before = len(self.ledger.events)
        apply_supported_entitlements(self.state, spins, bars=vendor_bars, ledger=self.ledger, config=config())
        from .account import decide as account_decide
        # Scoped single-thread research seam. The original callable is restored
        # even when the canonical economic step raises. No production file edit.
        context=(patch('stock_strategy_shared.wealth_core.adapter.decide',
                       partial(account_decide,windows=windows or {},orders=self.pending))
                 if self.variant=='account300' else nullcontext())
        with context:
            result = step_session(session=day,state=self.state,bars=norm.bars,
                pending=self.pending,ledger=self.ledger,last_known=self.last_known,cfg=config(),
                strategy_id=STRATEGY_ID,strategy_version=STRATEGY_VERSION,
                security_bars=signals,terminal_terms=events,prior_conversion_bases=bases or {},
                settlement_counters=self.counters)
        if isinstance(self.state, RollingState):
            self.state.remember_entries(day)
        new = self.ledger.events[before:]
        self.events.update(e.event_type.value for e in new)
        row = dict(session=day,equity=result.resolved_equity,
            estimated_equity=result.estimated_equity,blocked=result.blocked,
            holdings=len(self.state.episodes),cash=self.state.cash,
            fees=sum(e.fees for e in new),
            turnover=sum(abs(e.shares_delta)*(e.price or 0) for e in new if e.event_type.value in ('BUY','SELL')),
            fills=len(result.fills),queued=len(self.pending),
            eligible=sum(b.eligible for b in signals),
            stops=sum(o.reason.value=='EXIT_TRAILING_STOP' for o in result.decision.operations),
            held=sorted(self.state.held_security_ids()))
        self.rows.append(row)
        return row

    def report(self):
        rows = self.rows
        valid = bool(rows) and all(r['equity'] is not None and r['equity'] > 0 for r in rows)
        values = [50_000.] + [r['equity'] for r in rows] if valid else []
        peak, drawdown = 50_000., 0.
        for value in values:
            peak = max(peak,value)
            drawdown = min(drawdown,value/peak-1)
        years = (date.fromisoformat(rows[-1]['session'])-date.fromisoformat(rows[0]['session'])).days/365.25 if rows else 0
        multiple = values[-1]/50_000 if valid else None
        return dict(variant=self.variant,sessions=len(rows),start=rows[0]['session'] if rows else None,
            end=rows[-1]['session'] if rows else None,performance_available=valid,
            multiple=multiple,cagr=math.expm1(math.log(multiple)/years) if valid and years else None,
            maximum_drawdown=drawdown if valid else None,
            final_equity=rows[-1]['equity'] if rows else None,
            fees=sum(r['fees'] for r in rows),turnover_dollars=sum(r['turnover'] for r in rows),
            blocked_sessions=sum(r['blocked'] for r in rows),
            stop_signals=sum(r['stops'] for r in rows),events=dict(self.events),settlement=dict(self.counters),
            average_holdings=sum(r['holdings'] for r in rows)/len(rows) if rows else 0)


def run(args):
    args.output.mkdir(parents=True,exist_ok=False)
    started = time.monotonic()
    print('Validating local inputs',flush=True)
    data = Data(args.archive,args.supplements)
    classifier = Classification()
    arms = {name:Arm(name) for name in VARIANTS}
    feed = Feed({})
    feed.median5_state = arms['baseline'].state.median5
    # Research dataset event proxies are explicit input records, not ticker code.
    repairs = json.loads(Path(__file__).with_name('input-repairs.json').read_text())
    write(args.output/'identity.json',dict(base='b812db40bcb68b06a9d79eb1ad8e7a6885180671',
        archive_sha256=data.sha,supplements_sha256=data.supplements_sha,
        variants=VARIANTS,capital=50000,warmup_sessions=300,requested_end=args.end,
        research_only=True,controller_included=False,provider_vintages_available=False,
        source_sha256={p.as_posix():sha256(p) for base in ('research/data_available','shared/stock_strategy_shared/wealth_core') for p in Path(base).glob('*.py')}))
    status = 'COMPLETE'
    count = 0
    with (args.output/'daily.jsonl').open('w',encoding='utf8') as trace:
        for index,(day,raw) in enumerate(data.sessions(args.end)):
            for i,row in enumerate(raw):
                repair = next((r for r in repairs if r['session']==day and r['security_id']==row['security_id']),None)
                if repair:
                    blob = json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
                    if hashlib.sha256(blob).hexdigest()!=repair['source_sha256']:
                        raise ValueError('research source repair mismatch')
                    raw[i] = {**row,'dividend_per_share':'0'}
            rows = [classifier.apply(r) for r in raw]
            meta = {r['security_id']:metadata(r) for r in rows}
            feed.meta = meta
            bars = tuple(vendor(r) for r in rows)
            bases = {t.security_id:b for t in data.terminal.get(day,()) if (b:=feed.prior_conversion_basis(t.security_id)) is not None}
            norm = feed.advance(day,bars)
            trim(feed)
            if index < 300:
                if index%100==0:
                    print(json.dumps(dict(phase='WARMUP',session=day,elapsed=round(time.monotonic()-started,1))),flush=True)
                continue
            signals = snapshot_bars(feed,norm.security_bars)
            windows={b.security_id:feed.series[b.security_id].signal_closes[-300:]
                     for b in signals if feed.series[b.security_id].session_indices[-1:]==[index]}
            daily = {}
            for name,arm in arms.items():
                daily[name] = arm.step(day,norm,norm.security_bars if name=='baseline' else signals,
                    data.terminal.get(day,()),data.spins.get(day,()),bars,bases,windows)
            trace.write(json.dumps(dict(session=day,arms=daily,spy=data.benchmark[day]),allow_nan=False)+'\n')
            trace.flush()
            count += 1
            if count%25==0:
                progress = dict(phase='REPLAY',session=day,measured_sessions=count,
                    elapsed_seconds=round(time.monotonic()-started,1),equity={n:a.rows[-1]['equity'] for n,a in arms.items()})
                write(args.output/'status.json',progress)
                print(json.dumps(progress),flush=True)
            if args.max_sessions and count>=args.max_sessions:
                status='BOUNDED_RUN_COMPLETE'
                break
            if time.monotonic()-started>args.seconds:
                status='TIME_BUDGET_REACHED'
                break
    reports = {n:a.report() for n,a in arms.items()}
    if count:
        start,end=arms['baseline'].rows[0]['session'],arms['baseline'].rows[-1]['session']
        values=[data.benchmark[r['session']] for r in arms['baseline'].rows]
        peak=values[0]; dd=0.
        for value in values:
            peak=max(peak,value); dd=min(dd,value/peak-1)
        benchmark=dict(start=start,end=end,multiple=values[-1]/values[0],maximum_drawdown=dd)
    else:
        benchmark=None
    result=dict(status=status,elapsed_seconds=time.monotonic()-started,arms=reports,spy=benchmark,
        daily_sha256=sha256(args.output/'daily.jsonl'),
        differences={name:sum(a['held']!=b['held'] for a,b in zip(arms['baseline'].rows,arms[name].rows)) for name in VARIANTS if name!='baseline'})
    write(args.output/'result.json',result)
    write(args.output/'status.json',dict(status=status,measured_sessions=count))
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--supplements',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--end',default='2026-07-31')
    parser.add_argument('--max-sessions',type=int,default=0)
    parser.add_argument('--seconds',type=int,default=10800)
    args=parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        if args.output.exists():
            write(args.output/'failure.json',dict(error=repr(exc),traceback=traceback.format_exc()))
        raise

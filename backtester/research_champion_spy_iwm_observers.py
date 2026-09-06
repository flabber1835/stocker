#!/usr/bin/env python3
"""Fresh, same-session SPY/IWM observation-policy experiment. RESEARCH / NOT CERTIFIED.

The corrected Champion's Wealth Core, Native guard, and accounting are generated
from the pinned harness. This module receives that freshly generated state once
per session and advances independent outer controllers. Prior replay artifacts
are permitted solely to the separate, post-run reference checker.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
POINTER = ROOT / 'backtester/data/champion-spy-iwm-observer-inputs-v1.json'
STATUS = 'RESEARCH_NOT_CERTIFIED'
PROFILE_SHA = '1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26'
DATASET_SHA = '5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993'
RUNTIME_SHA = '887f479b15ad861313da666ad698034d3847121c'
BASE_SHA = '1e7875d2b83fc549e316a97d573633b060461eda'
BASELINE_DAILY_SHA = 'fbc8a18d2e6f01bbc5154fe359990633bbe93e28b4dbeba57da0be149f4811a8'
END = pd.Timestamp('2026-07-31')
STARTS = {'full20': pd.Timestamp('2006-07-31'), 'fresh5': pd.Timestamp('2021-08-02')}
FAMILIES = ('spy', 'spy_iwm', 'spy_iwm_vix')
MA_GRID = (80, 120, 160)
DD_GRID = (-0.08, -0.10, -0.12)
RATIO_GRID = (1.0, 1.2, 1.4)
RECOVERY = 8
SPY_REBOUND = 0.11
WC_DRAWDOWN = -0.10
EXPOSURE_CEILING = 0.55
VIX_STRESS = 25.0
VIX_RECOVERY = 20.0
EPS = 1e-12


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + '\n', encoding='utf-8')


def finite(value: object) -> bool:
    return value is not None and bool(np.isfinite(value))


def verify_inputs(root: Path, pointer: Path = POINTER) -> dict:
    expected = json.loads(pointer.read_text())
    if '@sha256:' not in expected['package']:
        raise RuntimeError('Observer package must be content addressed')
    if digest(root / 'MANIFEST.json') != expected['manifest_sha256']:
        raise RuntimeError('Observer manifest hash mismatch')
    manifest = json.loads((root / 'MANIFEST.json').read_text())
    if manifest['files'] != expected['files']:
        raise RuntimeError('Observer pointer/manifest file lists disagree')
    for name, sha in expected['files'].items():
        if Path(name).name != name or digest(root / name) != sha:
            raise RuntimeError(f'Observer input hash mismatch: {name}')
    return expected


def read_prices(path: Path, column: str) -> pd.Series:
    frame = pd.read_csv(path, parse_dates=['date'])
    if frame['date'].isna().any() or frame['date'].duplicated().any() or not frame['date'].is_monotonic_increasing:
        raise RuntimeError(f'Duplicated or out-of-order observations: {path.name}')
    values = pd.to_numeric(frame[column], errors='raise')
    if not np.isfinite(values).all() or (values <= 0).any():
        raise RuntimeError(f'Invalid prices: {path.name}')
    if frame['date'].max() > END:
        raise RuntimeError(f'Observer observation extends beyond cutoff: {path.name}')
    return pd.Series(values.to_numpy(), index=pd.DatetimeIndex(frame['date']), name=column)


def features(prices: pd.Series) -> pd.DataFrame:
    """All windows end at the current close; no future padding or centered windows."""
    if not prices.index.is_monotonic_increasing or prices.index.has_duplicates:
        raise RuntimeError('Price calendar must be unique and increasing')
    result = pd.DataFrame(index=prices.index)
    returns = prices.pct_change(fill_method=None)
    result['r20'] = prices.pct_change(20, fill_method=None)
    result['r40'] = prices.pct_change(40, fill_method=None)
    result['dd126'] = prices / prices.rolling(126, min_periods=126).max() - 1.0
    result['rv20'] = returns.rolling(20, min_periods=20).std(ddof=1) * math.sqrt(252)
    result['rv60'] = returns.rolling(60, min_periods=60).std(ddof=1) * math.sqrt(252)
    result['ratio'] = result.rv20 / result.rv60
    # A completely constant series has no volatility acceleration.
    zero = result.rv20.eq(0.0) & result.rv60.eq(0.0)
    result.loc[zero, 'ratio'] = 1.0
    for length in MA_GRID:
        result[f'trend{length}'] = prices / prices.rolling(length, min_periods=length).mean() - 1.0
    return result


class MarketData:
    def __init__(self, root: Path, sessions: list[str], start: pd.Timestamp, end: pd.Timestamp):
        self.pointer = verify_inputs(root)
        spy = read_prices(root / 'spy-sfp.csv.gz', 'closeadj')
        iwm = read_prices(root / 'iwm-sfp.csv.gz', 'closeadj')
        vix = read_prices(root / 'vix-cboe.csv.gz', 'close')
        self.spy = spy
        frame = features(spy).add_prefix('spy_')
        frame = frame.join(features(iwm.reindex(spy.index)).add_prefix('iwm_'))
        # Lag on the equity trading calendar. Missing values remain missing.
        frame['vix_lag1'] = vix.reindex(spy.index).shift(1)
        frame['vix_source_session'] = pd.Series(spy.index, index=spy.index).shift(1)
        required = pd.DatetimeIndex(sessions)
        required = required[(required >= start) & (required <= end)]
        missing = required.difference(frame.index)
        if len(missing):
            raise RuntimeError(f'Missing market sessions: {list(missing[:10])}')
        numeric = frame.columns.drop('vix_source_session')
        bad = ~np.isfinite(frame.loc[required, numeric].to_numpy(dtype=float))
        if bad.any():
            row, col = np.argwhere(bad)[0]
            raise RuntimeError(f'Missing observer feature: {required[row]} {numeric[col]}')
        self.frame = frame
        self.rows = {str(date.date()): row for date, row in frame.to_dict(orient='index').items()}

    def at(self, date: pd.Timestamp) -> dict:
        try:
            return self.rows[str(date.date())]
        except KeyError as exc:
            raise RuntimeError(f'Observer session absent: {date}') from exc


@dataclass(frozen=True)
class Config:
    family: str
    ma: int
    drawdown: float
    vol_ratio: float

    def __post_init__(self):
        if self.family not in FAMILIES or self.ma not in MA_GRID:
            raise ValueError('Unsupported observation configuration')
        if self.drawdown not in DD_GRID or self.vol_ratio not in RATIO_GRID:
            raise ValueError('Configuration outside preregistered grid')

    @property
    def name(self) -> str:
        return f'{self.family}-ma{self.ma}-dd{abs(self.drawdown):.2f}-vr{self.vol_ratio:.1f}'

    @property
    def central(self) -> bool:
        return self.ma == 120 and self.drawdown == -0.10 and self.vol_ratio == 1.2


def configs() -> list[Config]:
    return [Config(*values) for values in itertools.product(FAMILIES, MA_GRID, DD_GRID, RATIO_GRID)]


@dataclass(frozen=True)
class Observation:
    available: bool
    stress: bool
    full_healthy: bool
    positive: bool
    return20_floor: float | None
    vix_recovered: bool


def observe(config: Config, row: dict) -> Observation:
    symbols = ('spy',) if config.family == 'spy' else ('spy', 'iwm')
    keys = [f'{symbol}_{name}' for symbol in symbols
            for name in ('r20', 'r40', 'dd126', 'ratio', f'trend{config.ma}')]
    if config.family == 'spy_iwm_vix':
        keys.append('vix_lag1')
    if not all(finite(row.get(key)) for key in keys):
        return Observation(False, False, False, False, None, False)
    stress = any(row[f'{s}_trend{config.ma}'] < 0 and row[f'{s}_dd126'] <= config.drawdown
                 and row[f'{s}_ratio'] >= config.vol_ratio for s in symbols)
    full = all(row[f'{s}_r20'] > 0 and row[f'{s}_r40'] > 0 and row[f'{s}_ratio'] <= 1
               for s in symbols)
    positive = all(row[f'{s}_r20'] > 0 for s in symbols)
    vix_recovered = True
    if config.family == 'spy_iwm_vix':
        stress = stress and row['vix_lag1'] >= VIX_STRESS
        vix_recovered = row['vix_lag1'] <= VIX_RECOVERY
        full = full and vix_recovered
    return Observation(True, bool(stress), bool(full), bool(positive),
                       min(row[f'{s}_r20'] for s in symbols), bool(vix_recovered))


@dataclass
class Controller:
    config: Config
    episode: bool = False
    latched: bool = False
    full_streak: int = 0
    positive_streak: int = 0
    prev_native: float = 1.0
    prev_desired: float = 1.0
    entries: int = 0
    episodes: int = 0
    concordance_releases: int = 0

    def step(self, native: float, effective_native: float, wcdd: float,
             spy20: float | None, wc20: float | None, observation: Observation) -> tuple[float, str]:
        if not finite(native) or not 0 <= native <= 1:
            raise RuntimeError('Native allocation outside long-only envelope')
        o = observation
        self.full_streak = self.full_streak + 1 if o.available and o.full_healthy else 0
        rebound = finite(spy20) and spy20 > SPY_REBOUND
        reasons = []
        if self.prev_native >= 1-EPS and native < 1-EPS:
            if not self.episode:
                self.episodes += 1
            self.episode = True
            self.positive_streak = 0
            reasons.append('RECOVERY_EPISODE_START')
        if self.episode:
            self.positive_streak = self.positive_streak + 1 if native > 0 and o.positive else 0
        else:
            self.positive_streak = 0
        cleared = self.latched and (self.full_streak >= RECOVERY or rebound)
        if cleared:
            self.latched = False
            reasons.append('MARKET_STRESS_CLEAR')
        desired = native
        if self.episode and native >= 1-EPS:
            concordant = (self.positive_streak >= RECOVERY and finite(wc20) and wc20 > 0
                          and finite(o.return20_floor) and o.return20_floor >= wc20
                          and finite(spy20) and spy20 >= wc20 and o.vix_recovered)
            if self.full_streak >= RECOVERY or rebound or concordant:
                self.episode = False
                desired = 1.0
                if concordant and self.full_streak < RECOVERY and not rebound:
                    self.concordance_releases += 1
                    reasons.append('RECOVERY_CROSS_SURFACE')
                elif self.full_streak >= RECOVERY:
                    reasons.append('RECOVERY_PERSISTENCE')
                else:
                    reasons.append('RECOVERY_SPY_REBOUND')
                self.positive_streak = 0
            else:
                desired = self.prev_desired
                reasons.append('FULL_RISK_HELD')
        eligible = (native >= 1-EPS and finite(effective_native) and effective_native >= 1-EPS
                    and finite(wcdd) and wcdd <= WC_DRAWDOWN and o.available and finite(spy20))
        if not self.latched and not cleared and eligible and o.stress:
            self.latched = True
            self.entries += 1
            reasons.append('MARKET_STRESS_ENTER')
        if self.latched:
            desired = min(desired, EXPOSURE_CEILING)
        desired = min(native, desired)
        if not 0 <= desired <= native:
            raise RuntimeError('Outer controller violated Native guard envelope')
        self.prev_native, self.prev_desired = native, desired
        return float(desired), '|'.join(reasons) if reasons else 'NORMAL'


def score(curve: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    curve = np.asarray(curve, dtype=float)
    if len(curve) < 2 or not np.isfinite(curve).all() or (curve <= 0).any():
        raise RuntimeError('Metric curve must contain finite positive values')
    years = (dates[-1] - dates[0]).days / 365.2425
    returns = curve[1:] / curve[:-1] - 1
    sd = returns.std(ddof=1)
    return dict(start=str(dates[0].date()), end=str(dates[-1].date()), sessions=len(curve),
                elapsed_years=years, cagr=float((curve[-1]/curve[0])**(1/years)-1),
                max_drawdown=float(np.min(curve/np.maximum.accumulate(curve)-1)),
                sharpe_zero_rf=float(returns.mean()/sd*np.sqrt(252)) if sd > 0 else None,
                ending_multiple=float(curve[-1]/curve[0]))


def exposure_episodes(frame: pd.DataFrame) -> list[dict]:
    active = frame.allocation.to_numpy() < 1-EPS
    episodes, begin = [], None
    for i, value in enumerate(active):
        if value and begin is None:
            begin = i
        if begin is not None and (not value or i == len(active)-1):
            end = i if value else i-1
            episodes.append(dict(start=str(frame.date.iloc[begin].date()),
                                 end=str(frame.date.iloc[end].date()), sessions=end-begin+1,
                                 min_allocation=float(frame.allocation.iloc[begin:end+1].min()),
                                 open_at_end=bool(value and i == len(active)-1)))
            begin = None
    return episodes


class Experiment:
    """Independent controllers around a single newly generated raw book."""
    def __init__(self, root: Path, output: Path, start: pd.Timestamp, end: pd.Timestamp,
                 sessions: list[str], mode: str):
        if mode not in STARTS or start != STARTS[mode] or end != END:
            raise RuntimeError('Experiment window drifted from preregistration')
        self.mode, self.start, self.end, self.output = mode, start, end, output
        index = pd.DatetimeIndex(sessions)
        if start not in index:
            raise RuntimeError('Launch date is not in canonical session calendar')
        position = index.get_loc(start)
        if mode == 'fresh5' and position < 260:
            raise RuntimeError('Fresh launch requires 260 prior indicator sessions')
        self.warmup_start = index[position-260] if mode == 'fresh5' else index[0]
        self.market = MarketData(root, sessions, self.warmup_start, end)
        self.grid = configs()
        self.controllers = {c.name: Controller(c) for c in self.grid}
        self.names = ['champion', 'native_guard'] + list(self.controllers)
        self.pending = {name: 1.0 for name in self.names}
        self.effective = self.pending.copy()
        self.nav = self.pending.copy()
        self.rows: list[dict] = []
        self.source_rows: list[dict] = []
        self.prev_close: float | None = None
        self.prev_date: pd.Timestamp | None = None
        self.last_seen: pd.Timestamp | None = None
        self.initial_state_verified = mode == 'full20'
        write_json(output / 'observer-configs.json', [asdict(c) | {'candidate': c.name, 'central': c.central}
                                                     for c in self.grid])

    def launch(self, book: object) -> None:
        """Validate the source harness' explicit all-cash fresh initialization."""
        if self.mode != 'fresh5':
            raise RuntimeError('Launch reset is for the independently initialized arm only')
        if any(s.held() or s.reserved() for s in book.slots):
            raise RuntimeError('Fresh launch inherited holdings or orders')
        if book.cash != 100_000_000.0 or book.receivables or book.sec_ready or book.terminal_pending:
            raise RuntimeError('Fresh launch inherited path-dependent financial state')
        if self.rows or self.prev_close is not None:
            raise RuntimeError('Fresh launch has already measured economics')
        self.initial_state_verified = True
        write_json(self.output / 'fresh-launch-state.json', dict(status='PASS', start=str(self.start.date()),
                    warmup_start=str(self.warmup_start.date()), warmup_sessions=260, cash=book.cash,
                    held=0, pending=0, receivables=0, cooldowns=0, controller_state='NEW',
                    prior_market_indicators='WARM', inherited_portfolio_history=False))

    def advance(self, date: pd.Timestamp, native: float, effective_native: float,
                wcdd: float, wc20: float | None, spy20: float | None,
                champion_target: float, open_equity: float, close_equity: float,
                bil: pd.DataFrame, overlay: Callable) -> None:
        if self.last_seen is not None and date <= self.last_seen:
            raise RuntimeError('Experiment sessions must advance strictly chronologically')
        self.last_seen = date
        if self.mode == 'fresh5' and date < self.start:
            return
        if not self.initial_state_verified:
            raise RuntimeError('Fresh launch state has not been verified')
        row = self.market.at(date)
        observations = {c.name: observe(c, row) for c in self.grid}
        if not all(o.available for o in observations.values()):
            raise RuntimeError(f'Market observation unavailable on {date}')
        targets = {'champion': (float(champion_target), 'FRESH_CHAMPION'),
                   'native_guard': (float(native), 'FRESH_NATIVE_GUARD')}
        for name, controller in self.controllers.items():
            targets[name] = controller.step(native, effective_native, wcdd, spy20, wc20, observations[name])
        if date >= self.start:
            for name in self.names:
                old, new = self.effective[name], self.pending[name]
                cost = 0.0
                if self.prev_close is not None:
                    self.nav[name], cost = overlay(self.nav[name], old, new, self.prev_close,
                                                   open_equity, close_equity, bil, date, self.prev_date)
                self.effective[name] = new
                desired, reason = targets[name]
                self.rows.append(dict(date=date, candidate=name, nav=self.nav[name], allocation=new,
                                      close_target=desired, turnover=abs(new-old), transition_cost=cost,
                                      reason=reason, market_stress=observations[name].stress if name in observations else None,
                                      latched=self.controllers[name].latched if name in self.controllers else None))
            self.source_rows.append(dict(date=date, raw_wc_equity=close_equity, raw_wc_open=open_equity,
                                        native_close_target=native, native_gate_input=effective_native,
                                        wc_dd=wcdd, wc_r20=wc20, spy_r20_native=spy20,
                                        cash_gap_factor=float(bil.loc[date, 'gap_factor']),
                                        cash_intraday_factor=float(bil.loc[date, 'intraday_factor']), **row))
            self.prev_close, self.prev_date = close_equity, date
            if date.month in (3, 6, 9, 12) and date.day >= 28:
                central = next(c.name for c in self.grid if c.family == 'spy_iwm' and c.central)
                print(f'[OBSERVER_PROGRESS] {date.date()} champion={self.nav["champion"]:.8f} '
                      f'spy_iwm_center={self.nav[central]:.8f} variants={len(self.names)}', flush=True)
        # All new decisions take effect at the following session open.
        for name in self.names:
            self.pending[name] = targets[name][0]

    def finish(self, source: pd.DataFrame) -> None:
        frame = pd.DataFrame(self.rows)
        if frame.empty or frame.date.min() != self.start or frame.date.max() != self.end:
            raise RuntimeError('Observer replay window incomplete')
        champion = frame[frame.candidate.eq('champion')].reset_index(drop=True)
        if list(champion.date) != list(source.date):
            raise RuntimeError('Shared-book control dates differ')
        nav_gap = float(np.max(np.abs(champion.nav.to_numpy()-source.control_nav.to_numpy())))
        allocation_gap = float(np.max(np.abs(champion.allocation.to_numpy()-source.control_allocation.to_numpy())))
        if nav_gap > 1e-12 or allocation_gap > 1e-12:
            raise RuntimeError(f'Fresh shared control parity failed: {nav_gap}, {allocation_gap}')
        write_json(self.output / 'observer-internal-parity.json', dict(status='PASS', nav_gap=nav_gap,
                   allocation_gap=allocation_gap, same_session_arms=len(self.names),
                   shared_fresh_book=True, prior_replay_used_as_input=False))
        frame.to_csv(self.output / 'observer-daily.csv.gz', index=False, compression={'method':'gzip','mtime':0})
        pd.DataFrame(self.source_rows).to_csv(self.output / 'observer-source-sessions.csv.gz', index=False,
                                             compression={'method':'gzip','mtime':0})
        stats, annual, episodes = [], [], []
        dates = pd.DatetimeIndex(champion.date)
        baseline_nav = champion.nav.to_numpy()
        spy = source.spy_nav.to_numpy()
        for name in self.names + ['spy_benchmark']:
            candidate = (frame[frame.candidate.eq(name)].reset_index(drop=True) if name != 'spy_benchmark'
                         else pd.DataFrame(dict(date=dates, nav=spy, allocation=np.ones(len(dates)), turnover=np.zeros(len(dates)))))
            horizons = [('full', 0)] + [(str(n), n) for n in (5, 10, 15, 20)
                                       if (dates[-1]-dates[0]).days >= n*365.2425-5]
            for label, years in horizons:
                take = np.arange(len(dates)) if not years else np.flatnonzero(dates >= dates[-1]-pd.DateOffset(years=years))
                v = candidate.nav.to_numpy()[take]
                m = score(v, dates[take])
                stats.append(dict(candidate=name, window_years=label, mode=self.mode, status=STATUS,
                                  reduced_sessions=int((candidate.allocation.to_numpy()[take] < 1-EPS).sum()),
                                  allocation_turnover=float(candidate.turnover.to_numpy()[take].sum()), **m))
            ratios = np.log(candidate.nav.to_numpy()/baseline_nav)
            changes = np.diff(ratios, prepend=0.0)
            for year in sorted(set(dates.year)):
                delta = float(changes[dates.year == year].sum())
                annual.append(dict(candidate=name, year=year, relative_log_wealth_contribution=delta,
                                   relative_wealth_factor=math.exp(delta)))
            for ep in exposure_episodes(candidate):
                episodes.append(dict(candidate=name, **ep))
        metrics = pd.DataFrame(stats)
        metrics.to_csv(self.output / 'observer-metrics.csv', index=False)
        pd.DataFrame(annual).to_csv(self.output / 'observer-annual-attribution.csv', index=False)
        pd.DataFrame(episodes).to_csv(self.output / 'observer-exposure-episodes.csv', index=False)
        self.report(frame, metrics, champion)
        print('[OBSERVER_COMPLETE] fresh chronological multi-arm replay; RESEARCH_NOT_CERTIFIED', flush=True)

    def report(self, daily: pd.DataFrame, metrics: pd.DataFrame, champion: pd.DataFrame) -> None:
        full = metrics[metrics.window_years.eq('full')].set_index('candidate')
        base = full.loc['champion']
        rows = []
        for c in self.grid:
            m = full.loc[c.name]
            neighbors = [n for n in self.grid if n.family == c.family and sum([
                abs(MA_GRID.index(n.ma)-MA_GRID.index(c.ma)),
                abs(DD_GRID.index(n.drawdown)-DD_GRID.index(c.drawdown)),
                abs(RATIO_GRID.index(n.vol_ratio)-RATIO_GRID.index(c.vol_ratio))]) == 1]
            neighborhood = full.loc[[c.name] + [n.name for n in neighbors]]
            allocations = daily[daily.candidate.eq(c.name)].allocation.to_numpy()
            changed = np.flatnonzero(abs(allocations-champion.allocation.to_numpy()) > EPS)
            rows.append(dict(candidate=c.name, **asdict(c), central=c.central, cagr=float(m.cagr),
                             max_drawdown=float(m.max_drawdown), ending_multiple=float(m.ending_multiple),
                             cagr_gap_vs_champion=float(m.cagr-base.cagr),
                             dd_gap_vs_champion=float(m.max_drawdown-base.max_drawdown),
                             adjacent_points=len(neighbors), local_cagr_range=float(neighborhood.cagr.max()-neighborhood.cagr.min()),
                             local_drawdown_range=float(neighborhood.max_drawdown.max()-neighborhood.max_drawdown.min()),
                             economic_screen_pass=bool(m.cagr >= base.cagr-0.02 and m.max_drawdown >= base.max_drawdown-0.03),
                             allocation_sessions_changed=len(changed),
                             first_allocation_divergence=str(champion.date.iloc[changed[0]].date()) if len(changed) else ''))
        grid = pd.DataFrame(rows)
        grid.to_csv(self.output / 'observer-plateau-grid.csv', index=False)
        families = []
        for name, group in grid.groupby('family'):
            families.append(dict(family=name, points=len(group), passing_points=int(group.economic_screen_pass.sum()),
                                 median_cagr=float(group.cagr.median()), min_cagr=float(group.cagr.min()),
                                 max_cagr=float(group.cagr.max()), median_drawdown=float(group.max_drawdown.median()),
                                 median_local_cagr_range=float(group.local_cagr_range.median())))
        pd.DataFrame(families).to_csv(self.output / 'observer-family-summary.csv', index=False)
        central = ['champion', 'native_guard'] + [c.name for c in self.grid if c.central] + ['spy_benchmark']
        lines = ['# SPY / IWM observation experiment', '', '**RESEARCH / NOT CERTIFIED**', '',
                 f'Mode: `{self.mode}`. Fresh chronological shared-book replay, {len(self.names)} same-session arms.',
                 f'Window: {self.start.date()} through {self.end.date()}.', '',
                 'The central parameter point was specified before results. No replacement is selected automatically.', '',
                 '| Predeclared arm | CAGR | Max drawdown | Ending multiple |', '|---|---:|---:|---:|']
        for name in central:
            m = full.loc[name]
            lines.append(f'| {name} | {m.cagr:.2%} | {m.max_drawdown:.2%} | {m.ending_multiple:.3f}x |')
        lines += ['', '## Scope', '',
                  'Wealth Core and Native protection remain frozen. External observers replace the outer leadership-dependent predicates. '
                  'The Native guard still responds to actual portfolio changes. Classification independence of external observations '
                  'does not establish economic invariance when stock selection changes.', '',
                  'These histories contain provisional classifications and retrospectively adjusted market observations. '
                  'Historical vendor-vintage PIT availability is not established. No result is formally certified.', '',
                  'See observer-metrics.csv for exact window dates and the matched SPY benchmark; observer-plateau-grid.csv for every grid point; '
                  'observer-annual-attribution.csv for additive relative log-wealth contributions; observer-exposure-episodes.csv for defensive intervals.']
        (self.output / 'OBSERVER_REPORT.md').write_text('\n'.join(lines)+'\n')
        write_json(self.output / 'observer-run-summary.json', dict(status=STATUS, mode=self.mode,
                   start=str(self.start.date()), end=str(self.end.date()), arms=len(self.names),
                   initial_state_verified=self.initial_state_verified, input_pointer=self.market.pointer,
                   central_points=central, families=families, formal_certification=False))


def once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f'{label}: expected unique source seam; found {text.count(old)}')
    return text.replace(old, new, 1)


def class_hashes(text: str) -> dict:
    protected = {'Book', 'Slot', 'Native', 'CandidateA', 'ControlLDRC', 'CandidateB'}
    return {node.name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
            for node in ast.parse(text).body if isinstance(node, ast.ClassDef) and node.name in protected}


def install(text: str, mode: str) -> str:
    before = class_hashes(text)
    if len(before) != 6:
        raise RuntimeError('Expected six frozen book/controller classes')
    text = once(text, 'import pandas as pd\n',
                'import pandas as pd\nfrom backtester import research_champion_spy_iwm_observers as _observer\n', 'observer import')
    text = once(text, '    ctl=ControlLDRC(); ca=CandidateA(); cb=CandidateB()\n',
                '    ctl=ControlLDRC(); ca=CandidateA(); cb=CandidateB()\n'
                f'    _observers=_observer.Experiment(Path(os.environ["OBSERVER_INPUT_ROOT"]),OUT,START,END,list(_CANONICAL.sessions),{mode!r})\n',
                'independent controller initialization')
    anchor = '            b_d,b_reason=cb.step(native_target,recent_r20,spy20)\n'
    text = once(text, anchor, anchor +
                '            _observers.advance(date,native_target,effective_native,dd,r20,spy20,a_d,open_eq,eq,bil,apply_overlay)\n',
                'same-session controller advance')
    text = once(text, '    out=pd.DataFrame(rows)\n',
                '    out=pd.DataFrame(rows)\n    _observers.finish(out)\n', 'fresh output validation')
    if mode == 'fresh5':
        text = once(text, "START = pd.Timestamp('2006-07-31')", "START = pd.Timestamp('2021-08-02')", 'fresh start')
        text = once(text, '    for y in range(2006,END.year+1):',
                    '    for y in range(_observers.warmup_start.year,END.year+1):', 'bounded price warmup')
        text = once(text, 'd.date=pd.to_datetime(d.date); d=d[d.date<=END]',
                    'd.date=pd.to_datetime(d.date); d=d[(d.date>=_observers.warmup_start)&(d.date<=END)]', 'warmup cutoff')
        text = once(text, '                if ready and not unresolved and book.cash>0:',
                    '                if date>=START and ready and not unresolved and book.cash>0:', 'no warmup admissions')
        anchor = "            gday+=1; date=pd.Timestamp(date); ds=date.strftime('%Y-%m-%d')\n"
        reset = '''            if date==START:
                _observers.launch(book)
                book=Book(); native=Native(); ctl=ControlLDRC(); ca=CandidateA(); cb=CandidateB()
                shadow_eq=[]; damaged_hist=[]; stop_days=[]
                pending_native=1.; effective_native=1.
                pend={k:1. for k in pend}; eff={k:1. for k in eff}; navs={k:1. for k in navs}
'''
        text = once(text, anchor, anchor+reset, 'explicit financial and controller state launch')
    elif mode != 'full20':
        raise ValueError(mode)
    if class_hashes(text) != before:
        raise RuntimeError('Frozen Wealth Core or controller class changed')
    compile(text, '<SPY-IWM-fresh-experiment>', 'exec')
    return text


def build_source(output: Path, mode: str) -> str:
    from backtester import research_champion_corrected_classification as corrected
    return install(corrected.build_source(output), mode)


def run(output: Path, input_root: Path, mode: str) -> int:
    from backtester import research_champion_corrected_classification as corrected
    if os.environ.get('PIT_OFFICIAL_BACKTEST', '0') != '0':
        raise RuntimeError('Observer research may not request official certification')
    dataset = Path(os.environ['CANONICAL_PIT_DATASET'])
    canonical = json.loads((dataset/'manifest.json').read_text())
    if canonical['dataset_hash'] != DATASET_SHA:
        raise RuntimeError('Canonical dataset changed')
    pointer = verify_inputs(input_root)
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    source = build_source(output, mode)
    generated = output/'generated-observer-replay.py'
    generated.write_text(source)
    identity = dict(status=STATUS, mode=mode, source_sha=os.environ.get('GITHUB_SHA'),
                    runtime_sha=RUNTIME_SHA, profile_sha256=PROFILE_SHA, canonical_dataset_sha256=DATASET_SHA,
                    generated_source_sha256=digest(generated), frozen_class_ast_sha256=class_hashes(source),
                    observer_inputs=pointer, start=str(STARTS[mode].date()), end=str(END.date()),
                    new_strategy_state=True, prior_replay_input=False, economics='FROZEN_CORRECTED_CHAMPION')
    write_json(output/'observer-identity.json', identity)
    env = dict(os.environ, RESEARCH_REPLAY_MODE='fullpit', OBSERVER_INPUT_ROOT=str(input_root.resolve()),
               BEST_EFFORT_SECURITY_TYPES=str(corrected.base.DEFAULT_LEDGER.resolve()),
               BEST_EFFORT_CLASSIFICATION_SCENARIO='reviewed_18')
    code = subprocess.run([sys.executable, str(generated)], env=env).returncode
    if code:
        write_json(output/'observer-completion.json', identity | dict(completion='FAILED', exit_code=code))
        return code
    raw = pd.read_csv(output/'daily.csv')
    frame = raw.rename(columns={'shadow_equity':'research_wealth_core_equity',
                                'open_equity':'research_wealth_core_open_equity',
                                'control_allocation':'research_allocation','control_nav':'research_nav'})
    frame['certification_status'] = 'NOT_CERTIFIED'
    frame['experiment_mode'] = mode
    frame.to_csv(output/'daily.csv.gz', index=False, compression={'method':'gzip','mtime':0})
    summary = json.loads((output/'summary.json').read_text())
    summary.update(identity)
    summary['evidence_level'] = 'FROZEN_CANONICAL_PACKAGE_WITH_PROVISIONAL_CLASSIFICATIONS_AND_OBSERVERS'
    write_json(output/'summary.json', summary)
    write_json(output/'observer-completion.json', identity | dict(completion='COMPLETED'))
    checksums(output)
    return 0


def checksums(output: Path) -> None:
    paths = sorted(p for p in output.rglob('*') if p.is_file() and p.name != 'OBSERVER_SHA256SUMS.txt' and not p.name.endswith('.log'))
    (output/'OBSERVER_SHA256SUMS.txt').write_text(''.join(f'{digest(p)}  {p.relative_to(output)}\n' for p in paths))


def reference_check(output: Path, reference: Path) -> None:
    if digest(reference) != BASELINE_DAILY_SHA:
        raise RuntimeError('Prior comparison artifact hash differs from pinned reference')
    completion = json.loads((output/'observer-completion.json').read_text())
    if completion['completion'] != 'COMPLETED' or completion['mode'] != 'full20':
        raise RuntimeError('Reference comparison requires completed full20 replay')
    actual, expected = pd.read_csv(output/'daily.csv.gz'), pd.read_csv(reference)
    if actual.date.tolist() != expected.date.tolist():
        raise RuntimeError('Reference window mismatch')
    numeric = ['research_nav', 'research_allocation', 'research_wealth_core_equity',
               'research_wealth_core_open_equity', 'native_close_target', 'effective_native', 'spy_nav']
    gaps = {}
    for col in numeric:
        a, b = actual[col].to_numpy(float), expected[col].to_numpy(float)
        gaps[col] = float(np.max(np.abs(a-b)))
        if not np.allclose(a, b, rtol=1e-12, atol=1e-12, equal_nan=False):
            raise RuntimeError(f'Corrected reference numeric parity failed: {col}, {gaps[col]}')
    for col in ['research_selected_positions_sha256','research_ranking_sha256','research_ldrc_state']:
        if actual[col].tolist() != expected[col].tolist():
            raise RuntimeError(f'Corrected reference path parity failed: {col}')
    write_json(output/'corrected-reference-parity.json', dict(status='PASS', sessions=len(actual),
               numeric_gaps=gaps, exact_holdings_ranks_controller_state=True,
               comparison_only_after_fresh_replay=True, reference_sha256=BASELINE_DAILY_SHA))
    checksums(output)
    print('[REFERENCE_PARITY] PASS: fresh corrected control matches retained artifact', flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--input-root', type=Path)
    parser.add_argument('--mode', choices=tuple(STARTS), default='full20')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--check-reference', type=Path)
    args = parser.parse_args()
    if args.check_reference:
        reference_check(args.output, args.check_reference)
        return 0
    if args.self_test:
        source = build_source(args.output, args.mode)
        print(json.dumps(dict(status='ASSEMBLY_PASS', mode=args.mode,
                              sha256=hashlib.sha256(source.encode()).hexdigest(), classes=class_hashes(source))))
        return 0
    if args.input_root is None:
        parser.error('--input-root is required for a fresh replay')
    return run(args.output, args.input_root, args.mode)


if __name__ == '__main__':
    raise SystemExit(main())

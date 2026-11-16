"""Independent transition equation and canonical replay cross-check."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D
import math
from types import SimpleNamespace

import numpy as np


def number(value, *, positive=False) -> D:
    result = D(str(value))
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError('invalid finite economic value')
    return result


def allocation(value) -> D:
    result = number(value)
    if not D(0) <= result <= D(1):
        raise ValueError('exposure outside [0,1]')
    return result


@dataclass(frozen=True)
class Day:
    session: str
    core_gap: D
    core_day: D
    core_full: D
    bil_gap: D
    bil_day: D
    bil_full: D
    fixed: D | None = None
    fixed_net: D = D(1)
    fixed_gross: D = D(1)
    fixed_cost: D = D(1)
    fixed_turnover: D = D(0)

    def factors(self, old: D, new: D) -> tuple[D, D, D, D]:
        old, new = allocation(old), allocation(new)
        if self.fixed is not None:
            if new != self.fixed:
                raise ValueError('original first deployment is fixed')
            return self.fixed_net, self.fixed_gross, self.fixed_cost, self.fixed_turnover
        turnover = abs(new-old)
        cost = 1-D('.001')*turnover
        if old == new:
            gross = new*self.core_full+(1-new)*self.bil_full
        else:
            gross = (old*self.core_gap+(1-old)*self.bil_gap)*(new*self.core_day+(1-new)*self.bil_day)
        return gross*cost, gross, cost, turnover

    def matrix(self, grid: tuple[D, ...]) -> np.ndarray:
        a = np.asarray(grid, dtype=float)
        if self.fixed is not None:
            result = np.full((len(a), len(a)), -np.inf)
            result[:, grid.index(self.fixed)] = math.log(float(self.fixed_net))
            return result
        gross = ((a*float(self.core_gap)+(1-a)*float(self.bil_gap))[:, None]
                 * (a*float(self.core_day)+(1-a)*float(self.bil_day))[None, :])
        np.fill_diagonal(gross, a*float(self.core_full)+(1-a)*float(self.bil_full))
        net = gross*(1-.001*np.abs(a[:, None]-a[None, :]))
        if np.any(net <= 0) or not np.isfinite(net).all():
            raise ValueError('nonpositive transition factor')
        return np.log(net)


def tape(rows: list[dict], *, canonical=True) -> tuple[list[Day], D, list[D]]:
    days, actual = [], []
    for previous, row in zip(rows, rows[1:]):
        p, e = previous['economics'], row['economics']
        v = row['valuation']
        if v['blocked'] or v['open_unresolved_security_ids'] or v['resolved_equity'] is None:
            raise ValueError('unresolved Core valuation')
        if e['bil_previous_session'] != previous['session'] or e['last_session'] != row['session']:
            raise ValueError('return period mismatch')
        new = allocation(e['held_allocation'])
        if new != allocation(p['pending_allocation']):
            raise ValueError('decision-to-open alignment changed')
        co = number(e['parent_core_open_equity'], positive=True)
        cc = number(e['parent_core_close_equity'], positive=True)
        cp = number(p['parent_core_close_equity'], positive=True)
        bo = number(e['bil_open_adjusted'], positive=True)
        bc = number(e['bil_close_adjusted'], positive=True)
        bp = number(e['bil_previous_close_adjusted_current_publication'], positive=True)
        fixed = new if e['initial_deployment'] else None
        if (p['held_allocation'] is None) != (fixed is not None) or (fixed is not None and days):
            raise ValueError('unexpected first deployment boundary')
        day = Day(row['session'], co/cp, cc/co, cc/cp, bo/bp, bc/bo, bc/bp,
                  fixed, number(e['net_factor'], positive=True), number(e['gross_factor'], positive=True),
                  number(e['transaction_cost_factor'], positive=True), number(e['turnover']))
        old = new if fixed is not None else allocation(p['held_allocation'])
        factors = day.factors(old, new)
        for value, key in zip(factors, ('net_factor', 'gross_factor', 'transaction_cost_factor', 'turnover')):
            if abs(value-number(e[key])) > D('1e-24'):
                raise ValueError('actual accounting equation differs: '+key)
        if abs(number(row['strategy']['nav'])/number(previous['strategy']['nav'])-factors[0]) > D('1e-24'):
            raise ValueError('recorded strategy NAV differs from transition')
        if canonical and fixed is None:
            canonical_check(previous, row, factors)
        days.append(day)
        actual.append(new)
    initial = rows[0]['economics']['held_allocation']
    return days, allocation(initial) if initial is not None else actual[0], actual


def canonical_check(previous: dict, row: dict, factors: tuple[D, D, D, D]) -> None:
    from sentinel.shadow_observation import ShadowObserver
    class Account:
        _allocation = staticmethod(ShadowObserver._allocation)
        _parent_economics = ShadowObserver._parent_economics
        starting_cash = '50000'
        warmup_input_identity = {}
    state = SimpleNamespace(last_processed_session=row['session'],
        shadow_nav_history=[row['core']['nav']], last_decision=row['decision'],
        last_evidence=dict(wealth_core=row['valuation'], observation=dict(shadow_nav=row['core']['nav'])))
    result = ShadowObserver._advance_strategy_economics(Account(), previous=previous['economics'],
        state=state, strategy_prices=row['economics']['strategy_prices'])
    for value, key in zip(factors, ('net_factor', 'gross_factor', 'transaction_cost_factor', 'turnover')):
        if abs(value-D(result[key])) > D('1e-24'):
            raise ValueError('canonical accountant differs: '+key)


def make_grid(initial: D, actual: list[D]) -> tuple[D, ...]:
    grid = (D(0), D('.55'), D(1))
    if any(allocation(x) not in grid for x in (initial, *actual)):
        raise ValueError('comparison permits only 0%, 55%, and 100% exposure')
    return grid


def performance(values: list[D], sessions: list[str]) -> dict:
    peak, maxdd, peak_day, worst_peak, worst_trough = values[0], D(0), sessions[0], sessions[0], sessions[0]
    drawdowns = []
    for session, value in zip(sessions, values):
        if value > peak:
            peak, peak_day = value, session
        dd = 1-value/peak
        if dd > maxdd:
            maxdd, worst_peak, worst_trough = dd, peak_day, session
        drawdowns.append(float(dd))
    multiple = values[-1]/values[0]
    elapsed = (date.fromisoformat(sessions[-1])-date.fromisoformat(sessions[0])).days
    return dict(cagr=math.expm1(math.log(float(multiple))*365.2425/elapsed),
                multiple=str(multiple), maxdd=float(maxdd), peak=worst_peak, trough=worst_trough,
                drawdown=drawdowns)


def replay(days: list[Day], initial: D, path: list[D], start: str, cap: float | None = None) -> dict:
    if len(days) != len(path):
        raise ValueError('incomplete exposure path')
    nav, gross, costs, turns, old = [D(1)], [], [], [], initial
    for day, new in zip(days, path):
        net, g, c, t = day.factors(old, new)
        if net <= 0:
            raise ValueError('nonpositive replay wealth')
        nav.append(nav[-1]*net)
        gross.append(math.log(float(g)))
        costs.append(math.log(float(c)))
        turns.append(float(t))
        old = new
    metrics = performance(nav, [start, *(d.session for d in days)])
    if cap is not None and metrics['maxdd'] > cap+1e-10:
        raise ValueError('independent replay exceeds requested drawdown cap')
    return dict(**metrics, nav=[str(x) for x in nav], exposure=[float(x) for x in path],
                gross_log=gross, cost_log=costs, turnover=sum(turns),
                switches=sum(a != b for a,b in zip([initial, *path[:-1]], path)),
                mean_exposure=float(sum(path)/len(path)))

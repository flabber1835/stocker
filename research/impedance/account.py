"""Synthetic next-open account; production projection, deterministic local fills."""
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

from sentinel.execution.projection import desired_basket, project
from stock_strategy_shared.wealth_core.state import PortfolioState
from stock_strategy_shared.wealth_core.ledger import Ledger

BILL = 'SYNTHETIC:BILL'
COST = Decimal('.001')


def dec(value):
    return Decimal(str(value))


@dataclass
class Account:
    cash: Decimal = Decimal('100000')
    shares: dict = field(default_factory=dict)
    fees: Decimal = Decimal(0)
    turnover: Decimal = Decimal(0)

    def nav(self, marks):
        return self.cash + sum((q * marks[s] for s, q in self.shares.items()), Decimal(0))

    def split(self, bars):
        for bar in bars:
            if bar.security_id in self.shares:
                self.shares[bar.security_id] *= dec(bar.split_ratio)

    def rebalance(self, core, marks, target):
        book = PortfolioState.from_dict(core.wealth_core)
        values = {e.security_id: dec(e.current_shares)*marks[e.security_id] for e in book.episodes.values()}
        denominator = dec(book.cash) + dec(Ledger.from_dict(core.ledger).receivable_total()) + sum(values.values(), Decimal(0))
        opening_nav = self.nav(marks)
        projection = project(shadow_weights=values, weight_denominator=denominator,
            exposure=dec(target), nav=opening_nav, marks=marks,
            defensive_security=BILL, defensive_weight=1-dec(target))
        desired = desired_basket(projection)
        assert not projection.unpriced
        trades = []
        for sid in sorted(set(self.shares) | set(desired)):
            reduction = self.shares.get(sid, Decimal(0))-desired.get(sid, Decimal(0))
            if reduction > 0:
                amount = reduction*marks[sid]
                self.cash += amount*(1-COST)
                self.shares[sid] -= reduction
                self.fees += amount*COST
                self.turnover += amount
                trades.append([sid, str(-reduction), str(marks[sid])])
        for sid in sorted(desired):
            needed = desired[sid]-self.shares.get(sid, Decimal(0))
            if needed <= 0:
                continue
            affordable = Fraction(self.cash) // (Fraction(marks[sid])*(1+Fraction(COST)))
            quantity = min(needed, Decimal(affordable))
            if quantity > 0:
                amount = quantity*marks[sid]
                self.cash -= amount*(1+COST)
                self.shares[sid] = self.shares.get(sid, Decimal(0))+quantity
                self.fees += amount*COST
                self.turnover += amount
                trades.append([sid, str(quantity), str(marks[sid])])
        self.shares = {s:q for s,q in self.shares.items() if q}
        assert self.cash >= 0 and all(q >= 0 and q == q.to_integral_value() for q in self.shares.values())
        fee_this_open = opening_nav-self.nav(marks)
        expected = sum((abs(dec(q))*dec(p)*COST for _,q,p in trades), Decimal(0))
        assert abs(fee_this_open-expected) < Decimal('1e-18')
        return dict(opening_nav=float(opening_nav), fees=float(expected), trades=trades,
                    target=target, stock_value=float(sum(q*marks[s] for s,q in self.shares.items() if s != BILL)))

    def snapshot(self):
        return dict(cash=str(self.cash), shares={s:str(q) for s,q in sorted(self.shares.items())},
                    fees=str(self.fees), turnover=str(self.turnover))

    @classmethod
    def restore(cls, row):
        return cls(dec(row['cash']), {s:dec(q) for s,q in row['shares'].items()},
                   dec(row['fees']), dec(row['turnover']))

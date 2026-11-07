"""Binary64 interval proof primitives; no market, account or strategy imports."""
from dataclasses import dataclass
from fractions import Fraction
import math
import operator
import sys


def require(value, code):
    if not value:
        raise ValueError('REFUSED_UNCERTAINTY_' + code)


@dataclass(frozen=True)
class Interval:
    lo: float
    hi: float

    def __post_init__(self):
        require(type(self.lo) is float and type(self.hi) is float
                and math.isfinite(self.lo) and math.isfinite(self.hi)
                and self.lo <= self.hi, 'FINITE_ORDERED_INTERVAL')

    @classmethod
    def point(cls, value):
        return cls(float(value), float(value))

    def add(self, other):
        return Interval(self.lo + other.lo, self.hi + other.hi)

    def sub(self, other):
        return Interval(self.lo - other.hi, self.hi - other.lo)

    def mul(self, other):
        values = [x * y for x in (self.lo, self.hi) for y in (other.lo, other.hi)]
        return Interval(min(values), max(values))

    def div(self, other):
        require(other.lo > 0 or other.hi < 0, 'DIVISOR_EXCLUDES_ZERO')
        values = [x / y for x in (self.lo, self.hi) for y in (other.lo, other.hi)]
        return Interval(min(values), max(values))

    def contains(self, value):
        return math.isfinite(value) and self.lo <= value <= self.hi

    def normal_positive(self):
        # Keep clear of the normal/subnormal boundary, where relative error
        # bounds are insufficient. Interval endpoint operations above follow
        # the same rounded binary64 operations as the witness.
        require(self.lo >= 2 * sys.float_info.min and self.hi <= sys.float_info.max / 2,
                'POSITIVE_NORMAL_SAFE_RANGE')
        return self

    def pair(self):
        return [self.lo, self.hi]


def fraction_bound(value, *, lower):
    """Outward binary64 enclosure of an exact rational real endpoint."""
    result = float(value)
    require(math.isfinite(result), 'RATIONAL_ENDPOINT_FINITE')
    exact = Fraction.from_float(result)
    if lower and exact > value:
        result = math.nextafter(result, -math.inf)
    if not lower and exact < value:
        result = math.nextafter(result, math.inf)
    return result


def growth(returns):
    """Match sum(returns)/len(returns), followed by 1+change, exactly."""
    total = Interval.point(0.)
    for value in returns:
        total = total.add(value)
    mean = total.div(Interval.point(len(returns))) if returns else total
    return Interval.point(1.).add(mean).normal_positive()


class RollingWitnessBounds:
    """Cancel a common unknown scale without discarding floating-point error."""
    def __init__(self, prefix):
        require(1 <= len(prefix) <= 41, 'PREFIX_LENGTH')
        self.prefix = [float(x) for x in prefix]
        for value in self.prefix:
            Interval.point(value).normal_positive()
        self.absolute = Interval.point(self.prefix[-1])
        self.factors = []
        self.steps = 0

    def advance(self, factor, observed_nav):
        factor.normal_positive()
        self.absolute = self.absolute.mul(factor).normal_positive()
        require(self.absolute.contains(observed_nav), 'ACTUAL_NAV_WITHIN_BOUNDS')
        self.factors = (self.factors + [factor])[-40:]
        self.steps += 1

    def period(self, count):
        require(type(count) is int and count in (20, 40), 'DECLARED_RETURN_HORIZON')
        if len(self.prefix) - 1 + self.steps < count:
            return None
        n = min(count, self.steps)
        lo = hi = Fraction(1)
        if count > self.steps:
            numerator = Fraction.from_float(self.prefix[-1])
            denominator = Fraction.from_float(self.prefix[-(count - self.steps) - 1])
            lo = hi = numerator / denominator
        for factor in self.factors[-n:]:
            lo *= Fraction.from_float(factor.lo)
            hi *= Fraction.from_float(factor.hi)
        # n normal NAV multiplications and one normal final division. The
        # denominator's prior unknown scale cancels before bounding rounding.
        u = Fraction(1, 2 ** 53)
        lo *= (1 - u) ** (n + 1)
        hi *= (1 + u) ** (n + 1)
        ratio = Interval(fraction_bound(lo, lower=True), fraction_bound(hi, lower=False))
        ratio.normal_positive()
        return ratio.sub(Interval.point(1.))

    def snapshot(self):
        return dict(prefix=self.prefix, absolute=self.absolute.pair(),
                    factors=[x.pair() for x in self.factors], steps=self.steps)

    @classmethod
    def restore(cls, value):
        require(set(value) == {'prefix', 'absolute', 'factors', 'steps'}, 'SNAPSHOT_FIELDS')
        obj = cls(value['prefix'])
        require(type(value['steps']) is int and value['steps'] >= 0
                and len(value['factors']) == min(40, value['steps']), 'SNAPSHOT_STEPS')
        obj.absolute = Interval(*value['absolute']).normal_positive()
        obj.factors = [Interval(*v).normal_positive() for v in value['factors']]
        obj.steps = value['steps']
        return obj


class CertifiedScalar(float):
    """Fail closed when an actually executed comparison is not invariant."""
    def __new__(cls, value, interval, evidence):
        require(interval.contains(value), 'REPRESENTATIVE_WITHIN_RETURN_BOUNDS')
        obj = float.__new__(cls, value)
        obj.interval, obj.evidence = interval, evidence
        return obj

    def compare(self, other, relation):
        require(type(other) in (float, int) and math.isfinite(other), 'EXACT_COMPARISON_THRESHOLD')
        fn = {'gt': operator.gt, 'ge': operator.ge, 'lt': operator.lt, 'le': operator.le}[relation]
        a, b = fn(self.interval.lo, other), fn(self.interval.hi, other)
        require(a == b, 'AMBIGUOUS_CONTROLLER_COMPARISON_' + relation)
        self.evidence.append(dict(interval=self.interval.pair(), relation=relation,
                                  threshold=other, result=a))
        return a

    def __gt__(self, other): return self.compare(other, 'gt')
    def __ge__(self, other): return self.compare(other, 'ge')
    def __lt__(self, other): return self.compare(other, 'lt')
    def __le__(self, other): return self.compare(other, 'le')

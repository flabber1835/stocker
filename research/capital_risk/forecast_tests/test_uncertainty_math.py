"""Synthetic proof/falsifier tests; never import or replay historical accounts."""
from fractions import Fraction
import math
import random

import pytest

from system_campaign_uncertainty_math import (
    CertifiedScalar, Interval, RollingWitnessBounds, fraction_bound, growth,
)


def test_rational_bounds_enclose_real_value():
    for value in (Fraction(1, 3), Fraction(-1, 3), Fraction(1, 10), Fraction(2 ** 70 + 1, 7)):
        assert Fraction.from_float(fraction_bound(value, lower=True)) <= value
        assert Fraction.from_float(fraction_bound(value, lower=False)) >= value


def test_binary64_interval_operations_include_interior_values():
    a, b = Interval(-.7, 1.3), Interval(.2, 2.7)
    for x in (-.7, -.12, 0., .33, 1.3):
        for y in (.2, .3, 1.11, 2.7):
            for actual, bound in ((x + y, a.add(b)), (x - y, a.sub(b)),
                                  (x * y, a.mul(b)), (x / y, a.div(b))):
                assert bound.contains(actual)


def test_mean_matches_python_sum_and_operation_order():
    values = [1e16, -1e16, .17]
    result = growth([Interval.point(x) for x in values])
    assert result.lo == result.hi == 1 + sum(values) / len(values)


def test_empty_witness_growth_is_one():
    assert growth([]) == Interval.point(1.)


def test_rolling_bounds_cover_interior_worlds_and_scale_cancellation():
    rng = random.Random(118)
    prefix = [1.]
    for _ in range(40):
        prefix.append(prefix[-1] * (1 + rng.uniform(-.025, .027)))
    worlds = [list(prefix) for _ in range(101)]
    proof = RollingWitnessBounds(prefix)
    widths = []
    for day in range(140):
        fixed = 1 + rng.uniform(-.025, .027)
        factor = Interval(.994, 1.008) if day == 0 else Interval.point(fixed)
        for j, navs in enumerate(worlds):
            actual = .994 + .014 * j / 100 if day == 0 else fixed
            # Interior values may round slightly above a decimal-built upper
            # endpoint, so use exactly the endpoint in that one world.
            if day == 0 and j == 100: actual = factor.hi
            navs.append(navs[-1] * actual)
        proof.advance(factor, worlds[0][-1])
        for n in (20, 40):
            bound = proof.period(n)
            for navs in worlds:
                assert bound.contains(navs[-1] / navs[-n - 1] - 1.)
        widths.append(proof.period(40).hi - proof.period(40).lo)
        if day in (0, 21, 44):
            proof = RollingWitnessBounds.restore(proof.snapshot())
    assert widths[0] > .01
    assert widths[40] < 1e-12
    assert widths[-1] < 1e-12


def test_short_prefix_preserves_availability():
    proof = RollingWitnessBounds([1., 1.01])
    proof.advance(Interval.point(1.001), 1.01 * 1.001)
    assert proof.period(20) is proof.period(40) is None


@pytest.mark.parametrize('interval', [Interval(0., 1.), Interval(1e-310, 1e-309)])
def test_subnormal_or_zero_normal_product_refuses(interval):
    with pytest.raises(ValueError, match='NORMAL'):
        interval.normal_positive()


@pytest.mark.parametrize('op,threshold,expected', [('gt', 0., True), ('ge', .1, True),
                                                  ('lt', .4, True), ('le', .3, True),
                                                  ('gt', .4, False), ('le', 0., False)])
def test_actual_comparisons_are_constant(op, threshold, expected):
    rows = []
    value = CertifiedScalar(.2, Interval(.1, .3), rows)
    assert value.compare(threshold, op) is expected
    assert rows == [dict(interval=[.1, .3], relation=op, threshold=threshold, result=expected)]


def test_boundary_inclusion_is_not_endpoint_only_approval():
    value = CertifiedScalar(0., Interval(0., .1), [])
    with pytest.raises(ValueError, match='AMBIGUOUS'):
        value > 0.
    assert value >= 0.
    with pytest.raises(ValueError, match='AMBIGUOUS'):
        value >= .1


def test_actual_comparison_guard_removal_falsifier():
    import inspect
    original = inspect.getsource(CertifiedScalar.compare)
    broken = original.replace("        require(a == b, 'AMBIGUOUS_CONTROLLER_COMPARISON_' + relation)\n", '')
    assert broken != original
    namespace = {}
    import textwrap
    exec(textwrap.dedent(broken), CertifiedScalar.compare.__globals__, namespace)
    with pytest.raises(ValueError, match='AMBIGUOUS'):
        CertifiedScalar(.05, Interval(-.1, .1), []).compare(0., 'gt')
    assert namespace['compare'](CertifiedScalar(.05, Interval(-.1, .1), []), 0., 'gt') is False


def test_invalid_representative_refuses():
    with pytest.raises(ValueError, match='REPRESENTATIVE'):
        CertifiedScalar(2., Interval(0., 1.), [])


def test_actual_nav_omission_guard_removal_falsifier():
    import inspect
    import textwrap
    original = inspect.getsource(RollingWitnessBounds.advance)
    broken = original.replace("        require(self.absolute.contains(observed_nav), 'ACTUAL_NAV_WITHIN_BOUNDS')\n", '')
    assert broken != original
    namespace = {}
    exec(textwrap.dedent(broken), RollingWitnessBounds.advance.__globals__, namespace)
    with pytest.raises(ValueError, match='ACTUAL_NAV'):
        RollingWitnessBounds([1.]).advance(Interval.point(1.), 2.)
    namespace['advance'](RollingWitnessBounds([1.]), Interval.point(1.), 2.)


def test_canonical_call_adapter_uses_same_discrete_result_with_intercepted_comparison():
    from system_campaign_uncertainty_gate import certified_recovery
    calls = []
    def synthetic(**kwargs):
        calls.append(type(kwargs['recent_r20']))
        return {'flag': kwargs['recent_r20'] > 0., 'counter': 8}, {'target': .55}
    actual, checks = certified_recovery(synthetic, {'recent_r20': .2},
                                      {'recent_r20': Interval(.1, .3)})
    assert actual == ({'flag': True, 'counter': 8}, {'target': .55})
    assert len(checks) == 1 and calls == [CertifiedScalar, float]


def test_adapter_refuses_mutated_nonfinancial_counter_too():
    from system_campaign_uncertainty_gate import certified_recovery
    def synthetic(**kwargs):
        kwargs['recent_r20'] > 0.
        return {'counter': int(type(kwargs['recent_r20']) is float)}
    with pytest.raises(ValueError, match='COMPLETE_RECOVERY_EQUALITY'):
        certified_recovery(synthetic, {'recent_r20': .2}, {'recent_r20': Interval(.1, .3)})


def test_gate_has_no_financial_advance_entrypoint():
    import ast
    from pathlib import Path
    import system_campaign_uncertainty_gate as gate
    tree = ast.parse(Path(gate.__file__).read_bytes())
    assert not any(isinstance(n, ast.Attribute) and n.attr in ('advance', 'main')
                   and isinstance(n.value, ast.Name) and n.value.id in ('runtime', 'backtest', 'kernel')
                   for n in ast.walk(tree))

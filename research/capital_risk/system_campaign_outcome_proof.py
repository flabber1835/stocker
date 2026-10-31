"""Bounded complete-outcome proof; no controller, market or account imports."""
from copy import deepcopy
import hashlib
import json
import math

from system_campaign_uncertainty_math import require


def commitment(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def exact_equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(exact_equal(left[k], right[k]) for k in left)
    if isinstance(left, (tuple, list)):
        return len(left) == len(right) and all(exact_equal(a, b) for a, b in zip(left, right))
    if type(left) is float:
        return math.isfinite(left) and math.isfinite(right) and left.hex() == right.hex()
    require(left is None or type(left) in (bool, int, str), 'OUTCOME_SUPPORTED_RESULT_TYPES')
    return left == right


def same_result(left, right):
    return exact_equal(left, right) and commitment(left) == commitment(right)


class SplitRequired(Exception):
    """An explicit unexamined Boolean child, never an accepted result."""


class Trace:
    def __init__(self, choices):
        self.choices = choices
        self.consumed = 0
        self.comparisons = []

    def compare(self, scalar, threshold, relation):
        require(type(threshold) in (float, int) and math.isfinite(threshold),
                'OUTCOME_POINT_FINITE_COMPARISON_THRESHOLD')
        fn = {'gt': lambda x: x > threshold, 'ge': lambda x: x >= threshold,
              'lt': lambda x: x < threshold, 'le': lambda x: x <= threshold}[relation]
        lower, upper = fn(scalar.interval.lo), fn(scalar.interval.hi)
        invariant = lower == upper
        if invariant:
            result = lower
        else:
            if self.consumed == len(self.choices):
                raise SplitRequired()
            result = self.choices[self.consumed]
            require(type(result) is bool, 'OUTCOME_EXACT_BOOLEAN_BRANCH')
            self.consumed += 1
        self.comparisons.append(dict(field=scalar.field, interval=scalar.interval.pair(),
            relation=relation, threshold=threshold, comparison_invariant=invariant, result=result))
        return result


class BoundedScalar(float):
    def __new__(cls, value, interval, trace, field):
        require(type(value) is float and interval.contains(value), 'OUTCOME_REPRESENTATIVE_IN_BOUNDS')
        result = float.__new__(cls, value)
        result.interval, result.trace, result.field = interval, trace, field
        return result

    def __gt__(self, other): return self.trace.compare(self, other, 'gt')
    def __ge__(self, other): return self.trace.compare(self, other, 'ge')
    def __lt__(self, other): return self.trace.compare(self, other, 'lt')
    def __le__(self, other): return self.trace.compare(self, other, 'le')

    def unsupported(self, *args):
        require(False, 'OUTCOME_UNSUPPORTED_BOUNDED_SCALAR_OPERATION')

    __bool__ = __float__ = __int__ = __index__ = unsupported
    __add__ = __radd__ = __sub__ = __rsub__ = unsupported
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = unsupported
    __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = unsupported
    __pow__ = __rpow__ = __neg__ = __pos__ = __abs__ = unsupported
    __round__ = __ceil__ = __floor__ = __trunc__ = unsupported
    __eq__ = __ne__ = unsupported


def no_scalar_escape(value):
    require(not isinstance(value, BoundedScalar), 'OUTCOME_BOUNDED_SCALAR_ESCAPED_RESULT')
    if isinstance(value, dict):
        for key, child in value.items():
            no_scalar_escape(key)
            no_scalar_escape(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            no_scalar_escape(child)


def certified_recovery(function, kwargs, bounds, *, max_leaves=64, max_nodes=127, max_depth=16):
    """Explore an overapproximation; admit only one complete canonical result."""
    require(type(max_leaves) is int and 1 <= max_leaves <= 64
            and type(max_nodes) is int and 1 <= max_nodes <= 127
            and type(max_depth) is int and 0 <= max_depth <= 16, 'OUTCOME_EXPLICIT_BRANCH_BUDGET')
    require(set(bounds) == {'recent_r20', 'recent_r40'}, 'OUTCOME_EXACT_TWO_DECLARED_RETURNS')
    for name, interval in bounds.items():
        require((kwargs[name] is None) == (interval is None), 'OUTCOME_RETURN_AVAILABILITY')
        if interval is not None:
            require(type(kwargs[name]) is float and interval.contains(kwargs[name]),
                    'OUTCOME_RETURN_IN_DECLARED_BOUNDS')
    original_input = commitment(kwargs)

    def call(values):
        try:
            return function(**values)
        finally:
            require(commitment(kwargs) == original_input, 'OUTCOME_ORIGINAL_INPUT_NOT_MUTATED')

    ordinary = call(deepcopy(kwargs))
    no_scalar_escape(ordinary)
    result_hash = commitment(ordinary)
    pending, leaves, nodes = [()], [], 0
    while pending:
        choices = pending.pop()
        require(len(choices) <= max_depth and nodes < max_nodes, 'OUTCOME_BRANCH_EXPLORATION_LIMIT')
        nodes += 1
        trace = Trace(choices)
        supplied = deepcopy(kwargs)
        for name, interval in bounds.items():
            if interval is not None:
                supplied[name] = BoundedScalar(kwargs[name], interval, trace, name)
        try:
            result = call(supplied)
        except SplitRequired:
            require(trace.consumed == len(choices), 'OUTCOME_EXACT_UNEXPLORED_BRANCH_PREFIX')
            pending.extend((choices + (True,), choices + (False,)))
            continue
        require(trace.consumed == len(choices), 'OUTCOME_ALL_DECLARED_BRANCH_CHOICES_CONSUMED')
        no_scalar_escape(result)
        require(same_result(ordinary, result), 'OUTCOME_COMPLETE_CANONICAL_RECOVERY_DIFFERS')
        leaves.append(dict(choices=list(choices), comparisons=trace.comparisons,
                           complete_result_sha256=commitment(result)))
        require(len(leaves) <= max_leaves, 'OUTCOME_COMPLETE_LEAF_LIMIT')
    require(leaves and not pending, 'OUTCOME_ALL_LEAVES_COMPLETED')
    proof = dict(schema='research.complete-controller-outcome-proof/1',
        all_complete_results_equal=True, ordinary_result_sha256=result_hash,
        input_sha256=original_input, nodes=nodes, leaves=leaves,
        all_individual_comparisons_invariant=all(c['comparison_invariant']
            for leaf in leaves for c in leaf['comparisons']),
        jointly_feasible_paths_overapproximated=True, point_valuation_selected=False)
    return ordinary, proof

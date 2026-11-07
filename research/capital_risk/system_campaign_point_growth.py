"""Proof-only point-return factors using the immutable CPython3.12 witness order."""
from contextlib import contextmanager
import hashlib
import platform
import sys

from system_campaign_uncertainty_math import Interval, require


def point_growth(returns):
    require(platform.python_implementation() == 'CPython'
            and sys.version_info[:2] == (3, 12), 'POINT_GROWTH_SAME_CPYTHON312')
    values = tuple(returns)
    require(all(isinstance(v, Interval) and v.lo == v.hi for v in values),
            'POINT_GROWTH_POINT_INPUTS_ONLY')
    points = [v.lo for v in values]
    change = sum(points) / len(points) if points else 0.
    return Interval.point(1 + change).normal_positive()


@contextmanager
def point_growth_scope(witness_source, expected_sha256):
    """Compose proof functions only; canonical witness and NAV guards stay intact."""
    require(hashlib.sha256(witness_source).hexdigest() == expected_sha256,
            'POINT_GROWTH_EXACT_WITNESS_SOURCE')
    point_growth(())  # Refuse an interpreter mismatch before installing anything.
    import system_campaign_uncertainty_context as context
    import system_campaign_financial_branches as branches
    original_context, original_review = context.growth, branches.growth
    context.growth = branches.growth = point_growth
    try:
        yield
    finally:
        context.growth, branches.growth = original_context, original_review

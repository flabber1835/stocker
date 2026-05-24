"""
Property-based tests for StrategyConfig / FactorWeights schema validation.

Properties under test:
  W1. Any six non-negative floats summing to exactly 1.0 (within 1e-6) always produce a valid FactorWeights.
  W2. Any six non-negative floats summing to a value outside [1-1e-6, 1+1e-6] always raise ValidationError.
  W3. FactorWeights with liquidity=0.0 default and the other 5 summing to 1.0 always validates.
  W4. Any component outside [0, 1] always raises ValidationError regardless of sum.
  W5. FactorWeights ordering doesn't matter — same values, different field assignment → same validation result.
"""
import math

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

import os
import sys

_SHARED_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared")
)
if _SHARED_PATH not in sys.path:
    sys.path.insert(0, _SHARED_PATH)

from stock_strategy_shared.schemas.strategy import FactorWeights


# ── helpers ───────────────────────────────────────────────────────────────────

def _factor_weights(**kwargs) -> dict:
    """Build a FactorWeights dict with defaults for missing keys."""
    base = {"momentum": 0.2, "quality": 0.2, "value": 0.2,
            "growth": 0.2, "low_volatility": 0.2, "liquidity": 0.0}
    base.update(kwargs)
    return base


# Strategy: generate 5 independent weights that sum to ≤ 1.0, sixth = 1 - rest.
@st.composite
def _valid_six_weights(draw):
    """Draw 6 non-negative weights that sum to exactly 1.0."""
    # Draw 5 values that sum to ≤ 1.0
    w = draw(st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=5, max_size=5,
    ))
    total = sum(w)
    if total > 1.0:
        # normalise
        w = [v / total for v in w]
        total = sum(w)
    sixth = 1.0 - total
    if sixth < 0.0:
        sixth = 0.0
        w = [v / total for v in w]
        sixth = max(0.0, 1.0 - sum(w))
    return w + [sixth]


# ── W1: summing to 1.0 always validates ──────────────────────────────────────

@given(weights=_valid_six_weights())
@settings(max_examples=200)
def test_weights_summing_to_one_always_valid(weights):
    """W1: Any 6 non-negative weights summing to 1.0 must produce a valid FactorWeights."""
    m, q, v, g, lv, liq = weights
    total = m + q + v + g + lv + liq
    assume(abs(total - 1.0) <= 1e-6)
    assume(all(w >= 0.0 for w in weights))
    try:
        fw = FactorWeights(
            momentum=m, quality=q, value=v, growth=g,
            low_volatility=lv, liquidity=liq,
        )
    except ValidationError as exc:
        pytest.fail(f"Valid weights (sum={total:.8f}) raised ValidationError: {exc}")


# ── W2: sum outside tolerance always fails ────────────────────────────────────

@given(
    weights=st.lists(
        st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
        min_size=6, max_size=6,
    ),
    delta=st.floats(min_value=1e-5, max_value=2.0, allow_nan=False, allow_infinity=False),
    direction=st.booleans(),
)
@settings(max_examples=200)
def test_weights_not_summing_to_one_always_invalid(weights, delta, direction):
    """W2: Weights with sum outside [1±1e-6] must always raise ValidationError."""
    # Normalise to [0, 1] each, then offset the sum deliberately
    total = sum(weights) or 1.0
    normed = [w / total for w in weights]
    # Now shift to make sum != 1
    shift = delta if direction else -delta
    normed[0] = max(0.0, normed[0] + shift)
    new_total = sum(normed)
    assume(abs(new_total - 1.0) > 1e-6)
    assume(all(0.0 <= w <= 1.0 for w in normed))
    m, q, v, g, lv, liq = normed
    with pytest.raises(ValidationError):
        FactorWeights(momentum=m, quality=q, value=v, growth=g,
                      low_volatility=lv, liquidity=liq)


# ── W3: liquidity=0.0 default with remaining 5 summing to 1.0 ────────────────

@given(
    weights=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=5, max_size=5,
    )
)
@settings(max_examples=200)
def test_five_weights_sum_to_one_with_zero_liquidity(weights):
    """W3: When liquidity=0.0 and 5 factors sum to 1.0, FactorWeights is valid."""
    total = sum(weights)
    if total == 0.0:
        return
    normed = [w / total for w in weights]
    total_normed = sum(normed)
    assume(abs(total_normed - 1.0) <= 1e-6)
    assume(all(w >= 0.0 for w in normed))
    m, q, v, g, lv = normed
    try:
        fw = FactorWeights(momentum=m, quality=q, value=v,
                           growth=g, low_volatility=lv, liquidity=0.0)
    except ValidationError as exc:
        pytest.fail(f"5 valid weights + liquidity=0 raised ValidationError: {exc}")
    assert fw.liquidity == 0.0


# ── W4: negative component always fails regardless of sum ────────────────────

@given(
    neg_val=st.floats(min_value=-100.0, max_value=-1e-9, allow_nan=False, allow_infinity=False),
    field=st.sampled_from(["momentum", "quality", "value", "growth", "low_volatility", "liquidity"]),
)
@settings(max_examples=100)
def test_negative_component_always_invalid(neg_val, field):
    """W4: Any negative weight value must fail validation (ge=0 constraint)."""
    payload = _factor_weights(**{field: neg_val})
    with pytest.raises(ValidationError):
        FactorWeights(**payload)


# ── W4b: component > 1 always fails ──────────────────────────────────────────

@given(
    val=st.floats(min_value=1.0001, max_value=100.0, allow_nan=False, allow_infinity=False),
    field=st.sampled_from(["momentum", "quality", "value", "growth", "low_volatility", "liquidity"]),
)
@settings(max_examples=100)
def test_component_over_one_always_invalid(val, field):
    """W4b: Any weight > 1 must fail validation (le=1 constraint)."""
    payload = _factor_weights(**{field: val})
    with pytest.raises(ValidationError):
        FactorWeights(**payload)


# ── W5: permutation invariance of validation ──────────────────────────────────

@given(weights=_valid_six_weights())
@settings(max_examples=100)
def test_weight_permutation_same_validation_result(weights):
    """W5: Shuffling the same valid values across fields produces the same validation result.

    FactorWeights validates on sum, so any permutation of a valid tuple is also valid.
    """
    total = sum(weights)
    assume(abs(total - 1.0) <= 1e-6)
    assume(all(w >= 0.0 for w in weights))
    fields = ["momentum", "quality", "value", "growth", "low_volatility", "liquidity"]
    # Original order
    fw1 = FactorWeights(**dict(zip(fields, weights)))
    # Reversed order
    fw2 = FactorWeights(**dict(zip(fields, reversed(weights))))
    assert fw1 is not None and fw2 is not None

"""Factor registry = single source of truth for the generic engine's factors.

Guards against the drift that the registry exists to prevent: the FactorWeights
schema fields, rank.FACTORS, and the registry must all agree, and the
min_non_null_factors bound must track the factor count (the old le=11 was stale at
12 factors).
"""
import os
import sys

from stock_strategy_shared.factor_registry import (
    FACTOR_NAMES, FACTOR_COUNT, FACTOR_LABELS, FACTOR_REGISTRY, DISPLAY_INDICATORS,
)
from stock_strategy_shared.schemas.strategy import FactorWeights, StrategyConfig


def test_registry_is_internally_consistent():
    # No magic count: adding a factor must NOT require editing this test. Assert the
    # registry's internal invariants instead (uniqueness, label coverage, a sanity
    # floor). The fields-vs-FactorWeights drift is guarded separately below.
    assert FACTOR_COUNT == len(FACTOR_NAMES) == len(FACTOR_REGISTRY)
    assert len(set(FACTOR_NAMES)) == FACTOR_COUNT          # no dupes
    assert set(FACTOR_LABELS) == set(FACTOR_NAMES)
    assert all(f.name and f.label for f in FACTOR_REGISTRY)
    assert FACTOR_COUNT >= 6                                # sanity floor, not a tripwire


def test_factor_weights_fields_match_registry_exactly():
    # The drift guard: every registry factor is a FactorWeights field and vice-versa,
    # so adding/removing a factor can't desync the weight vector from the engine.
    weight_fields = set(FactorWeights.model_fields)
    assert weight_fields == set(FACTOR_NAMES), (
        f"FactorWeights fields != registry: "
        f"missing={set(FACTOR_NAMES) - weight_fields}, extra={weight_fields - set(FACTOR_NAMES)}"
    )


def test_sum_validator_covers_every_registry_factor():
    # A vector with all weight on the LAST registry factor must still validate to 1.0
    # — proves the sum iterates the whole registry, not a hardcoded subset.
    kw = {f: 0.0 for f in FACTOR_NAMES}
    kw[FACTOR_NAMES[-1]] = 1.0
    fw = FactorWeights(**kw)
    assert abs(sum(getattr(fw, f) for f in FACTOR_NAMES) - 1.0) < 1e-9


def test_min_non_null_bound_tracks_factor_count():
    fld = StrategyConfig.model_fields["min_non_null_factors"]
    # the upper bound is now derived from the registry (was a stale literal 11)
    le = [m for m in fld.metadata if hasattr(m, "le")]
    assert le and le[0].le == FACTOR_COUNT


def test_rank_factors_equals_registry():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "pipeline", "app"))
    import rank  # noqa: E402
    assert list(rank.FACTORS) == list(FACTOR_NAMES)


def test_display_indicators_are_not_scoring_factors():
    assert not (set(DISPLAY_INDICATORS) & set(FACTOR_NAMES))

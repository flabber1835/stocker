"""The builder must honour trailing_stop.reentry_policy, not its own hardcoded rule.

THE DEFECT. The builder excluded stop-blocked names with a SQL predicate
`adjusted_close <= stop_peak` — peak recovery, hardcoded. The delta step read the
configured policy. So a config asking for a 21-session cooldown got peak recovery
anyway, because when two components disagree the effective policy is whichever is
stricter. After a 30% stop, clearing the peak needs a ~43% rally: the configured
hysteresis became near-permanent exclusion, silently.

The fix is structural rather than a corrected predicate — ONE function, imported
by both. These tests pin that, because a second implementation is how the
divergence happened in the first place.
"""
from __future__ import annotations

import inspect
import os
import re

import pytest

from stock_strategy_shared.drawdown import reentry_blocked

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _builder_src() -> str:
    return open(os.path.join(ROOT, "services", "portfolio-builder",
                             "app", "main.py")).read()


class TestOneSharedRule:
    def test_the_builder_imports_the_shared_predicate(self):
        assert "from stock_strategy_shared.drawdown import reentry_blocked" in _builder_src()

    def test_the_delta_engine_uses_the_SAME_object(self):
        """Not merely an identical copy — the same function. A byte-identical
        second implementation drifts the moment one side is edited."""
        import sys
        sys.path.insert(0, os.path.join(ROOT, "services", "pipeline", "app"))
        try:
            from engine import reentry_blocked as engine_fn
            assert engine_fn is reentry_blocked
        finally:
            sys.path.pop(0)
            sys.modules.pop("engine", None)

    def test_the_builder_does_not_reimplement_the_predicate_in_SQL(self):
        """The original bug in one line: a comparison of last close against
        stop_peak inside the query, which no config can influence.

        Comments are STRIPPED first — the comment above the fixed query describes
        the old predicate verbatim, and matching it would fail the test for
        documenting the bug correctly. (Second time today I wrote that mistake.)
        """
        code = "\n".join(l.split("#")[0] for l in _builder_src().splitlines())
        assert not re.search(r"adjusted_close\s*<=\s*l?\.?stop_peak", code), (
            "the builder compares price to stop_peak in SQL again — that ignores "
            "reentry_policy entirely")

    def test_the_builder_reads_the_configured_policy(self):
        src = _builder_src()
        assert "reentry_policy" in src and "reentry_cooldown_sessions" in src


class TestThePolicyActuallyDiffers:
    """If the two policies agreed, none of the above would matter. They do not,
    and the gap widens with stop width — which is why the override was harmful
    rather than merely untidy."""

    def test_cooldown_releases_a_name_the_peak_rule_still_blocks(self):
        # 30% stop: price recovered a long way but nowhere near the old peak
        assert reentry_blocked(85.0, 100.0) is True
        assert reentry_blocked(85.0, 100.0, sessions_since_stop=21,
                               policy="cooldown", cooldown_sessions=21) is False

    @pytest.mark.parametrize("stop_pct,rally", [(0.15, 0.176), (0.30, 0.429)])
    def test_the_peak_rule_hardens_as_the_stop_widens(self, stop_pct, rally):
        stop_price = 100.0 * (1 - stop_pct)
        assert (100.0 / stop_price - 1) == pytest.approx(rally, abs=0.001)

from __future__ import annotations

from pathlib import Path
import unittest

import backtester.run_research_strict_pit_20y as base
from backtester.research_terminal_grace_overlay import (
    _move_prior_qty_after_split,
    install,
)


class ResearchSplitDividendOrderingTest(unittest.TestCase):
    def test_prior_close_entitlement_is_captured_after_split_before_open_trades(self) -> None:
        text = install(
            base.corrected.transformed_source(
                "fullpit", Path("/tmp/research-split-dividend-ordering-selftest")
            )
        )
        split_tail = "if finite(factor) and factor>0: last_factor[tid]=factor"
        entitlement = "prior_qty={s.tid:s.qty for s in book.slots if s.held()}"
        dayact = "dayact=actions.get(date,{})"
        exits = "for s in book.slots:\n                if not(s.held() and s.pending_sell): continue"
        buys = "for s in book.slots:\n                if not(s.reserved() and not s.held()): continue"

        self.assertLess(text.index(split_tail), text.index(entitlement))
        self.assertLess(text.index(entitlement), text.index(dayact))
        self.assertLess(text.index(entitlement), text.index(exits))
        self.assertLess(text.index(entitlement), text.index(buys))

    def test_canonical_split_loop_variant_uses_same_stable_ordering(self) -> None:
        entitlement = "            prior_qty={s.tid:s.qty for s in book.slots if s.held()}\n"
        canonical_split = (
            "            for tid0,ratio0 in zip(tids,canonicalsplit[tids]):\n"
            "                tid=int(tid0); ratio=float(ratio0)\n"
            "                if abs(ratio-1.0)>1e-12:\n"
            "                    split_events+=1\n"
        )
        dayact = "            dayact=actions.get(date,{})\n"
        transformed = _move_prior_qty_after_split(entitlement + canonical_split + dayact)

        self.assertEqual(transformed.count(entitlement), 1)
        self.assertLess(transformed.index(canonical_split), transformed.index(entitlement))
        self.assertLess(transformed.index(entitlement), transformed.index(dayact))

    def test_aeo_2006_12_19_exact_economic_boundary(self) -> None:
        # Run 33341153930 isolated the first post-REY divergence to AEO.
        # A prior-close holding of 118,329 shares is transformed by the
        # 1.5-for-1 split before the $0.075/share dividend entitlement is
        # measured in the current raw-share domain.
        pre_split_qty = 118_329.0
        split_ratio = 1.5
        dividend_per_share = 0.075
        post_split_qty = pre_split_qty * split_ratio
        undercredit = (post_split_qty - pre_split_qty) * dividend_per_share

        self.assertEqual(post_split_qty, 177_493.5)
        self.assertAlmostEqual(undercredit, 4_437.3375, places=10)


if __name__ == "__main__":
    unittest.main()

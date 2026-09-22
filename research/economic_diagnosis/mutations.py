"""Deliberate research-accounting faults against independent dollar-book tests."""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path

from research.economic_diagnosis import analyze, test_analysis

MUTANTS = {
    "overnight_ownership": ("overnight = old*opening/prior + (1-old)*(1+bill_on)",
                            "overnight = new*opening/prior + (1-new)*(1+bill_on)",
                            "test_exit_still_bears_overnight_loss"),
    "transition_fee": ("1-cost*abs(new-old)", "1", "test_fee_applies_to_changed_fraction"),
    "entry_gap_lookahead": ("new*closing/opening", "new*closing/prior",
                            "test_entry_does_not_receive_the_pre_entry_equity_gap"),
    "cash_compounding": ("(1+bill_on)*(1+bill_day)", "(1+bill_on+bill_day)",
                          "test_unchanged_sleeves_are_not_rebalanced_at_open"),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = inspect.getsource(analyze.factor)
    original = test_analysis.factor
    verdicts = {}
    for name, (before, after, test) in MUTANTS.items():
        assert source.count(before) == 1, name
        namespace = {}
        exec(compile(source.replace(before, after), "<accounting-mutant>", "exec"), namespace)
        test_analysis.factor = namespace["factor"]
        try:
            getattr(test_analysis, test)()
        except AssertionError:
            verdicts[name] = dict(verdict="KILLED", falsifier=test)
        else:
            raise AssertionError(f"surviving mutation: {name}")
        finally:
            test_analysis.factor = original
    args.output.write_text(json.dumps(verdicts, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(verdicts))


if __name__ == "__main__":
    main()

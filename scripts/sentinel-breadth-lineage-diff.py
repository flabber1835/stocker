#!/usr/bin/env python3
"""Compare the two preserved breadth lineages. Needs no corpus.

## The question this answers

The recovered classifier's headline result is 7,061/7,061 sessions exact over
160,715 holding-days. That was measured against the FROZEN oracle
(`04_BREADTH_ORACLES/fundamental_portfolio_health_daily.csv`) using the holding
panel of the PRE-CORRECTION replay.

The engine in this repository is the corrected lineage. So before anyone spends
hours regenerating a panel from raw Sharadar, there is a cheaper question:

```text
do the two preserved tapes describe the same book, and if not, from when
and because of what
```

Both tapes are in the repository. This script reads only them.

## What it distinguishes

A breadth fraction is an integer count over the held-position count, so the
denominator is recoverable from the fraction. That separates two very different
causes of a mismatch:

```text
different denominator   the books hold a different NUMBER of positions.
                        Definitively a population difference, not a rule one
same denominator        same size, but the counts differ. Could be different
                        CONSTITUENTS under an identical rule, or a different
                        rule. The fractions alone cannot separate those two
```

The second case is deliberately NOT reported as a classifier disagreement. Once
the held set diverges, a same-size book made of different names produces
different counts under an identical classifier, and calling that a rule
difference would be the wrong conclusion drawn from the right number.

## Usage

```bash
python3 scripts/sentinel-breadth-lineage-diff.py
```
"""
from __future__ import annotations

import csv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FROZEN = (REPO / "docs" / "sentinel-handoff" / "04_BREADTH_ORACLES"
          / "fundamental_portfolio_health_daily.csv")
CORRECTED = (REPO / "docs" / "sentinel-reference-implementation"
             / "sentinel_1p1_daily.csv")

#: CSV text carries ~17 significant digits; two writers of the same float can
#: differ in the last one. Anything above this is a real difference — the
#: fractions are integer ratios over books of at most ~25 positions, so genuine
#: differences are enormous by comparison.
TOL = 1e-9

#: Wealth Core holds 25 slots; allow headroom for the panel's row count.
MAX_DENOM = 40


def load(path: Path) -> dict:
    out = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            try:
                out[row["date"][:10]] = (float(row["damaged"]), float(row["green"]))
            except (ValueError, TypeError, KeyError):
                continue
    return out


def denominator(damaged: float, green: float):
    """Smallest held-count making both fractions whole positions."""
    for n in range(1, MAX_DENOM + 1):
        if (abs(damaged * n - round(damaged * n)) < 1e-6
                and abs(green * n - round(green * n)) < 1e-6):
            return n, round(damaged * n), round(green * n)
    return None, None, None


def main() -> int:
    frozen, corrected = load(FROZEN), load(CORRECTED)
    common = sorted(set(frozen) & set(corrected))

    print(f"frozen oracle      {len(frozen):5d} rows")
    print(f"corrected tape     {len(corrected):5d} rows")
    print(f"overlap            {len(common):5d} sessions "
          f"{common[0]} .. {common[-1]}")

    diffs = [d for d in common
             if abs(frozen[d][0] - corrected[d][0]) > TOL
             or abs(frozen[d][1] - corrected[d][1]) > TOL]
    identical = len(common) - len(diffs)

    print(f"\nidentical          {identical:5d}")
    print(f"divergent          {len(diffs):5d}  "
          f"({100 * len(diffs) / len(common):.1f}%)")

    if not diffs:
        print("\nthe two lineages describe the same book on every shared session")
        return 0

    first = diffs[0]
    before = [d for d in common if d < first]
    print(f"\nFIRST DIVERGENCE   {first}")
    print(f"  identical run before it: {len(before)} consecutive sessions "
          f"({before[0]} .. {before[-1]})")

    fn, fd, fg = denominator(*frozen[first])
    cn, cd, cg = denominator(*corrected[first])
    print(f"  frozen     {fd:2d} damaged / {fg:2d} green of {fn} held")
    print(f"  corrected  {cd:2d} damaged / {cg:2d} green of {cn} held")

    pop = same = unknown = 0
    for d in diffs:
        a = denominator(*frozen[d])[0]
        b = denominator(*corrected[d])[0]
        if a is None or b is None:
            unknown += 1
        elif a != b:
            pop += 1
        else:
            same += 1

    print(f"\ndecomposition of the {len(diffs)} divergent sessions:")
    print(f"  different held COUNT — population differs   {pop:5d}  "
          f"({100 * pop / len(diffs):.1f}%)")
    print(f"  same held count, different counts           {same:5d}  "
          f"({100 * same / len(diffs):.1f}%)")
    print(f"  denominator not inferable                   {unknown:5d}")
    print("\n  The second group is NOT evidence of a classifier difference.")
    print("  Once the held set diverges, a same-size book of different names")
    print("  produces different counts under an identical rule.")

    years = {}
    for d in diffs:
        years[d[:4]] = years.get(d[:4], 0) + 1
    print("\ndivergences by year:")
    for y in sorted(years):
        print(f"  {y}  {years[y]:4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

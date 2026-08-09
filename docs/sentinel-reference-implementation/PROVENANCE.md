# Provenance and independent verification

`README.md` in this directory is the **upstream** package README, verbatim, and
is covered by `SHA256SUMS.txt`. This file is the repository's own record: where
the package came from, what was checked HERE, and what remains unchecked.

Source archive: `docs/Sentinel_1_1_Python_Only_Corrected.zip`
(sha256 `9e0b069c4adc23e72ed2a2bec50eb2ee6a59533dfce418ddb140e12349ab476a`,
received 2026-08-09). Contents extracted verbatim; `__pycache__` dropped.

**This supersedes the earlier `sentinel_1p1.py` / `Sentinel_1_1_Python_Only.zip`,
both DELETED.** Do not restore them — the earlier source carries a slow-stress
off-by-one that shifts a real 2022 transition by one session.

Nothing here is imported by Stocker, on any deploy path, or covered by the
Stocker test suite. It is the Sentinel reference implementation and the parity
target for item F of `docs/sentinel-deployment.md`.

## Verified IN THIS REPOSITORY, 2026-08-09

The package ships `validate_against_frozen.py`, and the frozen oracle it wants
(`docs/sentinel-handoff/02_SENTINEL_1P1_FROZEN_ORACLE/03_exact_candidate_daily.csv`)
is already committed here. So the parity claim is checkable without the raw
Sharadar corpus, and it was:

```bash
python3 docs/sentinel-reference-implementation/validate_against_frozen.py \
  --daily  docs/sentinel-reference-implementation/raw_sharadar_20y_daily.csv \
  --frozen docs/sentinel-handoff/02_SENTINEL_1P1_FROZEN_ORACLE/03_exact_candidate_daily.csv
```

```text
sessions                                  5032
candidate_allocation_mismatches              0
parent_effective_allocation_mismatches       0
damaged_mismatches                           0
green_mismatches                             0
shadow_max_normalized_relative_error   4.44e-16
nav_max_relative_difference             0.00125
nav_ending_relative_difference          0.00125
```

Every figure in `PARITY_REPORT.json` reproduces exactly. This is the first
independent confirmation in this repository that the recovered breadth and the
controller's allocation path match the frozen tape — previously both were
author's claims. `4.44e-16` is two machine epsilons: the shadow is not
approximately equal, it is equal.

Also checked: `sha256sum -c SHA256SUMS.txt` clean over all seven payloads, and
the four shipped controller unit tests still pass against the corrected source
(their import was retargeted from `sentinel_1p1` to `sentinel_1p1_standalone`;
that one-line edit is the only modification to any shipped file).

## What this does NOT establish

**That running `sentinel_1p1_standalone.py` against raw Sharadar produces
`raw_sharadar_20y_daily.csv`.** The verification compares a shipped OUTPUT to the
frozen oracle; it does not re-derive that output from the corpus, which this
machine does not have. A CSV agreeing with the oracle is consistent with the
source having produced it and does not prove it did.

So the honest position is: **the tape is confirmed, the producer is not.**
Closing that needs the corpus — `00_README/EXTERNAL_SHARADAR_SHA256SUMS.txt` in
the reproduction kit pins the exact inputs. Until then, treat the source as the
specification and the CSV as the parity target.

## The three code changes, since the README lists two

```text
1  STRESS DURATION off-by-one   `stress_duration += 1` REMOVED;
   (README item 1)              len(shadow_eq) - stress_start_i already yields 1
                                on the entry session. Consequence: 2022-05-17 is
                                duration 30, so slow-severe is decided at that
                                close and 0% Core is effective at the 2022-05-18
                                open. The old source was a session late
2  MEASUREMENT-WINDOW init      `date >= start` -> `date > start` in the NAV
   (README item 2)              accounting, with an explicit `date == start`
                                branch pinning NAV to 1.0, so the warm-up
                                interval cannot compound into the reported
                                20-year figure
3  UNCHANGED-ALLOCATION branch  NOT in the README's "what was fixed". When
   (in the diff only)           |new - old| < 1e-15 the sleeves now compound
                                close-to-close and mix at the fixed allocation,
                                instead of being split into overnight/intraday
                                legs. The BIL legs also became conditional —
                                `bo` only when old_alloc < 1, `bi` only when
                                new_alloc < 1 — so a fully-invested session no
                                longer computes a defensive leg it does not have
```

Change 3 is an accounting-semantics change on every session where exposure is
constant, which is the overwhelming majority of them. It is worth naming
explicitly because a reader working from the README alone would not know to look
for it.

## Reproduction hazards, unchanged from the previous package

```text
gc.disable()              module-level and unconditional; any process importing
                          this file inherits it
float32 lag closes        r21/r63 divide by lag closes stored as float32. Every
                          boundary in the breadth classifier is strict-vs-
                          inclusive, so a float64 rewrite will disagree on
                          boundary rows and look like a logic error
VERIFIED_CASH_SETTLEMENTS two hardcoded terminal cash terms (VRNA 107.0,
                          DAWN 21.50), audited out of band
```

## The residual NAV difference is not a defect

`nav_ending_relative_difference` is 0.00125 — 12.5 bp of terminal wealth over
twenty years, first appearing 2007-07-30 at the first parent transition, while
allocation, breadth and shadow stay exact. Upstream declines to patch it, and
that is the right call: the frozen 1.1 NAV inherits the Sentinel 1.0x parent's
open-accounting lineage, whereas this source applies ONE uniform next-open rule
to every date. Forcing a bit-exact NAV match would mean embedding legacy parent
accounting outputs as a runtime input — which is precisely what "no frozen
oracle as a runtime input" exists to prevent.

Certify Sentinel against the **transition oracle** (allocations and dates), not
against the frozen NAV series.

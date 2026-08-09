# Sentinel 1.1-RC — standalone reference implementation

Source archive: `docs/Sentinel_1_1_Python_Only.zip`
(sha256 `864fbaaf49386566be3d29c12e4a97321505120819413e4fcc683a6489355e17`,
received 2026-08-09). The two files here are its complete contents, extracted
verbatim. **Nothing in this directory is imported by Stocker**, is on any deploy
path, or is covered by the Stocker test suite. It is research provenance.

```text
sentinel_1p1.py        585 lines. Builds the Wealth Core shadow from raw
                       Sharadar, computes holding-level GREEN/RED/AMBER breadth,
                       runs the 1.0x fast/slow controller and the 1.1 recovery
                       ramp, applies next-open scalar allocation with BIL as the
                       defensive sleeve.
test_sentinel_1p1.py    61 lines, 4 synthetic unit tests over the four
                       controller state machines. No oracle data.
```

## Why this file matters more than the prose

Its docstring makes a claim the architecture doc has been asking for since
Sentinel was scoped:

> No frozen path, allocation, breadth, transition, CSV/JSON oracle, or
> precomputed strategy output is read.

If that holds, this is an **independent** producer of the frozen oracle rather
than a replay of it — which is exactly what §8 Q2 needed to stop being blocking.
It supplies `damaged_breadth` and `green_breadth` as executable code, not as a
described quantity.

## What has and has not been verified here

Verified in this repository, 2026-08-09:

```text
the four shipped unit tests pass (pandas 3.0.5 / numpy 2.4.6)
    test_binary_stress_hysteresis
    test_fast_state_minimum_hold_and_rearm
    test_slow_state_recovery
    test_sentinel_recovery_ramp
both files byte-match the archive; sentinel_1p1.py compiles
```

**Not** verified, and it is the whole claim:

```text
that a full run reproduces the frozen oracle's daily path, transition dates or
headline metrics. That needs the raw Sharadar corpus (SEP 1998-2026, ACTIONS,
TICKERS, SFP), which is not in this repo and not on this machine. Until such a
run is done and its output diffed against
docs/sentinel-handoff/.../02_SENTINEL_1P1_FROZEN_ORACLE/, the independence
claim above is the author's, not a measurement.
```

The unit tests exercise the state machines on synthetic sequences. Passing them
says the hysteresis and ramp logic behave as specified on hand-built inputs; it
says nothing about whether the breadth this program computes from real prices
equals the breadth the frozen oracle recorded. Those are the two different
questions the reconstruction work has repeatedly conflated.

## Reproduction hazards worth reading before running it

```text
gc.disable() at import time     module-level, unconditional. Any process that
                                imports this file inherits it.
float32 lag closes              r21/r63 in the original replay divided the
                                current close by a lag close stored as float32.
                                See docs/sentinel-reproduction-kit/
                                04_EXACT_BREADTH_RECOVERY/RECOVERY_STATUS.md.
VERIFIED_CASH_SETTLEMENTS       two hardcoded terminal cash terms (VRNA 107.0,
                                DAWN 21.50) audited out of band, absent from the
                                raw terminal rows. Same class of fact as Wealth
                                Core's C1 exact-terms branch.
EXPECTED_HASHES                 32 corpus file hashes, opt-in via a flag. They
                                pin the DATA, not the strategy.
```

Run: `python3 sentinel_1p1.py --data <sharadar-dir> [--verify-hashes]`.

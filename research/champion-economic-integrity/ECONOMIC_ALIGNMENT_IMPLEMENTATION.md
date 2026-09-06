# Production-equivalent economic alignment — implementation checkpoint

Date: 2026-09-06

Branch: `research/champion-production-equivalent-economic-alignment`

Base: `023dda5f63ea64fea0e846c619604b49206204db`

## Completed

- Froze the production-equivalent economic contract in Markdown and machine-readable JSON.
- Added `backtester/champion_final_security_truth.py` to make the completed P0/P1/P2/P3 factual review executable in the generated Champion classifier path, with cleanup precedence and the final PDS session-boundary override.
- Added `backtester/production_equivalent_economic_overlay.py` with fail-closed generated-source transformations for the remaining known economic seams:
  - final closed truth classifier import;
  - ex-date dividend receivable accrual before open-equity witness;
  - one-session dividend due convention retained;
  - removal of cumulative research-only terminal retirement;
  - removal of replay-only missing-mark NAV hard abort while retaining unresolved state/admission blocking;
  - source assertions forbidding executable capacity guards and pre-ranking terminal retirement geometry.
- Added `backtester/champion_production_equivalent_build.py`, a source-build/probe command that intentionally does not execute the 20-year replay.
- Added synthetic source-seam and dividend-entitlement transition tests.

## Replay status

**NOT RUN.**

The 20-year performance replay remains gated. The next required step is to execute the source builder/probe suite in the pinned environment with:

- exact candidate checkout `ba74e79490beb8950611b1d17f5d124833b3d91e` supplied as `--candidate-root`;
- canonical PIT dataset hash `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`;
- pinned runtime identity `887f479b15ad861313da666ad698034d3847121c`.

The builder must produce `PASS_SOURCE_BUILD_NO_REPLAY` and all synthetic/source tests must pass before the replay gate can be opened.

## No performance target

No historical CAGR is used as an acceptance criterion. The next full replay, once authorized by green implementation probes, will be accepted or rejected on semantic/provenance gates only.

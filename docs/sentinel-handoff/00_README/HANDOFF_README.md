# Sentinel 1.1 frozen research harness / oracle handoff

## Purpose
This package preserves the retained research evidence used to derive Sentinel 1.1 and gives the production implementation a frozen oracle. It is intentionally not cleaned up into a new implementation. The rule is: **read, compare, and reproduce; do not reinterpret missing behavior from prose.**

## Authoritative latest research candidate
The latest retained candidate is **Sentinel 1.1-RC, zero recovery gate**:

- Parent controller: Sentinel 1.0x (ordinary stress is a sensor; fast/slow severe causes drive the 0% actuator).
- Sentinel 1.1 change: on a canonical 0% -> 100% recovery, inspect `delta_r40_5 = r40(prior close) - r40(5 eligible sessions earlier)`.
- If `delta_r40_5 > 0`, recover canonically to 100% Core.
- If `delta_r40_5 <= 0`, recover first to 55% Core / 45% BIL.
- After 10 consecutive canonical healthy closes (`r20 > 0`, `damaged <= 60%`, `green >= 20%`), move to 65% Core.
- After another 10 consecutive healthy closes, move to 100% Core.
- Renewed canonical severe state overrides the ramp and returns target Core to 0%.

The previous +1 percentage point gate produced exactly the same historical path. The zero gate is the frozen simplified rule because it is exact-history equivalent and more robust to delayed features.

### Frozen exact historical reference, 2006-07-31 through 2026-07-31

- CAGR: **22.25174847%**
- Max drawdown: **-21.94904567%**
- Ending multiple: **55.608018x**
- Parent Sentinel 1.0x: 22.11974992% CAGR, -23.92559171% max DD, 54.419402x ending multiple.

## Critical architectural finding: the research overlay is scalar
The retained exact-next-open research model is an **allocation scalar over the immutable Wealth Core shadow**, not a second share-level Wealth Core episode machine. The reference accounting assigns the overnight close->next-open interval to the old allocation, the open->close interval to the new allocation, and charges cost on changed allocation notional. Production therefore needs a separate share-level execution projection, but controller certification should remain against this scalar oracle.

## The breadth blocker
The complete daily `damaged` and `green` breadth outputs are retained. The original **security-level classifier function** that assigned each holding its damaged/green label has **not been found** in the retained artifacts searched so far.

This is an explicit gap, not permission to invent a replacement. Before Sentinel controller implementation is accepted, any recovered or newly ported classifier must reproduce the frozen breadth oracle exactly (subject only to explicitly documented data-version differences).

Useful breadth files:
- `04_BREADTH_ORACLES/fundamental_portfolio_health_daily.csv`
- `04_BREADTH_ORACLES/sentinel_1p1_exact_daily_with_breadth.csv`

The retained position-level research scripts reconstruct holding-day state and consume green/red classifications, but do not contain the missing classification assignment itself.

## Directory guide
- `01_CURRENT_ARCHITECTURE/` — current design document.
- `02_SENTINEL_1P1_FROZEN_ORACLE/` — **latest oracle**. Exact daily path, transition audit, parameter plateau, rolling starts, delay/cost sensitivity, adversarial recovery tests, and promotion scorecard.
- `03_SENTINEL_1P0_PARENT/` — parent controller specification and simplification-equivalence proof.
- `04_BREADTH_ORACLES/` — frozen daily breadth/health outputs.
- `05_RECOVERY_RAMP_LINEAGE/` — immediate +1pp predecessor and its promotion suite.
- `06_RESEARCH_SOURCE_FRAGMENTS/` — actual Python scripts recovered from the systemic-shock and position-level research lineage.
- `07_SUPPORTING_SPECS/` — earlier persistent-bear / Wealth Core engineering specifications. These are lineage evidence; later frozen rules win where they differ.
- `08_SOURCE_ARCHIVES/` — untouched original zip bundles as retained in the ChatGPT file library.
- `09_GAPS/` — explicit missing/unrecovered items.

## Files Claude should read first
1. `00_README/FROZEN_SENTINEL_1P1_RULE.json`
2. `02_SENTINEL_1P1_FROZEN_ORACLE/zero_gate_decision.txt`
3. `02_SENTINEL_1P1_FROZEN_ORACLE/14_promotion_scorecard.json`
4. `02_SENTINEL_1P1_FROZEN_ORACLE/03_exact_candidate_daily.csv`
5. `02_SENTINEL_1P1_FROZEN_ORACLE/sentinel_1p1_transition_oracle.csv`
6. `03_SENTINEL_1P0_PARENT/Sentinel_1.0x_Comprehensive_Engineering_Prospectus.pdf`
7. `04_BREADTH_ORACLES/fundamental_portfolio_health_daily.csv`
8. `09_GAPS/MISSING_OR_UNRECOVERED.md`

## Implementation gate for Claude
Do not start by translating the PDF into code. First:
1. Reproduce the parent Sentinel controller decisions from frozen inputs.
2. Prove breadth parity against the daily oracle; if the security-level definition is still unavailable, stop and report the blocker rather than infer it.
3. Reproduce the Sentinel 1.1 recovery-ramp allocations and transition dates exactly from `03_exact_candidate_daily.csv`.
4. Preserve the scalar controller oracle as Claim 1. Build share-level execution projection as Claim 2.
5. Never allow realized broker exposure to feed back into Sentinel state.

## Known Sentinel 1.1 candidate allocation transitions
See `sentinel_1p1_transition_oracle.csv`. The recovery ramp creates the expected 55%/65% phases in 2011, 2015-16, and 2022; other canonical recoveries return directly to 100%.

## Integrity
`FILE_MANIFEST.csv` and `SHA256SUMS.txt` identify the exact files in this handoff. The untouched source archives are included so later refactors can always be traced back to the retained research artifacts.

---

## Stored in this repository (added 2026-08-09)

The ORIGINAL, UNMODIFIED archive is committed alongside the extracted tree:

```text
docs/Sentinel_1_1_Frozen_Harness_Handoff.zip
  sha256  c344dd14ee920985d65becf48c6317c484b20720cb223c22412fa7bf22f43993
  size    8.7 MB
```

Both are kept deliberately. The extracted tree is what anyone reads or greps;
the zip is the authoritative artefact, and it is what `00_README/SHA256SUMS.txt`
was computed against. If the two ever disagree, THE ZIP IS CORRECT — re-extract
rather than trusting a tree that may have been edited in place.

Verify before relying on anything here:

```bash
sha256sum docs/Sentinel_1_1_Frozen_Harness_Handoff.zip
cd docs/sentinel-handoff && sha256sum -c 00_README/SHA256SUMS.txt
```

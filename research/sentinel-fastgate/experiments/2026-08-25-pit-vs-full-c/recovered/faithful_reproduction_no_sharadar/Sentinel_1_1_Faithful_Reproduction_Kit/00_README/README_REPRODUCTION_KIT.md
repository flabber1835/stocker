# Sentinel 1.1 Faithful Reproduction Kit

Created: 2026-08-08

## Purpose

This archive preserves the code, frozen research oracles, certified Wealth Core packages, recovered breadth semantics, and integrity metadata required to faithfully reproduce the retained **Sentinel 1.1-RC (zero recovery gate)** research strategy.

**Raw Sharadar market-data payloads are intentionally NOT included in this lean edition.** Supply your own copies and verify them against `00_README/EXTERNAL_SHARADAR_SHA256SUMS.txt` before treating a replay as reference-equivalent.

### Authoritative reference result

Reference window: **2006-07-31 through 2026-07-31**

- CAGR: **22.25174847%**
- Maximum drawdown: **-21.94904567%**
- Ending multiple: **55.608018x**
- Parent Sentinel 1.0x: 22.11974992% CAGR, -23.92559171% max DD, 54.419402x ending multiple

The frozen Sentinel handoff is the authoritative controller oracle. Do not reinterpret rules from prose when a frozen oracle or rule JSON exists.

## Reproduction stack

1. **External raw market data (not bundled)**
   - Sharadar SEP yearly files, 1998-2026
   - Sharadar ACTIONS
   - Sharadar TICKERS
   - Sharadar SFP (required for SPY/BIL reference series)
   - Exact expected SHA-256 values are preserved in `00_README/EXTERNAL_SHARADAR_SHA256SUMS.txt`.
   - SF1 fundamentals are not required because certified Wealth Core and Sentinel 1.1 do not consume fundamentals.

2. **Certified Wealth Core**
   - `stocker_certified_wealth_core_v1.zip`
   - `stocker_certified_sharadar_symbolic_wealth_v1.zip`
   - Wealth Core is the immutable full-exposure alpha/shadow engine.

3. **Sentinel frozen research harness**
   - `Sentinel_1_1_Frozen_Harness_Handoff.zip`
   - Contains the frozen 1.1 rule, exact daily oracle, transition oracle, Sentinel 1.0x parent, recovery-ramp lineage, source fragments, source archives and promotion evidence.

4. **Exact recovered breadth classifier**
   - `recovered_breadth_classifier.py`
   - The GREEN / RED / AMBER / sector-stress classifier was mathematically recovered to exact daily count parity on all 7,061 comparable sessions / 160,715 holding-days.
   - Preserve the original float32 lag-close numerical semantics for r21/r63 or prove an exactly equivalent implementation.

## Critical distinction: the missing firewall `priority` formula

The historical file `/mnt/data/selective_firewall/run_firewall_experiment.py` has not been recovered, and the original `priority` ranking expression used by the earlier Selective Survivor Firewall remains unknown.

**This does not block Sentinel 1.1 reproduction.** Sentinel 1.1 consumes aggregate `damaged_breadth = mean(amber)` and `green_breadth = mean(green)` and does not use the selective-firewall `priority` ranking actuator.

Do not invent `priority` if reconstructing the older Selective Survivor Firewall. The compatibility entry point in `recovered_breadth_classifier.py` deliberately fails closed.

## Sentinel 1.1 research accounting contract

The retained exact-next-open research model is a **scalar allocation overlay over the immutable Wealth Core shadow**:

- decision after official close t;
- overnight close -> next-open belongs to the old allocation;
- open -> close belongs to the new allocation;
- transaction cost is charged on changed allocation notional;
- severe target is 0% Core / 100% defensive;
- ordinary stress is a sensor, not an actuator;
- the recovery ramp may use 55% -> 65% -> 100% Core;
- renewed canonical severe evidence overrides the ramp and returns to 0% Core.

A broker/share-level production implementation is a separate execution-projection problem and should be certified against this scalar controller oracle rather than silently redefining the research strategy.

## Minimum acceptance tests for a future rebuild

A faithful rebuild should, in order:

1. Reproduce certified Wealth Core shadow NAV from raw Sharadar data.
2. Reproduce GREEN and AMBER/damaged daily counts exactly against the frozen breadth oracle.
3. Reproduce Sentinel 1.0x fast/slow state transitions from the same shadow observations.
4. Reproduce Sentinel 1.1 zero-gate recovery-ramp allocations and transition dates exactly.
5. Reproduce the exact daily candidate path over 2006-07-31 -> 2026-07-31.
6. Reproduce the reference headline metrics above within explicitly documented floating-point tolerance.
7. Never use realized live/broker exposure as an input to Sentinel state; Sentinel judges the immutable shadow plus its own event memory.

## Integrity

`FILE_MANIFEST.csv` and `SHA256SUMS.txt` cover every bundled payload file in this lean kit. `EXTERNAL_SHARADAR_SHA256SUMS.txt` records the hashes of the intentionally omitted Sharadar inputs. Verify both the bundled files and your external data before using a replay as a certification source.

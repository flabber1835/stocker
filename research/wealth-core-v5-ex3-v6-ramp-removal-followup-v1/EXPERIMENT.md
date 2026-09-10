# Ramp removal follow-up: preregistration

> Post-experiment decision, 2026-09-10: [compact_simplified_no_ramp is the current simplification and hardening research champion (56.27×)](CHAMPION.md). The preregistration and recorded gate outcomes below remain unchanged.

User authorization: proceed with the seven-slot follow-up proposed after reviewing
hardening commit `44be8212c01dcdab4c913cb1b03ef28ef6c293da`. Delivery continues
through research PR #350 and issue #349. Main was independently checked at
`aee4b96ec50e91245b7ea6eaef4a11c50619715a`; research parent is
`d1892a83f0cfce058425a2dbbf6b789707427419`.

## Questions and arms

Each full-PIT Core replay supplies the same immutable observations to six tracks:

| Track | Native | EX3 | Peer implementation |
|---|---|---|---|
| original | Frozen V6 | Frozen V6, SPY rebound enabled | Frozen full network |
| simplified | Stored 51.9214x candidate | Stored no-SPY-rebound version | Selective symmetric cache |
| original_no_ramp | Delete the complete recovery ramp and its four fields | Frozen V6 | Frozen full network |
| simplified_no_ramp | Delete the complete recovery ramp | Stored no-SPY-rebound version | Selective symmetric cache |
| compact_original_no_ramp | Bounded ramp-free state | Five decision fields, rebound enabled | Add zero-red shortcut and integer vote |
| compact_simplified_no_ramp | Bounded ramp-free state | Five decision fields, rebound disabled | Add zero-red shortcut and integer vote |

The complete-ramp removal is distinct from the unsuccessful mandatory 0.55 ramp.
Native remains zero during severe states. EX3 continues to gate recovery and may
hold final exposure at zero or 0.55 after Native requests one.
Native's ordinary, base-fast, fast and slow mechanisms remain separate.
Wealth Core holdings, sizing, trading, cash accounting and shadow history remain
the frozen V5 implementation. No Sentinel track can change Core or its sensors.

## Seven full-PIT starts

1. Fresh original baseline with all six controller tracks.
2–4. Exclude, individually, the three most frequently held permanent security IDs
in that baseline, excluding the six IDs used in the prior hardening campaign.
Rank by measured holding-session count, then permanent-ID lexical order. Freeze
selection before any fault replay. No fault outcomes enter selection.
5–7. Stable permanent-ID universe dropout of 1%, with seeds 29, 47 and 83.

Prior excluded IDs: 301606049357818446, 1040633074096912075,
277347208162984956, 727329233939509358, 425931792436652190,
311453645065866101. These six fresh faults are reported separately from the
seven cases in the earlier ablation study. The new study is an extension of the
same historical dataset, not an untouched temporal holdout.

Each case claims a unique permanent Git ref immediately before its sole
`module.run()` call. A claimed slot cannot run again. No automatic Core retries.
This campaign adds at most seven starts to this simplification thread's 21
completed starts. The earlier eight-start hardening study belongs to a separate
campaign. Offline controller replay and deterministic checks use no Core slots.

## Authorities and acceptance gates

Frozen original source SHA256:
`335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d`.
Stored simplified source SHA256:
`2f3e0a6d2fbeb2704e0ea61972a4c8509a6d75462cb7ecb69b56afedb8637c2c`.
Replay harness: `eaddca3f04f279e99663f832bf7293e92ee15662`.
Telemetry/replay reference: hardening commit `44be8212c01dcdab4c913cb1b03ef28ef6c293da`.
Dataset: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.
Measurement: 2006-07-31 through 2026-07-31, 5,032 sessions, warmup from 2006-01-03.
The frozen next-open execution clock, integer sizing, 10bp costs/reserve and
one-session dividend lag are retained.

- Original baseline must pass the frozen Core, transaction, decision and
  headline checks. Original offline replay must match engine allocations,
  Native targets and reasons; inherited CSV NAV tolerance is 1e-10.
- Minimal original ramp removal must match the prior ablation class on every
  observation. Both prior baseline artifacts are downloaded and checked against
  fresh original/no-ramp and simplified results.
- Compact pairs must match their respective ramp-free references exactly in
  targets, reasons, effective allocations and NAV on every case. Both recovery
  designs also receive synthetic boundary and restart checks.
- Original, cached and zero-red/integer peer functions are compared on each Core
  breadth call. They share immutable per-close residual lookups; correlations and
  breadth decisions are independently computed. All held stocks remain eligible
  neighbors. A mismatch aborts the case and consumes its claimed slot.
- Compact controllers use a versioned strict snapshot; missing/extra fields,
  invalid booleans, out-of-range counters and incompatible schemas are rejected.
  Replay restart checks also preserve pending/effective allocations, the pending
  Native target, NAV and previous accounting date/equity. Active legacy ramp
  states require historical replay; this experiment does not migrate them.
- Economic-preservation screen, all 5/10/15/20-year windows: absolute CAGR
  difference <=0.25pp, drawdown deterioration <=1pp, absolute terminal-multiple
  change <=5%. Report versus original and versus simplified separately.
- Robustness screen: at least 50% median *individual* allocation-area reduction
  on faults affecting the comparator, and baseline CAGR loss <=1pp. Report
  comparator, sample size, every fault, terminal reconvergence, median and worst
  CAGR/drawdown sensitivity. Improvement in the median never hides worse tails.

No result authorizes promotion or merging. Existing evidence: original 49.6193x;
simplified 51.9214x; legacy ramp removal 22.16% CAGR / -25.87% max drawdown.
These are historical reference headlines, not new campaign results.

## Evidence and publication

Store complete generated strategy sources and SHA256s before launch. Preserve
warmup-inclusive observations, combined daily tracks, raw engine evidence,
slot receipts and failures in Actions artifacts. Publish compressed reusable
observation/daily tapes, results JSON and headline tables to this research branch.
Publish baseline headlines before fault jobs, and a complete/incomplete report
after all available cases. Result-only commits cannot trigger a new Core start.

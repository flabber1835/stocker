# Sentinel 1.1 / Wealth Core terminal-order correction

## Verdict

The historical lineage contained a real corporate-action ordering defect. The corrected implementation now treats terminal corporate actions as part of the session state before pending-entry fills and before close-time admissions.

The correction is causal and does not use future information:

1. At the current session, load effective corporate actions.
2. Mark terminal securities.
3. Cancel any pending entry into a security that is terminal at that open.
4. Process held-security terminal exits/settlements.
5. Process remaining pending fills.
6. At the close, exclude securities that terminated that session from new admissions.

## Historical defects found

### Pending entry that actually filled into a terminal security

- 2023-11-29 — VRTV — `acquisitionby|delisted`
- The old path bought 755,224 VRTV shares at $169.99 on the terminal date.
- The corrected path cancels that pending entry before the fill.

### Terminal-close names that the old path attempted to schedule for the next open

| Date | Ticker | Terminal actions | Durable candidate rank |
|---|---|---|---:|
| 2008-10-09 | SCRX | acquisitionby, delisted | 98 |
| 2016-02-04 | SWI1 | acquisitionby, delisted | 7 |
| 2016-02-22 | KING | acquisitionby, delisted | 2 |
| 2018-10-09 | SYNT | acquisitionby, delisted | 10 |
| 2020-04-06 | FTSV | acquisitionby, delisted | 1 |

These were not valid next-open admission candidates once the terminal event was already known at the same close. In the old path they consumed the one-admission-per-session mechanism and delayed valid replacements.

## Post-fix acceptance checks

- Raw Sharadar corpus hash check: PASS.
- Full replay: 1998 through 2026.
- 20-year Sentinel reporting window: 2006-07-31 through 2026-07-31, 5,032 sessions.
- Executed buys on or after a terminal action after the fix: **0**.
- Terminal security still held at the end: **0**.
- Terminal ticker followed by a later `listed` action in this Sharadar corpus: **0**.
- Pending terminal entries blocked: **1**.
- Terminal-close admissions blocked: **5**.

## Performance impact

| Metric | Previous raw-Sharadar reference | Terminal-corrected | Change |
|---|---:|---:|---:|
| Sentinel CAGR | 22.259384% | **22.094535%** | -0.164849 pp |
| Sentinel max drawdown | -21.949046% | **-21.963098%** | -0.014052 pp |
| Sentinel ending multiple | 55.677526x | **54.195113x** | -2.6625% |
| Wealth Core full-history multiple | 165.814088x | **173.765727x** | +4.7955% |

The correction improves Wealth Core's full-history ending wealth but changes the shadow risk path. The first Wealth Core path divergence occurs on 2016-02-05. The changed shadow later causes an additional Sentinel severe episode: the corrected Sentinel is 0% Wealth Core from 2025-04-08 through 2025-05-06 while the old path remains at 100%. There are 20 allocation-difference sessions in total.

## Current endpoint book

At 2026-07-31 the corrected Wealth Core shadow has:

- 20 held stocks
- stock weight: 62.8589%
- cash / vacant-slot weight: 37.1411%
- VRTV is no longer present

The large cash balance is therefore not explained by the VRTV zombie bug. It remains a consequence of the 25-slot / 4%-entry / cooldown / no-rebalancing mechanics, although the exact holdings and weights changed after the corporate-action correction.

## Lineage status

Do not overwrite the prior frozen Sentinel 1.1 result. It remains useful as an audit artifact showing what the old code produced. This corrected path should be treated as a new corrected research lineage until the production Wealth Core implementation is updated and re-certified against the same terminal-order semantics.

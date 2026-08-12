# Sentinel 1.1 breadth classifier — forensic reconstruction

> **CURRENT STATUS NOTE (added later; the report below is unchanged).**
>
> This report is the FORENSIC PASS of 2026-08-09, written before the classifier
> was recovered. Its conclusions — "not recovered", a GREEN rule exact on only
> 90.27% of sessions, a one-sided AMBER shortfall, an escalation term still to
> be found — describe what was known at that hour. They are **superseded** and
> are retained because the residual analysis is what makes the recovered rule
> credible: both terms it predicted must exist turned out to be exactly the two
> that were missing.
>
> The exact classifier landed the same day and is in this directory as
> `recovered_breadth_classifier.py` (and, identically, under
> `docs/sentinel-reproduction-kit/04_EXACT_BREADTH_RECOVERY/`). It supplies the
> **age-63 GREEN exemption** and **AMBER's sector escalation**, and reproduces
> the frozen breadth counts exactly: **7,061 / 7,061 sessions on both GREEN and
> AMBER/damaged over 160,715 holding-days**, mean absolute daily count error
> 0.000. `docs/sentinel-controller-certification.md` §7a transcribes the rules.
>
> `reconstruction_metrics.json` beside this file belongs to THIS report, not to
> the recovery — its `green_candidate` / `damaged_core_candidate` fields are the
> superseded approximations measured below.
>
> Two things below still stand. The DENOMINATOR finding (position-panel row
> count, not the health CSV's `holdings` column) is confirmed by the recovered
> source. And the "Recommended implementation rule" still holds with its reason
> updated: the `UNCERTIFIED_BREADTH` gate is now about **our reimplementation**
> not yet having been proven against the tape, not about the rule being unknown.
> `priority` remains genuinely unrecovered — Sentinel does not consume it.

## Bottom line

The original missing function `position_features(g, cfg)` has **not** been recovered byte-for-byte, but the forensic reconstruction materially narrows the gap.

I regenerated the original 1998–2026 fixed-30 Wealth Core holding panel from the retained replay source and Sharadar inputs. The regenerated panel contains **160,715 holding-days**. Its Wealth Core NAV path matches the frozen shadow NAV tape to floating-point precision, which confirms that the reconstruction is operating on the correct portfolio history.

The most important structural discovery is that the frozen breadth fractions use the **actual position-panel row count for each date as their denominator**. They do not use the `holdings` column in `fundamental_portfolio_health_daily.csv`. Once the correct denominator is used, every frozen `green` and `damaged` fraction resolves to an integer number of classified positions.

## High-confidence recovery: GREEN

The strongest simple rule is:

```python
green = (
    own_dd >= -0.075
    and r21 >= 0.0
    and r63 >= 0.0
)
```

Against all **7,061** comparable sessions:

- exact green position count on **90.27%** of sessions;
- mean absolute error **0.119 positions/session**;
- maximum absolute error **7 positions**.

This is strong enough to identify the core semantics with high confidence, but it is not yet sufficient to call the production classifier certified.

## High-confidence lower bound: DAMAGED / AMBER

The strongest recovered core rule is:

```python
damaged_core = (
    own_dd <= -0.10
    or r21 <= -0.03
)
```

This has a particularly informative residual shape:

- exact damaged count on **69.69%** of sessions;
- the rule **never over-predicts** damaged positions;
- it is short by an average of **0.403 positions/session**;
- the largest shortfall is **5 positions**.

That one-sided error is strong evidence that the original `amber` classifier was approximately:

```python
amber = damaged_core OR additional_escalation_condition
```

rather than a materially different base rule.

The surviving source also proves that downstream Sentinel breadth was:

```python
damaged_breadth = mean(x.amber)
green_breadth   = mean(x.green)
```

and that `position_features()` returned a sector-level `sector_stress` object. The remaining unidentified escalation is therefore most plausibly a sector/cluster stress term or another composite term generated inside `position_features()`. I tested simple sector proxies derived from the retained panel; none reproduces the missing residual exactly, so I am **not** promoting one as the answer.

## Sentinel-threshold impact

The incomplete reconstruction already agrees very strongly on the green predicates used by Sentinel, but the missing damaged escalation still matters:

| predicate                |   agreement |   mismatch_sessions |   true_sessions |   reconstructed_sessions |
|:-------------------------|------------:|--------------------:|----------------:|-------------------------:|
| fast_damaged_ge_0.85     |    0.987254 |                  90 |             216 |                      126 |
| fast_green_le_0.20       |    0.996601 |                  24 |             828 |                      848 |
| slow_damaged_ge_0.75     |    0.975216 |                 175 |             547 |                      372 |
| slow_green_le_0.25       |    0.994477 |                  39 |            1247 |                     1284 |
| recovery_damaged_le_0.60 |    0.968985 |                 219 |            5792 |                     6011 |
| recovery_green_ge_0.20   |    0.997168 |                  20 |            6326 |                     6310 |

The damaged-side mismatch is concentrated in the conservative direction: the incomplete reconstruction tends to call **fewer** holdings damaged than the frozen oracle. Therefore replacing the frozen oracle with the incomplete formula would be fail-open and is not acceptable.

## What is now proven

1. The correct portfolio history can be regenerated from retained artifacts.
2. The breadth denominator is known exactly.
3. `green` is very tightly constrained and its core formula is recovered with high confidence.
4. The core of `amber/damaged` is tightly constrained:
   `own_dd <= -10% OR r21 <= -3%`.
5. The missing part is an **additive escalation**, not an arbitrary unknown classifier.
6. The missing escalation affects Sentinel severe/recovery thresholds enough that production breadth must remain uncertified until it is recovered or independently proven.

## Recommended implementation rule

Do **not** put the reconstructed damaged rule into production as Sentinel 1.1.

For now:

- certify the Sentinel controller against the frozen daily breadth oracle;
- keep production breadth generation behind an explicit `UNCERTIFIED_BREADTH` gate;
- use this reconstruction as the forensic starting point for locating or solving the final escalation term;
- require exact session-by-session parity with the frozen breadth tape before removing the gate.

The files in this package are intended as a handoff to Claude/engineering, not as a new strategy definition.

# Wealth Core V3 -> V4 -> V5 lineage and affordability defect analysis

Status: research documentation. No V5 backtest has been run yet.

## Executive conclusion

The apparent performance loss from the earlier pre-fix V3 result to V4 was not evidence that fixing the AMZN zero-quantity bug reduced alpha.

The V4 affordability repair introduced a second execution defect. It tested one-share affordability using **cash remaining after subtracting the 10 bp admission cushion**, even though that cushion is released at the next open and the next-open sizing logic uses total actual cash.

That rule unintentionally acts as a **low-nominal-share-price filter** whenever residual cash is near the 10 bp cushion.

Wealth Core V5 is defined to correct this defect while retaining the intended AMZN protection.

---

## Version definitions

### Pre-fix Wealth Core V3

Evidence run:

- GitHub Actions run: `34299991647`
- trigger head: `d4645497b280d6a80579b204f4dde8a022f42593`
- artifact: `10085231668`
- measurement window: `2006-07-31` through `2026-07-31`
- sessions: `5,032`

Economics:

- Median-5 ranking hardening
- 20 slots
- 5% target entry weight
- 10 bp cash/admission cushion
- next-valid-open whole-share sizing
- fractional shares disabled
- one-session dividend lag
- exact quantity determined at next valid open

Known defect:

- close admission required only positive cash above the 10 bp cushion;
- it did not require that one whole share was even affordable at the known close price;
- this produced five consecutive zero-quantity AMZN admissions in December 2015.

Headline 20-year result:

| Metric | Wealth Core | Wealth Core + EX3 |
|---|---:|---:|
| CAGR | 16.749342% | 20.217119% |
| Max drawdown | -50.338058% | -24.502859% |
| Sharpe | 0.825236 | 1.075339 |
| Ending multiple | 22.136883x | 39.752015x |

### Fixed-V3 harness / Wealth Core V4 economics

Fixed-V3 evidence run:

- GitHub Actions run: `34305535605`
- head: `a262817beb6238786af92afea24c34be13a15420`
- artifact: `10087236046`
- replay step succeeded; the workflow was red only because the final persistence step failed.

V4 evidence run:

- GitHub Actions run: `34308443342`
- head: `a2a7d91854b5f4175f75f77e1d9dee9a82d9f768`
- artifact: `10088101728`
- workflow conclusion: success

Important lineage fact:

**Fixed V3 and V4 are economically identical.** V4 invokes the same fixed-V3 experiment harness and adds a V4 identity/assertion layer. There is no separate V4 stock-selection or execution change beyond the affordability repair already present in fixed V3.

Headline 20-year result:

| Metric | Wealth Core V4 | Wealth Core V4 + EX3 |
|---|---:|---:|
| CAGR | 13.904207% | 17.785908% |
| Max drawdown | -50.338058% | -24.502859% |
| Sharpe | 0.724389 | 0.983391 |
| Ending multiple | 13.515076x | 26.417751x |

Execution telemetry from V4:

- close admissions: 423
- completed entries: 423
- next-open blocks: 0
- zero-quantity blocks: 0
- all admitted trades executed: true
- fractional shares: false

So V4 eliminated the original repeated AMZN zero-quantity symptom, but it did so with an over-restrictive close affordability rule.

---

## Original AMZN defect

The original V3 close admission logic effectively asked:

```text
cash - 10bp_reserve > 0
```

That was not sufficient for whole-share execution.

In December 2015, AMZN cost more than $650 per share while available cash was only about $283 in the pre-fix path. The close repeatedly admitted AMZN, but the next-open whole-share sizing correctly computed zero shares.

The intended repair was:

> Do not admit a candidate when it is already known at the close that buying even one whole share is impossible.

That intent is correct.

---

## V4 defect: affordability was measured against the wrong cash amount

V4/fixed-V3 implemented the one-share gate as conceptually:

```text
cash_after_10bp_reserve >= one_share_close_cost
```

But the execution contract says the 10 bp cushion is a **close-time admission cushion released at the next open**.

At the next open, sizing is based on:

```text
execution_budget = min(intended_target, total_actual_cash)
shares = floor(execution_budget / open_share_cost)
```

Therefore subtracting the reserve from the one-share affordability test is internally inconsistent.

The correct logical split is:

```text
# admission-cushion condition
cash - reserve > 0

# one-share feasibility condition
cash >= one_share_close_cost
```

These are two different questions and must not be collapsed into one test.

---

## First causal divergence: AGN1 on 2014-05-23

The first portfolio divergence occurs roughly 18 months before the AMZN episode.

V4 close state on `2014-05-23`:

| Field | Value |
|---|---:|
| Total cash | $232.450008 |
| 10 bp reserve | $214.455910 |
| Cash above reserve | $17.994098 |
| AGN1 close price | $166.92 |
| Intended target | $10,722.80 |

V4 rejected AGN1 because `$17.99 < $166.92`.

But the next-open execution budget would have used the full `$232.45` cash balance. On `2014-05-27`, AGN1 opened at `$167.24`, so one whole share was affordable.

Observed paths:

- pre-fix V3: bought **1 AGN1** share at the 2014-05-27 open;
- V4: skipped AGN1 and eventually bought **14 TQNT** shares instead at a `$15.75` open.

This proves the V4 rule rejected a trade that the stated next-open execution contract could actually execute.

---

## Scope of the unintended filter

V4 produced `51` close decisions with:

```text
WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE
```

They occurred in three clusters:

| Decision date | Number of rejections |
|---|---:|
| 2014-05-23 | 1 |
| 2015-02-27 | 34 |
| 2015-12-04 | 16 |
| **Total** | **51** |

Using total cash, the cash amount that is actually released to next-open sizing:

- **48 of 51** rejected candidates were affordable for at least one share at the known close price including modeled transaction cost;
- only **3 of 51** were genuinely unaffordable from total cash.

The three genuinely unaffordable cases were:

| Decision date | Ticker | Close | Total cash |
|---|---|---:|---:|
| 2015-02-27 | GHC | $986.38 | $285.16 |
| 2015-12-04 | AMZN | $672.64 | $265.66 |
| 2015-12-04 | NVR | $1,705.75 | $265.66 |

Therefore **94.1% of V4's one-share-unaffordable rejections were false under the actual next-open funding contract**.

Examples from `2015-02-27` show the hidden nominal-price threshold clearly. Total cash was about `$285.16`, the reserve was about `$264.97`, and only `$20.20` remained above the reserve. V4 consequently rejected candidates such as KR at `$71.15`, JACK at `$96.69`, CEMP at `$33.12`, and CBRL at `$151.03`, then eventually admitted WEN at about `$11`.

On `2015-12-04`, rejecting AMZN was correct, but the same rule also rejected affordable lower-ranked candidates because their share prices exceeded the small amount of cash left above the reserve. V4 eventually admitted ORI at about `$18.82`.

This is economically equivalent to imposing a temporary maximum nominal share price whenever residual cash approaches the reserve.

---

## Why performance changed so much

The underlying ranking did not change.

Across all `5,032` measurement sessions:

- ranking SHA was identical on **5,032 / 5,032** sessions;
- selected holdings differed on **3,064** sessions;
- first selected-holdings divergence: **2014-05-27**;
- held-count differed on **1,386** sessions;
- Sentinel `A_allocation` differed on **196** sessions;
- first Sentinel allocation divergence: **2015-10-29**.

Once AGN1 was replaced with TQNT, the path became state-dependent:

1. a different security occupied the slot;
2. future exits occurred on different dates;
3. available cash changed;
4. future slot availability changed;
5. later candidate admissions changed;
6. later whole-share quantities changed;
7. the Wealth Core return and drawdown path changed;
8. Sentinel then observed a different Wealth Core path and made different exposure decisions.

That path dependence explains why a seemingly small close-admission rule eventually reduced 20-year CAGR from `16.75%` to `13.90%` in raw Wealth Core and from `20.22%` to `17.79%` with EX3.

The performance difference must therefore **not** be interpreted as evidence that the original AMZN bug was economically beneficial. The comparison is contaminated by the V4 low-nominal-price filter.

---

## Wealth Core V5 definition

Wealth Core V5 keeps all intended V4 economics except for the incorrect affordability comparison.

Required V5 configuration:

- Median-5 ranking hardening
- 20 slots
- 5% target entry weight
- 10 bp close-time admission cushion
- next-valid-open whole-share sizing
- fractional shares disabled
- one-session dividend lag
- exact quantity determined only at the next valid open
- next-open zero-quantity guard retained

Close admission must use two independent conditions:

### Condition 1: preserve the 10 bp admission cushion

```text
cash - reserve > 0
```

A candidate is not admitted if there is no positive cash above the 10 bp cushion.

### Condition 2: known one-share feasibility

```text
cash >= close_price * (1 + COST)
```

A candidate is not admitted if total cash cannot buy one whole share at the known close price including modeled transaction cost.

### Important non-binding rule

Passing the close feasibility check does **not** bind quantity.

At the next valid open:

```text
execution_budget = min(intended_target, actual_cash)
quantity = floor(execution_budget / (actual_open_price * (1 + COST)))
```

The 10 bp close cushion is released into the funding pool at the open.

If an extreme overnight gap or other event makes one share unaffordable by the next open, the existing zero-quantity guard remains authoritative.

---

## V5 acceptance criteria

A V5 implementation is acceptable only if all of the following are demonstrated before performance interpretation:

1. the only intended economic change from V4 is the affordability comparison described above;
2. ranking hashes remain identical to the frozen V4/V3 ranking path;
3. AGN1 on 2014-05-23 is no longer falsely rejected merely because cash above reserve is below one share;
4. the original impossible AMZN admission is still rejected when total cash cannot buy one share;
5. close admission does not bind share quantity;
6. quantity is determined from actual next-open price and actual cash;
7. fractional shares remain disabled;
8. the 10 bp admission cushion remains intact at the close;
9. the next-open zero-quantity guard remains intact;
10. execution telemetry separately reports cash-scarcity skips, total-cash one-share-unaffordable skips, next-open zero-quantity blocks, and completed entries.

Only after those gates pass should V5 performance be compared with pre-fix V3 and V4.

---

## Research interpretation

- **Pre-fix V3:** high-return historical path, but contains a real zero-quantity admission defect.
- **Fixed V3 / V4:** removes zero-quantity AMZN symptom, but introduces an over-restrictive affordability defect that materially changes stock selection.
- **V5:** intended clean repair: preserve the 10 bp cushion, reject only candidates that total cash cannot buy even one share of at the close, and leave exact quantity to the next open.

No claim is made yet about V5 CAGR, drawdown, Sharpe, trade count, or EX3 performance. Those require a fresh frozen full-PIT replay.
# Slot economics forensic decision record

Status: **forensic finding + proposed semantic correction; not implemented, not certified**

Date: 2026-09-07 (America/Los_Angeles)

Branch: `research/median5-slot-forensics-v16`

Related issue: #335

Production promotion: PR #333 remains **NO-GO / DO NOT MERGE** pending resolution of this economic-contract question and a fresh certification of whatever strategy is ultimately chosen.

## 1. Executive finding

The certified Wealth Core / Champion / Caesar-20 / Median-5 lineage contains a slot-admission rule under which any positive amount of available cash can reserve and eventually occupy a full physical portfolio slot, even when the amount is microscopic relative to the nominal target position.

The operative pattern is:

```python
target = min(equity * ENTRY_W, cash)
q = int(target // per_share)
if q < 1:
    continue
# reserve a full slot for q shares
```

This means a nominal 5% Median-5 slot can be occupied by one share or by a position representing a tiny fraction of the intended 5% allocation.

The exact observer-only full-PIT forensic replay preserved byte-for-byte economic-path parity with the certified Median-5 reference, so this is not a replay corruption. The engine executed the frozen contract it was given. The problem is that the frozen contract appears to have encoded an economically incoherent interpretation of what a portfolio slot means.

This issue originated in the original Wealth Core v1 implementation, before LDRC. Commit `447780ce5f65883ab3e34a800e68680c3617dbe5` already contained the cash-clipped sizing rule. LDRC, Champion, Caesar-20 and Median-5 inherited it.

## 2. Direct forensic evidence

The exact forensic replay observed 426 buy fills.

Underfilled admissions relative to the nominal target at the execution open included:

- 141 below 99% of target
- 89 below 90%
- 74 below 75%
- 50 below 50%
- 41 below 25%
- 34 below 10%
- 29 below 5%
- 22 below 1%
- 10 below 0.1%

This is therefore systemic, not an isolated end-book anomaly.

### LLYVK

- decision date: 2024-12-12
- nominal 5% target: approximately $52.31M
- cash available: approximately $221.3K
- reserved shares: 3,098
- executed fraction of nominal target: approximately 0.423%
- held through 2026-07-31
- no sell signal
- no sell attempt
- no failed liquidation
- occupied one physical slot for 407 held sessions
- during 139 full-capacity sessions while LLYVK was held, an otherwise admissible candidate existed if that slot were free

### RCUS

- decision date: 2025-12-22
- nominal 5% target: approximately $59.61M
- cash available at decision: approximately $28.98
- reserved shares: 1
- executed notional: approximately $23.09
- executed fraction of nominal target: approximately 0.00003883%
- held through 2026-07-31
- no sell signal
- no sell attempt
- no failed liquidation
- occupied one physical slot for 151 held sessions
- during all 45 full-capacity sessions while RCUS was held, an otherwise admissible candidate existed if that slot were free

These positions were born tiny. They did not become tiny because of a split, failed exit, stale mark, or data corruption.

## 3. The deeper economic contradiction

The original design simultaneously tries to preserve all of the following:

1. new entries are a fixed fraction of current portfolio equity (4% in 25-slot Wealth Core / Champion; 5% in Caesar-20 and Median-5),
2. no leverage,
3. no routine trimming of existing winners,
4. failed positions may exit below their original target weight,
5. the book may attempt to refill vacancies.

Those requirements do not guarantee that a newly empty slot can immediately be refilled at the nominal target weight.

Example: a 5% position falls and exits when it is worth only 3.5% of current portfolio equity. The sale creates roughly 3.5% cash. If the next position is still required to start at 5% of current equity, the strategy cannot fund it immediately without either borrowing, trimming winners, or waiting for more cash.

The current implementation resolved that contradiction implicitly by allowing the available 3.5%, 0.4%, 0.01%, or even one share to become a full slot occupant.

That is the wrong semantic resolution.

The coherent resolution is to allow a **vacancy to remain a vacancy** until sufficient uncommitted cash exists to fund a genuine new investment episode.

## 4. Proposed economic invariant

This proposal is frozen here **before** examining any counterfactual returns.

### 4.1 Meaning of a slot

An occupied or reserved slot means one properly funded investment episode. A slot is scarce state capacity and must not be acquired merely because one share is affordable.

For an `N`-slot strategy with `ENTRY_W = 1/N`, the decision-time target is:

```text
nominal_target = current_resolved_equity * ENTRY_W
per_share_decision = decision_close * (1 + transaction_cost)
intended_shares = floor(nominal_target / per_share_decision)
reserved_cash = intended_shares * per_share_decision
```

`reserved_cash` is the full whole-share target notional including the buy-side cost. The requirement is not an impossible exact floating 5.000000% allocation; it is the actual whole-share order implied by the nominal target.

### 4.2 Uncommitted cash

Available cash for a new admission must mean:

```text
uncommitted_cash = ledger_cash - cash_reserved_for_existing_pending_entries
```

Receivables do not count until settled. Cash already promised to another pending entry cannot be promised again.

A new slot may be reserved only if:

```text
intended_shares >= 1
and
uncommitted_cash >= reserved_cash
```

If not, no admission occurs, no slot is reserved, and the candidate gains no special future claim. The strategy ranks again on the next decision session.

### 4.3 Pending-order cash reservation

When an admission is accepted, both are reserved atomically:

- the physical slot;
- the decision-time `reserved_cash` budget.

This reservation must survive restart exactly like the pending order and slot reservation.

### 4.4 Next-open execution

The decision-time budget is fixed. At the next executable open:

```text
fillable_shares = min(
    intended_shares,
    floor(reserved_cash / per_share_open)
)
```

If the stock gaps upward, fewer shares may be purchased, but the fill remains bounded by the already-reserved dollar budget. This is a legitimate execution effect and does not recreate the cash-starved slot bug.

If `fillable_shares == 0`, cancel the admission, release the slot, and release the reserved cash.

If there is no executable open, keep the pending order, slot reservation, and cash reservation. Do not allow the same dollars to finance another admission while the order waits.

### 4.5 Explicit non-rules

Do **not**:

- introduce an 80% / 90% / 95% minimum-fill threshold;
- choose any threshold by CAGR or historical performance;
- top up a small position later to make it full size;
- trim existing winners to finance a replacement;
- borrow or permit negative cash;
- give yesterday's candidate priority when cash later becomes sufficient;
- patch LLYVK, RCUS, or any named security specially.

The purpose is to restore a coherent definition of a slot, not to optimize a backtest.

## 5. Why vacancies are economically meaningful

A vacancy is not necessarily an implementation defect. Under the proposed invariant it can contain information about the path of the strategy.

If prior failed episodes returned less cash than a new full-risk episode requires, the book has not yet regenerated enough free capital to make another nominal-sized commitment without selling winners or borrowing. Holding cash and leaving capacity unused is the internally consistent result.

This also aligns with the earlier admission-control research, which found that rapid restoration into a failing opportunity set could be harmful and that pacing replacements / allowing vacancies had coherent defensive behavior.

## 6. Reinterpretation of earlier black-box and statistical observations

This section is qualitative reasoning only. It is not a claim of causal proof and does not use a counterfactual backtest.

### 6.1 Strongly or plausibly clarified by the slot defect

#### Nominal position count vs economic fullness

Earlier black-box work often treated number of held names as a proxy for how full the portfolio was. That inference is unsafe. A one-share RCUS consumes exactly one slot, just like a properly funded 5% episode.

Therefore `20 holdings` does not necessarily mean twenty economically meaningful risk units, and average held-count statistics can materially overstate effective diversification and effective deployment.

#### Effective concentration

The strategy already has a highly asymmetric wealth distribution in which rare long-duration winners become large and fund a disproportionate share of wealth. Microscopic slot occupants amplify that concentration because they count toward the nominal diversification denominator while contributing essentially no capital.

The bug does not create the winner-skew phenomenon, but it can make the actual economic book more concentrated than the name count suggests.

#### Extreme path dependence from small early differences

Prior audits repeatedly found that tiny changes in slot timing, classification, or one early admission could produce large downstream differences in holdings despite similar aggregate position counts.

The slot defect supplies a concrete propagation mechanism: economically negligible capital can acquire a scarce state-machine slot for months or years. That changes who can be admitted next, which changes later vacancy timing, cooldown state, cash, issuer conflicts, breadth populations, and subsequent admissions.

The state machine is therefore capable of becoming path-dependent on a $28 order, not only on economically meaningful portfolio decisions.

#### Caesar-20 vs 25-slot divergence

Changing slot count was not merely changing diversification. It changed a discrete path-dependent admission machine in which any positive cash amount could claim a slot. A microscopic slot consumes 5% of Caesar-20's physical capacity versus 4% of a 25-slot book.

This is a plausible amplifier of why nearby portfolio-size variants can rapidly cease to be nested subsets and why exact slot-count surfaces can look jagged.

It does not prove that Caesar-20's advantage was caused by the bug.

#### Exact portfolio-size / parameter sweet spots

Because slot occupancy controls future state, changing N can alter which candidate receives a vacancy, when cash is available, and whether a microscopic admission blocks a later meaningful one. This can make an N=20 vs N=19/21 surface much more discontinuous than the underlying stock-selection signal.

Therefore precise performance rankings between nearby slot counts deserve less confidence until the slot invariant is corrected and the variants are re-run from the same corrected base.

### 6.2 Breadth and controller implication — especially important

Many controller/breadth features are count-based across held positions. They implicitly treat held names as roughly comparable units of portfolio risk.

That assumption is natural in a strategy intended to open equal-weight positions, but the cash-starved admission rule breaks it.

In a 20-name Median-5 book, each held security has approximately a 5-percentage-point vote in a simple count-based breadth statistic regardless of whether the security represents ~5% of NAV or $23 of NAV.

RCUS therefore can have nearly zero economic weight while still having a full constituent vote in count-based breadth or damage/green classification.

This can plausibly:

- distort damaged/green breadth;
- move discrete controller predicates around their thresholds;
- amplify path dependence in LDRC / Sentinel state transitions;
- make economically immaterial holdings influence exposure decisions made for the entire account.

This is not proof that any particular historical controller transition was wrong because of RCUS or another tiny holding. It is a strong conceptual reason to distrust the assumption that count-based breadth was operating on equal-risk units throughout the certified path.

### 6.3 Stop-density observations

Stop density was previously interpreted as an endogenous measure of opportunity-set failure: many positions stopping in a short interval means the current cohort is failing.

That concept remains coherent, but it also assumes a `position` is a reasonably comparable unit of capital risk. A microscopic slot and a full-sized slot each contribute one possible stop event.

The slot defect can therefore add noise to count-based stop-density measures, although a microscopic position that never reaches its stop contributes no event at all. It is a partial issue, not a complete explanation of the stop-density findings.

### 6.4 Observations that the defect does not explain well

The following findings remain substantially independent:

- the 21/22-session slot-cooldown timing fingerprint;
- the 119/120-session review timing fingerprint;
- one-admission-per-session pacing;
- the high positive skew of long-duration momentum winners;
- the poor average economics of many short-duration failed episodes;
- evidence that the most extreme raw momentum cohort was inferior to more durable moderate momentum;
- the intrinsic hysteresis and threshold path dependence of binary/progressive portfolio controllers;
- PIT reconstruction, factual security-type classification, and corporate-action truth.

The bug can interact with or amplify some of those systems, but it is not a satisfactory root explanation for them.

## 7. What should and should not be considered invalidated

### Still valid unless a separate defect is found

- certified PIT reconstruction work;
- point-in-time identity/security-type factual evidence;
- corporate-action / terminal-event factual evidence;
- the qualitative finding that Wealth Core is a high-skew momentum/compounder engine;
- state-machine timing observations such as cooldown, review age, and one-admission pacing.

### No longer promotion-grade without re-evaluation

Exact economic-performance claims depending on this admission path, especially:

- Champion / Wealth Core performance results using the shared cash-clipped slot rule;
- Caesar-20 performance and its comparison with 25-slot variants;
- Median-5 performance and its claimed superiority;
- exact portfolio-size sweet spots;
- small performance differences between nearby strategy variants;
- controller results whose inputs depend on the realised holdings/breadth path;
- robustness tests that inherit the same physical-slot semantics.

The old certificates remain internally correct descriptions of the exact frozen algorithm. What is in question is whether that algorithm represented the owner's intended economic strategy.

If the slot invariant changes, the corrected strategy is a **new economic candidate** and requires fresh certification. It cannot be silently substituted into PR #333 while retaining the old Median-5 equivalence claim.

## 8. Current promotion posture

- PR #333: **blocked / do not merge**.
- No paper or live exposure has occurred under the proposed Median-5 promotion.
- Do not use existing Median-5 / Caesar-20 headline performance as a reason to select the corrected rule.
- Do not run return-driven threshold searches before the semantic rule is frozen.
- The next legitimate step after owner review is to implement the proposed invariant as a one-factor research variant and re-run the relevant architectures from the corrected common base.

## 9. Core principle

The correction can be summarized in one sentence:

> **A physical slot represents a properly funded investment episode, not the fact that at least one share was affordable.**

Everything else follows from that definition: cash reservation, legitimate vacancies, no double-spending of pending cash, bounded next-open gap fills, and the rejection of arbitrary minimum-fill thresholds.

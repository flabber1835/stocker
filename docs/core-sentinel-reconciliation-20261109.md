# Fixed-decision account reconciliation pilot

## Decision and scope

The owner authorized a bounded financial reconciliation of the existing P00
Wealth Core and original Sentinel, not a policy search. Keep their recorded
decisions, holdings, episode identities, fees, actions and state commitments
immutable. Do not initialize, restore or advance another Core engine. No
production, broker, database, parameter or installed-account change is selected.

Use the 275 recorded closes from 2018-01-02 through 2019-02-05, inclusive.
The funded account starts flat with $50,000 at the first close; its first trade
opportunity is 2018-01-03. No earlier claim or overnight return belongs to it.
In particular, the shadow's Jan 3 ATHM dividend is not an entitlement of an
account which first buys that morning. Extend history only after the fixed
pilot passes the mechanics and independent-review gates below.

The verified implementation base is main
`1e7f4b181fbcb998b3086833ab813c21b1c2ca8e`. The separate legacy research
dependency is pinned to `0bc38753ac1f85b31eb95f560720e6b037e892c5`.
Do not merge that unmerged research branch into current main or describe its
canonical source as current main. Delivery is a feature-branch PR to main.

## Immutable evidence

Admit the original encrypted completed P00 artifact through the existing hosted
reader. Its completed root is
`65637d23029e0817822c169e7d424e00cd75a01703cb22a6aeb1b3f69b390f83`.
The committed daily prefix is 170,330,724 bytes with SHA256
`9f1c682846167a1deafe4496aa4d2e6b803f5650d9f2265b34c691bae56067b2`;
the final checkpoint SHA256 is
`6942c696c752ee35d8a215a6ad138c71a69d9d8dd1337dcaa01519c3e141ea56`.
Use the authenticated append-only checkpoint ledger to recover the daily event
prefix, rather than inferring dividend or merger terms from price movements.

The original BIL fields are normalized daily return-factor pairs, not raw ETF
share prices. Never use them to size persistent BIL shares. Qualify a separately
bound, retrospective Alpaca SIP BIL-only input capture: raw, split and all-adjusted
daily bars for 2017-12-29 through 2019-02-05 and corporate actions queried over
2016-01-01 through collection time. Action query bounds are process dates;
explicitly check economic ex/pay-date coverage and actual payable terms.
The collector may GET market data only, using the existing WSL provider
configuration in place, with finite page/byte/request bounds, redirect refusal,
symbol/domain validation, raw payload hashes and a safe receipt. No account,
orders, positions, activities, database or credential export is permitted.
Capture and cash distributions must qualify before the full share pilot runs.
Missing terms are UNKNOWN, not a zero dividend. This fresh source vintage is
not claimed point-in-time or identical to the frozen research proxy.

The captured Alpaca cash-dividend rows omit payable dates. Supplement and
corroborate their ex-dates/rates using State Street's primary historical
distribution workbook, linked by its ETF distribution document page:
`https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx`.
Bind the exact workbook bytes, URL, collection time, BIL filter, sheet and row
coordinates, ex/record/pay dates, rates and currency. This adds an explicitly
named retrospective issuer source; it does not turn absent Alpaca terms into
known terms. Require matching ex-dates and amounts, positive identified payable
terms and full pilot coverage. Refuse discrepancies or missing terms.
Bind the primary BIL product page
`https://www.ssga.com/us/en/individual/etfs/state-street-spdr-bloomberg-1-3-month-t-bill-etf-bil`
for ticker, CUSIP/ISIN and explicit USD base/trading currency. The workbook's
`DIVIDEND($)` header alone does not establish the ISO currency. This identity
supplement is retrospective evidence, not a historical security-master claim.

## Comparisons and attribution

Freeze four account arms; do not select an arm by its return:

1. **S: exact original scalar control.** Reuse the pinned original account
   operation and original factor inputs. Reproduce every saved economics field.
2. **A: scalar source bridge.** Same scalar operation and fixed decisions, with
   separately qualified actual-BIL price/distribution total-return factors.
   Its only intervention is the defensive input/instrument representation.
   Feed the qualified BIL all-adjusted open/close factors to the unchanged
   scalar Account in an isolated legacy-source subprocess. This retains the
   source's total-return reinvestment convention. Q and P instead hold RAW BIL
   shares and accrue/pay its actual cash distributions; that convention
   difference belongs to the A-to-Q bridge, not to retention.
3. **Q: daily whole-share projection.** Canonical current-main projection,
   original Core marked notionals and opening-dollar intents, explicit defensive
   weight `1-exposure`, original targets, actual raw prices, cash and claims.
   Disable retained targets.
4. **P: persistent whole-share projection.** Identical to Q with canonical
   `held_targets.carry_quantities` and `held_targets.apply` enabled. Carry
   intended quantities for identical causal ownership at unchanged exposure.

S-to-A identifies the defensive source bridge; A-to-Q includes account geometry,
rounding, cash, claims, fees and opening conventions. Q-to-P isolates retention
and its downstream effects. Never attribute all S-to-P differences to retention.
Use exact dollar NAV/event reconciliations before descriptive return metrics.

## Canonical boundary and accounting

The journals contain full Core phase observations but not every full canonical
SessionState envelope. This pilot therefore qualifies the **pure projection and
retention contract**, using explicitly named trace DTOs containing just the
recorded fields consumed by those pure functions. It does not fabricate a
SessionState or claim full `build_execution_plan`, durable authority, database,
protected-order or production-adapter equivalence. It must refuse unsupported
historical input instead of changing the book. Use canonical `project`,
`desired_basket`, ownership/carry/apply and compatible canonical opening sizing;
no handwritten alternative allocation policy. Record exact source hashes.

Use the existing hosted research account/corporate-action primitives where
compatible; do not reuse their private allocation policy. Account bookkeeping
is an offline companion account, never another strategy/shadow book.
At a decision close, sizing NAV is cash plus marked account positions, excluding
unpaid claims. Economic NAV additionally includes accrued claims. Claims become
spendable only on payment, and ownership at the ex-date boundary determines
entitlement. Report stock inventory, BIL inventory, actual cash, claims and
actual trade costs separately, alongside the unchanged Core's reference cash.
The companion account has one spendable cash balance. Its dollars do not have
unique Core-versus-rounding provenance after trades; do not invent cash
subaccounts or present a reference cash allocation as an observed balance.

Use historical idealized raw-next-open fills, sell reductions before buys,
deterministic SID order within side, whole-share buys clipped to fee-inclusive
available cash, and 10bp cost on actual traded notional. Original shadow fees
inform its immutable weights but are not charged a second time to the companion
account. Track desired, actual, filled and remaining quantities separately;
cash clipping must not replace persistent intended quantities with fills.
Reconcile the intended residual each subsequent open under the same fixed plan
rule. Decisions first affect the next source session, after old holdings earn
the intervening overnight gap and actions. No missing/future price interpolation.

Apply authenticated holder-level corporate-action terms to actual account
quantities, not proportionally scaled shadow proceeds. The pilot includes ILG
to VAC at 0.165 shares plus $14.75 per ILG share, and ECYT cash settlement.
Retain and disclose the original $118.45 first-open fractional-cash proxy and
original ECYT Dec 20 convention; these are inherited assumptions, not observed
exchange-agent settlements. Unsupported material retained-target actions refuse
or use a predeclared authenticated exit/new-ownership transition; never guess.

For Sep 4 ILG-to-VAC, apply the authenticated holder-level conversion to actual
holdings and prior intended ILG quantities using the canonical terminal
entitlement primitive. Replace the opening ILG intent by its delivered whole
VAC shares and separately record cash and fractional proceeds. At the next
close, canonical ownership has a different SID, so ordinary carry does not
preserve that VAC quantity: a fresh canonical projection establishes its new
ownership basis. This explicit material-action bridge does not assert that the
scalar-action target projector supports a merger or a new security ID.

Idealized raw-open fills do not establish observed PAPER returns or availability
of current protected LIMIT/DAY fills at 9:31. No intraday/limit proof is claimed.

## Execution and acceptance

All financial imports, canonical calls, account transitions, synthetic financial
tests and restores run only in credential-free, network-disabled GitHub-hosted
containers. Local work is data/AST inspection, input hashing, safe market-only
collection and transport. Pin legacy/current source separately. Reuse encrypted
staging and AES-GCM output transport; plaintext private financial data does not
enter public logs/artifacts. Never forward the research key into a financial
container. Refuse unexpected context/source/input or unknown worker outcomes.

Require: exact S reproduction; identical immutable decision input in every arm;
canonical target reconciliation; separate cash/position/claim/fee identities;
long-only and nonnegative spendable cash; no duplicate entitlement/payment;
correct whole-share action units; no prior-close lookahead; desired-versus-fill
separation; monthly and ownership/exposure-boundary checkpoint continuation;
and independent review of every pilot event/close and summary metric.

Falsifiers must detect removed retention, retention across exposure/ownership
change, future input use, early/duplicate claim payment, negative cash, altered
source/predecessor and corrupted checkpoints. A second stopped hosted process
must independently verify the event arithmetic and commitments before admitting
performance. Nonzero/OOM/UNKNOWN or missing data forbids admission. A favorable
return cannot relax gates; an unfavorable return cannot trigger retuning.

The report states qualification status, exact assumptions, model bridges,
turnover/fees, effective stock/BIL/cash/claim composition, drawdown dates and
fixed-window return. Short-pilot annualization is diagnostic only. Full history
is conditional on mechanics qualification and raw input coverage, not returns.

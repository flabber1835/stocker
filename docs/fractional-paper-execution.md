# Dollar purchases and fractional disposals in PAPER

Owner decision, 2026-11-13, recorded before implementation. Introduce a distinct
opt-in `FRACTIONAL_MARKET_DAY_V1` execution policy. The owner selected whole-share
market purchases as the fallback and preservation of existing hold behavior.
This document does not activate trading. Deliver through a reviewed PR, required
CI, backed PAPER installation and a separate fresh-plan financial activation.

## Qualification of the execution successor

Fractional eligibility is a distinct guarded broker read (`asset_rules`), with
fresh authority checks before and after the read. Revocation must prevent its
result from authorizing a submission. The broker protocol, wrapper and operation
inventory must remain complete and agree on that operation.
The production authority gate must classify every protocol read for preparation,
execution and recovery; wrapper callbacks alone do not prove that the complete
automation path accepts the operation under the correct signed authority.

The changed held-target and target-reprojection modules have new execution
semantics. Their current bytes must not inherit the old structural-extraction
economic identity. Retain the earlier source bytes as qualification fixtures,
authenticated against the existing structural transition and original Git
witnesses, so the historical extraction proof remains independently testable.
Preserve every historical source-map digest; test historical prefixes without
including the newly retained fractional predecessor in those older prefixes.

The retained-inventory serializer must not repeat every changed candidate file
in every historical release. Source profile schema 55 uses one fixed complete
anchor: the independently pinned `aed1a26c335281169c6d8067b1ce2e7de1632053`
predecessor. Store that anchor once and retain single-level override/removal
records. Authenticate the anchor's count and closure before expansion, then
validate every complete historical map against its unchanged independent pins.
There are no recursive references or new compatibility authority. Preserve the
existing fourfold whole-profile compression check and one-million-byte bound;
new candidate edits must not rewrite the historical delta records.

## Authority and scope

Preserve the canonical Wealth Core book, its selection, pending-entry eligibility,
slot priority, stops, cooldowns and cash semantics. Preserve the Sentinel
controller and its inputs. Broker observations remain execution inputs only.
This changes account execution, not the canonical strategy or protected backtest.
The new policy is PAPER-only, long-only and unlevered. Existing account binding,
command journal, UNKNOWN outcomes, backups and WAL remain authoritative.

Every newly submitted order is simple MARKET/DAY with extended hours disabled.
Fractionable BUYs specify USD notional; other BUYs specify whole quantities using
the existing conservative market sizing. SELLs specify exact share quantities.
No native close-position, replace-order, shorting or margin path is introduced.
Regular-session starts/cutoffs retain the current exchange-calendar contract.
A market order has no per-share price ceiling. The whole-share fallback's
buffer estimates cost; native cash-only enforcement remains load-bearing.

## Intent, amount and fulfillment

A command has exactly one positive finite Decimal amount: quantity or USD
notional. Notional is permitted only for a BUY under the new policy. It is never
stored as an estimated share quantity or as zero shares. Persist original amount,
native instrument, policy and ordinary terms before SEND_PENDING. Retrying never
changes these fields or the deterministic client key. A changed amount or
denomination requires explicit resolved supersession and a new revision.

Historical quantity commands and plans retain their original encoding,
fingerprints, quantities, policies and recovery behavior. The behavioral schema
must explicitly represent nullable requested quantity plus notional, enforce the
exclusive alternatives and validate its migration. Fill quantities remain shares.
Order evidence and restored-command adoption preserve the same amount distinction.
Notional order responses can have null requested quantity; no estimated quantity
is inferred from average price. Unknown, contradictory or incomplete native
evidence cannot acknowledge an order or release funds.

The immutable allocation records the authorized purchase dollars independently
of the shares eventually acquired. Positive owned fills determine execution
progress, not a new strategy decision. A partial purchase retains its acquired
shares AND unfinished purchase obligation. A restart or new continuing plan
must not spend the original budget again or silently accept a partial fill as
complete. Broker-reported positions are a reconciliation witness, never a source
from which arbitrary holdings are adopted as intended targets.

For unchanged episodes and exposure, carry execution holdings established by
owned fills and authenticated corporate actions, together with outstanding
purchase intent. Do not rebalance because prices or account/shadow NAV drift.
An entry, actual strategy exit or changed exposure establishes a new allocation
under the canonical priority and one immutable recorded valuation basis. A new
plan may retire obsolete unsent intent, but cannot supersede working or UNKNOWN
commands. Legacy incomplete share intent needs explicit prospective sizing in
the new plan; installation cannot erase it or rewrite an old command.

Fractionable entry budgets use canonical dollar reservations scaled to account
capital and exposure, constrained by retained allocation, cash and costs. Do not
derive a fictional whole-share acquisition and then convert it back to dollars.
Allocation changes retain the existing allocation semantics with documented
reference values. Sizing dollars does not remove canonical price-domain or
entry-cancellation requirements. A fractional-capable broker cannot resurrect
an entry canceled by Wealth Core.

## Cash and serialization

The new projection records a terminal owned-command prefix, its exact shares at
the effective session, and fixed purchase budgets. Its event-sequence boundary
excludes subsequent commands. Revalidation checks that prefix rather than
resampling current positions. For a purchase, the effective share target is the
recorded baseline plus this plan's owned fills; remaining dollars are a separate
obligation. A filled whole-share fallback completes the chosen whole quantity
and leaves its unused dollars as cash, even if eligibility later changes.

Canonical pending-entry and action evidence remains necessary. Use the existing
authenticated prior RAW close reference recipe for allocation, with current
share-unit transforms. Fractional entry budgets use reserved dollars before
whole-share rounding, within the residual Core allocation; the account must
separately prove actual available cash. Non-entry allocation changes use the
plan's fixed decision valuation and nine-decimal share intent before conversion
to cents. Do not request an opening quote to translate a dollar entry into shares.
Final notional funding requires dollars and fee headroom, not a quote-based
estimate of shares. Whole-share fallback still requires its fresh quote.

Keep reductions before dependent increases. Required reductions must positively
settle, and the account/cash equation must reconcile before spending proceeds.
Submit at most one unresolved market BUY across the account. Reconcile its actual
fills and cash before proceeding, including after restart. UNKNOWN and pending
cancellation retain their obligations. No same-plan budget recycling follows
from a balance change, elapsed time or order absence.

Send USD notional in cents, rounded downward within the fixed allocation after
fee headroom. Validate share requests at the supported nine-decimal increment;
never rely on the broker truncating a request. Use exact arithmetic independent
of ambient Decimal precision. Broker minimums and residuals are explicit. A
terminal filled purchase's documented rounding residual is cash, not an endless
top-up loop. A canceled partial purchase has an outstanding obligation; a
successor may spend only its evidenced remainder with renewed cost headroom and
current authority inside the ordinary window. Do not determine reusable dollars
from an inadequately precise average fill price.

## Replacing an already saved next-session plan

Owner follow-up, recorded before implementation on November 13: provide an
attended replacement of the unsent Monday plan when selecting the fractional
policy. Installing the software alone neither selects the policy nor replaces
saved intent. The normal same-policy retry remains immutable.

Extend `prepare-paper-plan --reviewed-informational-dual` with an explicit
replacement request naming the predecessor plan ID and fingerprint, actor,
reason and confirmation. Only a transition from a retained quantity policy to
`FRACTIONAL_MARKET_DAY_V1` is supported. Require a fresh, monotonic same-mode
controller certificate renewal, the exact unchanged decision/shadow record and
publication, backed owner PAPER, disabled/killed automation without a live
leader, and a time before the effective session's regular open. A certificate
renewal gives the successor a distinct deterministic plan identity even when
quantities and cash happen to be identical. No identity salt or historical plan
edit is introduced.

Authenticate and re-derive the predecessor using its saved sizing policy,
independently of the newly selected policy. Require wholly unsent command rows
and history, with no fills, recovered identities or unresolved account commands,
both before broker reads and after complete account/order/cash reconciliation.
Do not use this path to resolve a failed, canceled, filled or UNKNOWN attempt,
or unexplained cash. Preserve all existing financial and backup gates.

Adopt the new account-sized plan, its original sizing/cash evidence, supersession
link and authenticated replacement receipt in one transaction. The receipt
binds both plans, both policies, the unchanged shadow record, renewed certificate,
control generation and exact request. An identical attended retry validates and
returns that successor; it cannot size again or consume the request for another
plan. Old plan economics, command rows and their history remain intact. Ordinary
automation must bind the new configuration and acquire the new plan through its
existing fresh-generation scheduling path; replacement does not enable trading.

The next-plan display reads the saved policy, never the process environment.
For fractional plans it uses the shared allocation calculation over the saved
decision valuation, holdings and retained share/budget basis, and shows proposed
USD market purchases after the existing fee headroom. These are dated estimates:
current asset eligibility, share-unit actions, cash and execution authority are
checked at submission. Do not invent an asset's fractional eligibility or a fill
quantity. Explicitly name the whole-share market fallback. Show exact quantity
reductions and unchanged holds; keep unavailable inputs visible. Update both
overview and detailed previews, including their bounded memo. No quote lookup,
broker write or execution projection persistence belongs in display rendering.

Capture the exact predecessor ID and fingerprint with `current-paper-plan`
before changing its financial authority or selected policy. After the qualified
software installation, keep automation disabled and killed. Select the new
market policy in the reviewed configuration, clear incompatible protected-cap
or debug-window selections, and obtain the fresh PAPER certificate renewal bound
to that configuration. Then perform the attended replacement. Its supported
preparation arguments are:

```text
prepare-paper-plan --through <decision-close> --expect-account <paper-account>
  --reviewed-informational-dual
  --replace-unsent-plan <old-plan-id>
  --replace-unsent-plan-fingerprint <old-plan-fingerprint>
  --policy-replacement-actor <actor>
  --policy-replacement-reason <reason>
  --confirm-unsent-policy-replacement
```

Use the ordinary qualified CLI/runtime entry point. Verify the returned current
plan and retained replacement receipt, then complete the separately authorized
fresh automation binding and release. The ordinary next-plan reader selects the
new generation's future plan; it never relabels the old cycle. If any requirement
refuses, leave the plan history intact and diagnose that evidence. These flags
are not an account reset, a certificate issuer, or permission to submit orders.

## Current asset eligibility

Permanent security identity and native asset identity stay separate from current
trading rules. Record timestamped typed fractional eligibility and revalidate it
at the final submission boundary. False selects whole-share purchase sizing;
missing, stale or malformed evidence defers. A failed lookup is not false.
Changing eligibility never changes an already attempted command's economics.
A known terminal refusal may permit an explicitly revised fallback; timeout,
ambiguous rejection or exact-key absence cannot.

Shares do not carry a permanent acquisition-mode label. A whole-share purchase
can later be sold fractionally; mixed purchases reconcile as one holding. If
fractional eligibility disappears, permitted whole-share reductions can proceed
while an unsellable fractional remainder remains visible. Closing such a fraction
requires positively qualified broker capability; no presumed close exception,
round-up purchase, silent write-off or native liquidation endpoint is allowed.
Do not apply a minimum BUY notional automatically to an exact-quantity exit.

## Corporate actions and recovery

Apply supported share-unit events once over the authenticated effective timeline.
Transform holdings and applicable share obligations; dollar obligations do not
multiply with split ratios. Preserve canonical pending-entry cancellations.
Reuse the existing authenticated rational share-action calculation for owned
fills, so a one-for-thirty split of 0.9 shares is exactly 0.03 shares. Filter
evidence to the command's unit interval; a later recovery does not age the
fixed allocation baseline past its effective session.
Recovered close evidence also retains and rederives the authenticated scalar
events between projection and observation. Its effective share target uses the
same exact rational factors, rather than multiplying a rounded published ratio.
Changed action evidence invalidates that close witness.
Delayed broker share changes remain scoped restrictions, not compensating trades.
Unrepresentable entitlements stay explicit pending authoritative disposition.

Cash in lieu, dividends, mergers, spinoffs and native corrections retain their
existing evidence/classification boundaries. No balance difference manufactures
a sale, dividend or cash-in-lieu event. Unsupported non-scalar actions restrict
the affected security without inventing successor ownership. PAPER limitations
do not justify synthetic fills, shares or cash. Current provider capability and
accepted evidence, not generic documentation alone, govern financial admission.

## Qualification, presentation and transition

Reconciliation also houses the historical action-input decoder. Qualify the
exact before/after reconciliation module as an execution-only source transition:
its action decoding and date/domain interpretation must be byte-identical.
The complete runtime attestation changes; the certified canonical strategy and
economic-input identity do not. Use a sealed exact source pair with unknown
neighbor and guard-removal falsifiers, chained through the existing operation
read witness. Do not widen the old source pair or change its historical fixtures.
This source continuity grants no broker or installation authority.
The oldest retained runtime also compares `core/decision.py` mechanically.
Qualify its exact account-plan-only fractional lot change separately, reverse
only those known bytes for that historical comparison, then run the original
checker. Keep the actual runtime attestation and all canonical definitions
unchanged; unknown neighboring source changes cannot use this comparison.

Display intended dollars, actual acquired shares, unfinished purchase dollars,
cash residuals and blocked share residuals separately. A dust restriction cannot
claim flatness or completed liquidation. Reporting never supplies financial
authority. Preserve actual native fill notices and historical policy labels.

Automation convergence and close verification derive the effective share book
from the immutable projection plus owned command fulfillment. Retain that exact
fulfillment witness in account evidence and rederive it during verification.
Outstanding executable dollars or unresolved purchase evidence prevent success;
less than the one-dollar minimum plus fee reserve remains an explicit cash
residual. A canceled purchase revision may be settled after its exact fills are
accounted for and the original obligation is fulfilled by subsequent revisions;
its cancellation remains in the journal. Freeze predecessor shares at the projection's effective session, even
when recovery reads later corporate actions. Age the resulting share book once
for the observation session, including purchases whose starting share count was
zero. Never age the dollar allocation itself.

Qualify typed amounts/wire payloads, missing qty responses, exact cash arithmetic,
partial fills, cancellation races, accepted-then-timeout, duplicate reports,
restart, stale restore, eligibility changes, split precision, corporate-action
restrictions, no daily turnover, cash scarcity, whole-share fallback, and the
real scheduled callback sequence. Include meaningful guard-removal falsifiers.
Use isolated PostgreSQL and bounded test resources; protect operating/backtest
resources. New policy and changed source identity must be explicitly selected
and independently qualified before any PAPER activation.

Install only at a reconciled handoff with no working or uncertain command; keep
all historical obligations and the same book/account. Rollback after notional
submission must retain notional-capable readers and recovery. A quantity-only
binary cannot safely recover the new journal. Keep the historical protected
limit and whole-market paths for their original records; new-policy selection
does not reauthorize historical transport.

Provider references checked during planning:
[fractional trading](https://docs.alpaca.markets/us/docs/fractional-trading),
[order submission](https://docs.alpaca.markets/us/reference/postorder),
[order lifecycle and replacement restrictions](https://docs.alpaca.markets/us/docs/orders-at-alpaca),
[corporate actions](https://docs.alpaca.markets/us/docs/mandatory-corporate-actions).

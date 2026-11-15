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

### Execution invariants across account plans

Issuer admission and same-issuer priority use positive authenticated purchase
dollars or a positive share target. The issuer record binds the immutable
projection fingerprint. The checks read the dollar obligations from that
projection and keep the same ownership, native identity and reservation gates.
Pre-open coverage and RAW reference collection include carried purchase
obligations even when a security has zero shares and no new opening intent.

Carry acquired quantities separately from the original allocation. Validate the
original allocation before deriving which purchases are unavailable. A later
plan can therefore carry a filled leg alongside a leg with zero fills.

For fractional plans, derive trade cash and reusable purchase principal from
the same exact durable fills matched to the command and native order. The
serialized average checks fill coverage and consistency. It cannot supply exact
cash. Missing fills defer financial authority and contradictory fills refuse it.
Keep the exact native fee cash equality.

Keep scalar-action entitlements as rational share quantities until they can be
expressed exactly. The account may contain a restricted holding alongside
ordinary holdings. Compare an unrepresentable holding against the exact
entitlement. An unchanged pre-action balance or adjacent quantity at the broker
increment can remain a scoped restriction. A different balance still needs
independent reconciliation. Carry the exact pending target separately from the
executable share basket and age it through later authenticated events. A
restricted quantity may never authorize a compensating order or count as flat.

Recheck the original reduction against the fresh reconciled position after
settlement. A filled whole-share reduction can leave a fractional remainder
that still blocks dependent buys. Automation and close verification require
completion of the underlying share and dollar obligations, including dust.

The backed local patch retains the exact installed PR #589 runtime inventory as
an additional predecessor. Its reconciliation change is limited to execution
and result interpretation. Preserve the earlier complete action compiler
witness and verify the economic input definitions and dependencies against it.
The local receipt records the actual source and image and preserves the existing
scheduled PAPER plan.

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

The installed host may queue this attended replacement with
`sentinel_activation_coordinator.py --queue-from-installation <receipt> --mode
dual` and the same five replacement flags. Seal the exact request in the
activation record and forward it only through the fenced preparation step after
signed authority renewal. Reject combinations with other recovery requests.
The coordinator must stop for operator review if the named replacement has
already completed under a different authority.

Host environment validation admits the fractional selection under the same
owner PAPER and required backup prerequisites as the whole-share market policy.
The protected cap and debug window must be absent before installation or
activation can use either market policy.

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

## Current PAPER fill settlement and cancelled purchases

The dual PAPER current-book path reconciles shares from account-bound order
and position evidence. When a fractional plan's owned command reports shares
that its durable fills do not yet cover, reconcile that command against the
accepted PAPER Activity SSE. Restrict the read to the candidate orders' trading
days and exact native identities. Bracket it with the selected account and
validate the order, side, asset, execution time, idempotent execution identity
and cumulative shares before journal publication. This supplies positive fill
facts to the existing observation transaction. Missing publication waits
through the cash guard. The broader historical fill and close capabilities
keep their existing qualification boundaries.

Store a trade's native USD cash impact alongside its immutable fill identity
in the existing journal transaction. Replays must agree with that impact.
Compute the cash equation with the posted amount when supplied and signed
exact gross for fills without that field. Principal for fulfillment is still
the gross executed amount. Use the greater of posted debit and gross when
computing a cancelled buy's reusable budget. The cash activity cursor still
excludes trades from non-trade cash. This charges each trade and any
independently posted fees once. Corrections and busts still require explicit
recovery.

Before completing a notional buy, require the native fill total to cover its
cumulative shares and agree with the requested dollars within the supported
rounding bound. For a complete order the bound is one USD cent plus one
share increment at each reported fill price. A partial or cancelled order
can spend less. A spend above the bound at any stage, or a material shortfall
on a claimed full fill, is contradictory and fences continuation.

After a positively resolved cancellation, the normal scheduler may continue
the current fractional plan inside its execution window. It uses actual
fulfilled shares, exact spent cash, current funding and a new command revision
for the remainder. The rejected purchase itself waits for a new plan. An
unrelated purchase may proceed after reconciliation proves its own authority.
Legacy scheduler refusal rules continue to apply to legacy plans.

A same-plan retry of a cancelled whole-share fallback retains its original
share remainder and evidenced funding ceiling. On a successor with unchanged
ownership and exposure, carry the acquired shares and the unchanged unspent
dollar ceiling. Evaluate eligibility again for a prospective order under that
ceiling. A filled whole-share fallback carries its acquired shares alone,
including when fractional eligibility later becomes available. The new
retained-target basis has a distinct version so existing proofs remain
reproducible.

Qualify the retained source with its exact installed predecessor. Exercise
the production PAPER adapter, ordinary current-book reconciliation, the
cash guard, and sequential submission together with an isolated Alpaca
fixture. Cover delayed and contradictory fill evidence, posted cash rounding,
cancelled revisions, and the unchanged-exposure successor plan.

## Recovery boundaries for fractional PAPER plans

When a positively identified working dollar BUY can explain the direction
and instrument of a position lead, hold transport for the existing bounded
endpoint-lag window and seek the exact order and its native executions.
The notional does not create a guessed share ceiling or owned position.
Require cumulative order and fill agreement before publication, and preserve
the original nonrenewable lag clock across polls, even when the position
quantity moves. An unexplained instrument, direction or expired bound refuses.
Keep the deadline in the existing PAPER-only broker cash activity namespace
so a broker lag does not invalidate the SHADOW input inventory.
Use permanent security and native asset IDs for an exact late fill across
a ticker rename. Retain side, order ID, key, amount, terms and time checks.
Expose the exact owned-fill reader as an optional execution-protocol read
with its own guarded operation. Require explicit PAPER support and a concrete
adapter implementation. Simulators and legacy adapters can omit the reader.

Share coverage and posted cash coverage are separate. An omitted optional
USD trade cash field can be enriched by replaying the same native fill
identity. A supplied amount is immutable. Where posted dollars are omitted,
accept only cash arithmetic proved by exact execution values and the applicable
Alpaca USD posting precision. For a terminal fractional sale, accept derived
cash only when rounding each fill and rounding the order give the same cent
amount without a half-cent tie. An omitted amount on a completed dollar BUY
must also agree with the requested dollars. Never use the account balance
to invent a ledger entry. Keep cash and separately posted fees single-counted
and keep complete posted cash verification exact. See [Alpaca activity events](https://docs.alpaca.markets/us/docs/activity-sse)
and the [Alpaca Customer Agreement](https://files.alpaca.markets/disclosures/library/AcctAppMarginAndCustAgmt.pdf).

Corporate-action restrictions must bind to the relevant owned position or
attempt interval. Match a resolved event by permanent security ID. Use a
ticker only where the event lacks that identity, and preserve the distinction
between a transport restriction and a proved explanation for a changed
quantity. An arbitrary quantity mismatch cannot be cleared by a material
action marker. The cash bracket for market funding can accept a stable
scoped restriction after checking both observations, reconciling cash against
the immutable plan baseline, and checking reduction dependencies. Account-wide
integrity and close verification keep their full clean-book requirements.

An exact, terminal share-denominated market fill can exceed its buffered
budget. Preserve the acquired shares and record the overrun as explicit
execution evidence with zero remaining spending authority. The overrun
does not invalidate confirmed owned fills or prevent an authorized successor
from reducing its target. Notional contradictions and UNKNOWN outcomes
continue to fence transport.

A current plan with authenticated continuing purchase dollars requires a
projection even with no new opening intents. This includes unfinished BIL
allocations when Core exposure is zero. Reconcile and request ordinary
execution inside the original window when that projection is absent and no
command ever crossed transport. An already attempted plan missing its
projection refuses. Raw share equality cannot complete the dollar obligation.
If the original window elapses before projection, retain its authenticated
continuing budgets only when ownership and exposure permit ordinary carry.
On recovery, a symbol's unavailable RAW reference must leave independently
actionable legs eligible. If all actionable work is exhausted, the remaining
unavailable legs stay explicit and the cycle follows its ordinary retirement
rules. Account-wide evidence still governs every send.

At a confirmed cash shortfall, keep a proven unsent order and its allocation.
Other independently affordable candidates may proceed under their own fresh
funding and issuer checks within the original deadline. Preserve the priority
of candidates that can be funded, the writer lock and one unresolved market
BUY. Generic authority failures and indeterminate sends cannot use this path.

The backed application handoff fingerprints the persisted posted fill-cash
records and the durable position-leading order deadlines. Previously issued
receipts keep their encoding and are interpreted with their original scope.
Qualify the exact successor against the installed source with composed
endpoint lag, restart, affordability, corporate identity and accounting
falsifiers before the backed PAPER handoff.

## Recovery across transport, share units, and provider identity

An order remains uncertain after any indeterminate transport attempt. A refusal
before a later retry proves only that retry did not reach transport. Record the
first uncertain outcome and let exact, account-bound recovery decide it.
Positive exact and open order evidence can identify a pending notional command
whose own native order ID has yet to be recorded. Recognize a matching,
position-leading observation under the same nonrenewable grace clock. Do not
derive ownership or authorize transport until order and fill evidence agree.
Use the native fill identity when validating the union of new and durable
executions. Equal price, quantity and time can belong to distinct fills.
Advance verified fills while cancellation is pending, preserving the
cancellation fence until a terminal broker state. A still-working native
status with a positive cumulative counter retains the corresponding partial
progress rather than returning the command to zero-fill acknowledgement.

Share-only fractional execution needs the same verified next-open actions and
effective-session target projection as an opening purchase. Re-enter the
original execution window for a provably unsent plan with no projection,
including a pure reduction. A missing projection after transport refuses.
Reserve raw convergence compatibility for historical plans that were governed by
that contract. A current plan can certify convergence only in its verified
share units, including when no dollar obligation exists.

Resolve instrument identity separately from current trading availability. A
positively identified inactive, unavailable or nontradable BUY is an explicit
security-level deferral. Preserve its obligation and let independently authorized
orders reach the executor, including reductions. Account, source, authority or
contradictory native identity failures still refuse. For a reduction, use the
current position's native instrument ahead of terminal order history. Preserve
the final fresh eligibility, issuer, cash and clock checks.

Treat historical order symbols as aliases only after permanent security and
native asset IDs agree with current authenticated reference evidence. Require
the current issuer relationship and any standing issuer reservation to agree.
Check conflicting historical native asset IDs when the security has a current
position, open obligation or nonzero attributed balance. A closed position's
journal is retained even if the security is no longer selected. For supported
sequential scalar events, recognize the exact book after any applicable prefix
of the actions as an intermediate posting restriction. Preserve the final
entitlement and continue refusing unexplained differences. A reconciliation is
clean only when it has a complete RUNNING account result and no restrictions,
foreign activity or unresolved work.

For a supported, directional merger action, reset the acquired security's
economic history. Preserve the existing acquirer's price history when the
provider identifies it as the receiving instrument and independent current
asset identity corroborates continuity. Ambiguous parties and changed or
unresolved native identities keep the conservative quarantine. Correct the
prospective input publication path without rewriting retained generations or
changing Wealth Core or controller rules.

Store new posted fill cash inside the existing PAPER cash-activity namespace.
Resolve the historical fill-cash namespace as an immutable compatibility read,
exclude its rows from SHADOW proof inputs, and preserve the installed
operational SQL contract. Keep one record per fill, including on replay.
Backed handoff fingerprints both encodings. Semantic restore validates every
retained posted amount against its exact fill, owned command, order, side and
price. Missing optional cash fields remain governed by the existing runtime
coverage rules. An orphan, duplicate, or contradictory sidecar fails restore
qualification. The validation is read-only.

## Qualification, presentation and transition

The backed release includes the already deployed November 13 close, opening
evidence and zero-share retry fixes. Retain their original whole-share display
and authority rules for saved protected-limit plans. Their held-share retry
basis keeps schema version 2. New fractional fulfillment evidence uses version
3 so that the historical retry payload retains its meaning. When replacing an
unsent plan, keep its authenticated retry intents and original holding basis,
then size those openings under the successor's selected policy.

Admit the exact installed November 13 source as a retained predecessor. Keep
the existing verified source maps from both branches and the compact inventory's
fixed anchor. Only the combined release's exact source may use that admission.

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

## Order-amount migration and interrupted installation recovery

On the first PAPER install, the v2-to-v3 command migration and the repeat feed
DDL advanced the independent DDL witness by 68 events. The unchanged
OBSERVATION and MIRROR prefixes correctly refused the resulting inventory.
The canonical installer now proves an already current feed schema by read only.
It still installs a missing or older feed through the existing explicit path
when operational evidence is absent. A v2 database with established coverage
must already have the exact current feed catalog before changing command DDL.

During v2-to-v3 command DDL, use the existing atomic operational coverage
handoff. With operational evidence installed, require disabled and killed
control, invalidated lease and the existing financial writer exclusion. Lock
both inventories and validate the authenticated prefixes before the three exact
ALTER statements. Validate the v3 catalog and ledger before transferring those
prefixes. Preserve each prefix body and sequence boundary or roll the entire
migration back. A current schema retry does not reseal stale evidence.

For the earlier failed installation, use the separately namespaced order-amount
witness from the paused pre-migration backup. Require the exact v2 behavioral
and feed catalogs, installed operational schema, durable fence, and complete
signed prefixes. Bind the existing streaming source-byte proof and additionally
bind every historical command and its physical tuple. At the v3 successor,
compare the same command bytes with only the new notional column projected out,
and independently require that column to be NULL for all historical commands.
Require the exact 68-event transition, unchanged source, authority and prefix
coordinates, and lock the witness and watched sources through the coverage commit.
Transfer only the two derived signatures and inventories. An extra DDL event,
changed command or source, stale witness, or missing pre-install proof refuses.
Use the existing supervised activation after recovery. Preserve the exact signed
PR #588 executable as an additional retained predecessor in the source profile.
Seal the full repaired executable and keep all previous source maps and the
fixed compact anchor. This source proof grants no trading authority.

```bash
bash scripts/sentinel-restore-drill.sh --physical-only --backup EXACT_PRE_DDL_BASE --order-amount-witness ABSOLUTE_NEW_WITNESS
python3 scripts/sentinel_order_amount_coverage_recovery.py --installation-receipt EXACT_RECEIPT --witness ABSOLUTE_NEW_WITNESS --confirm-witness-sha256 FILE_SHA256 --backup BASE_NAME --output ABSOLUTE_NEW_TRANSFER_RECEIPT
```

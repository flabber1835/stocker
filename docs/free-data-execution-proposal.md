# Free-data protected execution proposal

Status: execution redesign selected, implementation pending qualification,
2026-10-19. The operator authorized fixing, qualifying and deploying paper
execution, selected free data, and explicitly allowed capped DAY BUYs submitted
between 09:31 and 09:40 ET to remain working until the regular close. The maximum
price band remains an operator decision. This document does not itself grant
native transport or deployment authority; the ordinary release and execution
gates still apply. The operator does not purchase SIP. The unpublished SIP-only
latency candidate is not a selected release. Production remains on its installed
IEX execution policy.
The running historical backtest and its inputs remain untouched.

## Finding

Paid SIP is not documented as a prerequisite for submitting an Alpaca order
with a client-chosen limit. Alpaca's Basic market-data plan is free and includes
real-time IEX. Its paper specification describes fills against current NBBO
even for paper-only accounts with IEX data entitlement. This supports separating
client-side quote availability from the broker's execution price checks; it
does not certify a new order policy for Sentinel.

Sources: [data plans](https://docs.alpaca.markets/us/docs/about-market-data-api),
[paper specification](https://docs.alpaca.markets/us/docs/paper-trading),
[create-order reference](https://docs.alpaca.markets/us/reference/postorder).

The published order table lists whole-quantity LIMIT/DAY without the sales-contact
qualification; this account's support remains unverified. The current
[order-type table](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
marks IOC and OPG with a sales-contact qualification. The
[Elite features](https://alpaca.markets/elite) list IOC and opening-auction
orders, and the [paper tutorial](https://alpaca.markets/learn/start-paper-trading)
restricts OPG/CLS to Elite Smart Router users. Account support must therefore be
confirmed independently; generic API enum values do not prove entitlement.

## Proposed protected BUY policy

Retain the same Wealth Core securities, controller exposure, canonical dollar
intent priority, BIL sleeve, paper account and whole-share envelope. Execution
alone derives broker order terms. No broker outcome feeds back into either
strategy or controller, and no missing BIL quote changes BIL into cash or another
security in the intended book.

For new BUY increases, use the authenticated prior closed-session RAW close as
an explicitly historical reference. Existing `execution.feed_inputs.marks`
provides raw stock and BIL marks. Bind the source/publication, permanent security
and native asset identities, observed decision session and applicable share-unit
evidence. This is a validated observed close, not a claim that the provider can
never correct history. Do not use adjusted/signal prices or describe the close
as a current quote. Proven splits require the inverse price adjustment to the
effective share units. Known unsupported actions or unresolved applicable share
units restrict affected securities; absence of an optional pre-open certificate
is not a blanket refusal.

Derive a fixed, tick-rounded BUY limit from that reference and a reviewed price
band. Derive whole quantity from the canonical priority budget at that maximum
price, including explicit fee headroom. Persist the policy, reference, limit,
quantity, TIF and maximum reserved spend before transport. A fill below the
limit leaves cash unspent; a gap above it deliberately permits no fill. Never
raise the limit automatically or resize an already transported command to chase
a price. The price-band and fee-bound values remain review decisions.

Maintain fresh account availability, cash, settled-sale evidence, native asset
identity/tradability, control/kill, lease, certificate, rollout, publication and
final execution-clock checks. Preserve 09:31 ET start and 09:40 ET new-increase
submission cutoff. Existing exact-quantity market reductions can retain their
current path; necessary reductions must still be positively FILLED and cleanly
reconciled before their proceeds can fund an increase.

## Approved standing-order lifetime

A DAY limit can remain working until it fills or the broker confirms a terminal
state. Alpaca normally cancels an unfilled DAY remainder after the closing
auction; the appliance must not assume an EXPIRED status exactly at 16:00.
Current recovery reconciles orders and does not provide a
09:40 cancellation sweep. A client-side cancel request cannot guarantee an order
will stop filling during appliance failure, network loss or a fill/cancel race.
The existing cutoff prevents new submissions; it is not broker-enforced expiry.
DAY limits make later fills an ordinary possibility rather than an exceptional
delayed market fill. The operator explicitly approved this lifetime on
2026-10-19. Keep 09:40 as a cutoff for new submissions and never widen a durable
limit. No 09:40 cancel sweep or broker-enforced 09:40 expiry is claimed.

If already-submitted orders must immediately stop resting, prefer LIMIT/IOC only
after confirming the account's native support. Do not silently fall back to DAY.
IOC still permits partial/zero fills, uncertain acknowledgements and network
delay; it does not prove every fill timestamp precedes the client's cutoff.
Opening-auction orders also require different pre-open authority and cannot be
submitted at 09:31: Alpaca rejects OPG submissions after 09:28 until 19:00 ET.
They are not the default-account solution for this existing schedule.

## Durable funding and recovery

Current shadow priority reservations are not a broker cash-reservation ledger.
Derive durable remaining obligations from immutable owned order terms and
positively attributed fills. Reserve remaining quantity times the limit plus
the applicable fee bound. UNKNOWN submit/cancel and CANCEL_PENDING retain their
reservation. A cancel request, timeout or negative lookup never releases money.
Release only against positive terminal evidence and reconciled partial fills.
An unchanged command key must never describe a different limit or TIF.

Resting BUYs may reduce broker buying power below cash. Current paper admission
rejects that difference. The new contract must authenticate native reservation
and settled-cash semantics, avoid subtracting the same reservation twice, and
derive a conservative usable amount bounded by both native buying power and
cash after owned obligations. It must not infer cash flows, assume sale proceeds,
permit margin or conceal unexplained differences. Missing evidence refuses.

Fees need an explicit bound; principal alone is not total debit. The
[current fee schedule](https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf)
and account terms determine applicable charges. Paper simulation does not prove
live fee behavior. This proposal remains paper-only.

## Selected implementation contract

These decisions precede source implementation. Select the new profile explicitly
with `SENTINEL_PAPER_BUY_POLICY=PROTECTED_LIMIT_DAY_V1`; its required integer
`SENTINEL_PAPER_BUY_CAP_BPS` has no implicit production value and accepts integers
from 0 through the reviewed ceiling of 500 basis points. A cap without the
explicit profile selection refuses, rather than appearing to protect MARKET
orders. The operator's
price-band answer is required before selecting the release configuration.
Retain the legacy market policy and its IEX evidence decoding for historical
commands. A profile change cannot reinterpret an already transported command.

### Release configuration channels

Persist the selected policy and cap in the release checkout's literal `.env`
before sealing an activation request. The separately supervised activation owner
reloads that file; a temporary installer-shell override is not durable release
configuration. A changed `.env` requires a new reviewed activation request.

The one-time retired-Stocker environment converter deliberately leaves both
BUY-policy inputs unset, with an explicit reason in its complete whitelist.
A legacy file cannot select a financial execution policy or price band for a
new deployment. This converter is not the existing Sentinel release `.env`
copy path; ordinary upgrades preserve an already reviewed selection. The
operator must explicitly select the new release policy/cap before activation.

The ordinary `sentinel` CLI receives the same nonsecret
`SENTINEL_PAPER_BUY_POLICY` and `SENTINEL_PAPER_BUY_CAP_BPS` Compose inputs as the
authorized CLI and automation services. The installer's `current-paper-plan`
reader also passes both values explicitly from its selected environment,
including empty legacy values. That broker-free reader verifies the newly
signed execution configuration and must compute the same
`sentinel.paper-execution-config/2` identity and cap as certificate creation,
installation, activation and execution. This propagation grants no broker
credentials, runtime marker, signing key or execution permission. The panel and
shadow worker do not verify execution-policy identity and receive no new
execution-policy inputs; Wealth Core and the controller remain independent.
The offline issuer signs the exact candidate's authenticated bindings and does
not infer a different policy from its own credential-free process environment.

The policy's canonical fingerprint binds the cap, whole-share rounding, DAY TIF,
simple order class, extended-hours false, 60-second start delay, 600-second new
submission cutoff, historical raw reference recipe and a fixed USD 1.00 cash
headroom for each BUY. This headroom is an execution reserve, not a claim about
the maximum fees in live trading. This profile admits only the certified Alpaca
paper endpoint; the paper specification excludes regulatory fees. Ordinary cash
reconciliation remains based on actual attributed paper fills and activities.
No live fee or settled-funds qualification is inferred from it.

### Historical reference and Core allocation

Use a separate typed `PriorCloseReferences` model, never an `OpeningPrices` or
`RegularQuotes` instance. Bind the exact plan fingerprint, prior decision and
effective sessions, publication/snapshot/manifest identity, raw values, security
and symbol identities, and action evidence. Re-read each required raw source row
under the authenticated publication pin. A self-consistent hash of retained
marks, or reproduction of a zero provisional opening target, is insufficient to
authenticate a new limit price. Retained v1 sizing authority remains unchanged.

For a security with evidenced effective share multiplier m, divide the raw
reference by m. Compute L by rounding DOWN reference*(1+cap_bps/10000), using
USD 0.01 ticks at prices >=1 and USD 0.0001 below 1; reject a nonpositive result.
Freeze the limit and the reference/policy proof in the execution projection.
All BUY increases, including BIL and existing-name increases, require these
protected terms. SELL reductions keep their existing exact-quantity market path.

Opening dollar intents are not jointly cash-reserved at admission. Allocate a
shared reference-basis Core budget explicitly: C=target_exposure*account_nav;
H is the sum of action-aged, non-opening Core target shares times their
action-aged raw references, excluding BIL and zero targets. Require H<=C and
start A=C-H. In canonical slot order, reserve B_i=min(account_scale*intended_i,A)
and deduct the FULL B_i from A, including an unavailable or deferred entry.
Whole entry quantity is floor(max(0,B_i-1.00)/L_i). Keep the existing distinct,
unheld, zero-provisional-target requirements. No entry can consume another
entry's reservation or the BIL sleeve. This calculation makes no assumed sale
credit and never uses broker state as a strategy/controller input.

Missing price coverage is a BUY availability restriction. Keep every existing
non-opening action-aged target unchanged. A missing entry reference reserves its
full slot allocation and records an explicit pending quantity calculation. If a
missing non-opening Core reference makes H unevaluable, record
`CORE_REFERENCE_UNAVAILABLE`, retain provisional opening quantities of zero with
explicit pending evidence, and authorize no BUY from that projection. Do not
invent H, a reference, or a sale. Missing BIL pricing restricts its BUY without
turning the intended sleeve into cash. The executor defers only the unavailable
BUY before command creation; exact market reductions retain their ordinary
authority. Contradictory source identity, action units or H>C remains an integrity
refusal. An absent price and contradictory evidence are different conditions.

An unavailable opening calculation is never convergence. Preserve the pending
entry IDs even when provisional executable quantities are zero. Once actual
in-flight orders are positively settled, recovery supersedes an immutable
reference-unavailable projection with an explicit incomplete reason; it does
not report a completed basket or reprice the old plan. The next ordinary
decision may produce a new projection. Recovery continues to reconcile working
DAY orders after 09:40, and the cutoff never licenses another late BUY.

The cold authenticated dual sizing proof also exposes canonical shadow equity
as a detached scalar. The fresh pre-mutation guard compares it with the
protected allocation's scale denominator and recomputes the bounded allocation
arithmetic. This rejects a caller-chosen scale without restoring the complete
Wealth Core state for every order. The scalar changes no canonical book state.

This is an execution allocation at historical references, not a guarantee of
constant live mark-to-market exposure. Existing held/BIL target quantities retain
their action-aged plan semantics. Their BUY deltas still require a fixed limit,
the actual cash proof and the funding reservation below. An unaffordable whole
leg defers rather than changing its durable quantity or selling another name.

### Budget-constrained limits for fixed share targets

Preserving a fixed quantity while multiplying its reference by the full price
band can make a fully invested basket unaffordable. At 100% BIL this can refuse
the entire purchase even with a valid raw reference. Keep the target quantity,
and tighten its limit at projection creation to its allocated dollar budget.

For each positive non-opening target Q, let B=Q*action-aged RAW reference for a
Core name, and B=(1-target_exposure)*account_nav for BIL. Set the fixed BUY limit
to floor_tick(min(raw_reference_cap,(B-1.00)/Q)). Thus Q*L+1.00<=B. Record the
fixed-leg kind, Q, B, raw cap and final limit, and validate the budget against the
plan and its authenticated raw/action evidence. Opening dollar intents retain
their existing cap-first whole-quantity sizing from the remaining Core budget.
Never change existing held or BIL targets merely because their cap is tighter.
A nonpositive affordable limit is a BUY-only availability restriction; reductions
retain their original quantity. A zero target needs no BUY terms.

The operator's percentage is a maximum, not a promise that every order uses the
whole band. The budget can tighten a limit below the reference; that order may
rest without filling. Limits never widen after creation and there is no claim
of guaranteed fills from historical data. The sum of fixed full-target maxima
and reserved opening budgets remains bounded by the planned Core/BIL allocation.

The private complete-basket timing scenario explicitly assumes marketable fills
at each submitted BUY limit, the maximum permitted principal, and reports that
assumption. It is a software cost/timing test, not evidence that the real market
will trade at that price. Separate provider tests cover nonmarketable DAY orders
remaining working with their native reservation and no synthetic fill.

### Immutable terms and explicit schema migration

Add a frozen `OrderTerms` value to `Command` and `BrokerOrder`, appended after
existing fields. It binds order type, TIF, Decimal limit or null, order class and
extended-hours flag. Canonical versioned serialization retains the exact wire
economics. Unsupported foreign terms remain visible as typed evidence; missing
reported terms cannot authenticate an owned order. Owned submissions permit the
existing MARKET/DAY terms or BUY LIMIT/DAY/simple/regular-hours terms. LIMIT
requires an explicit certified capability and never falls back to MARKET.

Keep CommandIdentity v1 and every historical client key unchanged. Store terms
as immutable command economics; different terms require a new revision. Carry
them through dispatch, pre-transport refusal proofs, native asset-ID routing,
acknowledgement checks, exact-key recovery, adoption, reconciliation and rebuilt
command comparisons. Bind policy/reference provenance through the authenticated
plan projection. New observation and compact-witness versions include terms;
old observation bytes, versions and digests remain unchanged.

`sentinel_commands` belongs to the closed behavioral catalog. Add a genuine v2
migration rather than silently extending its DDL: preserve v1 constants and
recognized catalog fingerprints, validate exact v1 core and Stage-4 catalogs,
require fenced automation/no live leader, then add non-null JSONB `order_terms`
with canonical historical MARKET/DAY default and append ledger row 2 atomically.
Use the existing advisory schema lock and two-second relation lock timeout.
Validate exact v2 catalogs before committing. Runtime requires v2 and performs
no repair. New/legacy installation runs the unchanged v1 bootstrap followed by
the same explicit v2 migration in its transaction. Missing ledger rows, partial
columns, unknown versions/defaults/constraints and unfenced upgrades refuse.

### Closed retained-source successor

Expand the opening successor's exact reviewed scope to these 29 existing
Sentinel modules, using hashes from verified main `1e1db91b` and the already
authenticated predecessor manifests:

```text
authority/validation.py                 automation_runtime.py
dual_plan_authority.py                  dual_reconciliation.py
execution/alpaca.py                     execution/alpaca_asset_id.py
execution/certification.py              execution/commands.py
execution/contract.py                   execution/executor.py
execution/guarded.py                    execution/journal.py
execution/opening_prices.py             execution/opening_sizing.py
execution/reconcile.py                  execution/recovery.py
execution/target_reprojection.py        feed/readers.py
identity.py                            idle_leader_upgrade.py
paper/execution.py                      paper/targets.py
paper/validation.py                     retained_input_namespaces.py
rolling_runtime.py                      runtime_admission.py
schema.py                              semantic_source_basis.py
structural_verification.py
```

The additions are exactly `opening_latency_upgrade.py`,
`execution/protected_limits.py` and `execution/protected_funding.py`. Admit this
set together only when all three current hashes match the closed descriptor;
the checker's own hash retains the existing normalized self-pin rule. Missing,
modified or additional neighboring modules refuse. Preserve all 16 earlier
descriptor files and all 21 complete predecessor witness fixtures byte for
byte. Expand only their scope projection inside the new descriptor. Neither
Wealth Core sources nor the retained book's economic identity changes.

This is source compatibility for reading retained state. Its authority effect
remains `NONE`: it grants no execution certificate, policy, migration approval,
cash permission or broker authority. The exact protected funding cursor is
execution evidence; unknown cursor names retain their ordinary economic
classification. Existing fresh authority checks and the explicit behavioral v2
migration remain necessary. The development generator validates this closed
input scope and requires an explicit `--seal` to write final pins, after every
participating source file is frozen. Read-only input checking does not reseal
the descriptor. No permission or financial verdict is cached by this mechanism.

### Conservative funding cohort

Preserve the existing strict account/quiescence and cash-activity checks. Do not
declare an arbitrary buying-power deficit to be an explained broker reservation.
Before the first protected BUY, earn one immutable funding basis for this plan
using the existing clean, COMPLETE, quiescent cash evidence after every necessary
reduction is positively FILLED. Bind deployment, plan/projection/policy, account
identity, cash/BP/multiplier, observation identity and the explicit evidence
variant below. Persist it under the existing writer lock before any protected
transport.

The exact `protected-buy-funding:v1:` processed-session prefix is execution
evidence, alongside the existing broker and target-projection namespaces. Exclude
it from immutable strategy input fingerprints and retained economic context.
Unknown prefixes remain economic inputs. This classification grants no broker
authority and changes no Wealth Core or controller state.

The journal is the reservation ledger. For this initial profile, conservatively
charge the FULL original limit principal plus USD 1.00 headroom for every
protected BUY promise in the cohort, including PLANNED, SEND_PENDING, UNKNOWN,
working, filled and canceled orders. Do not recycle partial-fill savings or a
terminal order's unused allowance within the plan. A positively proven unsent
SUPERSEDED command can release its allowance. A new plan can earn a new basis
only through the ordinary quiescent cash proof. This deliberately conservative
rule avoids releasing money against a lagging account endpoint or fill report.

For the current exact command, exclude only its own allowance from the other
charges; also derive LIVE_other from each other potentially live BUY's remaining
quantity times its immutable limit plus headroom. Require the current full
maximum cost <= min(fresh buying_power, max(0,fresh cash-LIVE_other),
max(0,basis_cash-other_charges)). Positive terminal evidence removes the live
remainder, while its original gross charge stays. A fill reflected in cash but
not yet positively reconciled can temporarily make this bound too conservative;
defer and recover rather than assume that the order filled. Never subtract local
reservations from native BP again.

There are two explicit durable funding evidence variants. The existing
`sentinel.protected-buy-funding/1` activity-backed variant retains its exact
shape and semantics: before each submission ingest a fresh complete accepted
native activity interval and require its identity, scheme and balance to match
the basis. An activity-capable adapter with an unavailable, incomplete or
contradictory interval cannot fall back to another variant.

The supported, composition-certified `ALPACA_PAPER` adapter deliberately has no
accepted account-cash activity capability (execution contract section 5.4).
For that exact certified composition only, use a separately tagged
`sentinel.protected-buy-funding/2` plan-cash variant. It grants no cash-activity
capability, no event-set identity and no finality claim. Select it from the
actual certified broker and its disabled activity capability, never from a
caller-supplied mode or a failed activity request. Bind this selection to the
basis and verify the same composition/capability before every submission.

Earn this basis with the unchanged clean COMPLETE quiescent observation,
strict account check and `_cash_authority_or_refuse(activity_state=None)`.
Require no prior nonsuperseded BUY. Its fixed cash ceiling is no greater than
both actual cash and the exact immutable plan cash plus positively reported,
durable same-plan SELL fill principal. Do not credit the ordinary USD 1.00 cash
comparison tolerance into this ceiling. No new deposit, later sale, balance
increase, cancellation or fill saving can increase or renew it. Every original
BUY maximum keeps the gross charge described above through terminal states.
Before every POST retain fresh account cash, buying power, flags and 1x checks,
the remaining-live-promise bound and the fixed gross cohort ceiling. Cash above
the basis by more than the existing USD 1.00 tolerance refuses; lower cash can
only restrict spending. This check does not infer an attributed withdrawal or
fill, and the ordinary settled cash equation remains mandatory in recovery and
before a future plan earns a basis. A restart with working orders still fails
the existing quiescent increase gate.

Without accepted native activity identities, offsetting deposits and withdrawals
are not detectable as an event-set change. This is the existing Alpaca
no-activity cash contract, not a claim of account-activity completeness. A stale
account endpoint cannot release a same-plan promise because its gross charge
survives independently of that endpoint. Complete foreign-order reconciliation
and fresh broker checks remain required; concurrent external actors have the
same limits as the existing Alpaca cash path. The broker enforces its native
available funds independently. Do not infer atomic account completeness or
promote the quarantined SSE decoder from these monetary bounds.

Keep the ordinary complete clean reconciliation before the basket and native
1x cash availability checks at each order. Do not subtract local reservations from BP
again. Keep fresh identity/status/flags/multiplier checks and forbid BP above
cash under the existing tolerance. Any other-plan in-flight obligation or an
unbounded legacy BUY refuses new protected transport. Never credit subsequent
sales, deposits or balance changes to the cohort. UNKNOWN/cancel requests retain
the full allowance; no lookup absence or elapsed time is terminal evidence.

Resting orders remain recoverable through the independent recovery path. New
increase attempts continue to require the ordinary quiescent proof; they may
defer while an earlier DAY order rests. This first profile does not relax the
settlement contract to complete later legs during a nonquiescent restart.

A protected submit may return a typed, positively reported order receipt with
cumulative filled quantity and average price. After validating the exact client
key, native asset, side, quantity and terms, persist those reported counters
with the ACKNOWLEDGED command before considering the next leg. This reduces its
live remainder only by positive broker evidence; its original gross charge and
fee allowance remain. A missing receipt preserves the old conservative hold.
A contradictory or unusable receipt is UNKNOWN. Never infer fills from a cash
change, elapsed time or an expected matching price. Independent complete
reconciliation and the normal fill journal still own terminal settlement, cash
certification, close proof and fill notifications. A submit receipt cannot make
the automation cycle succeed by itself. Legacy MARKET/DAY outcomes retain their
existing behavior.

The next reconciliation can see the same cumulative order fill while its
position endpoint still lags. Receipt counters must retain the existing bounded
lag treatment. For an owned protected BUY entering reconciliation as
ACKNOWLEDGED with positive counters, read only its indexed command-event history
for the unique positive SEND_PENDING-to-ACKNOWLEDGED event. Its key and counter
must agree with the immutable command, and a fresh positive broker order must
still match that command's native order/asset identity, quantity and exact terms.
The event supplies only the receipt's durable counter and original clock; it
does not pretend to contain absent native payload fields. Missing, duplicate or
contradictory history supplies no lag capacity.

Use that event's original aware `at` timestamp, never a later poll/restart, as
the immutable first-seen time for its zero-to-receipt-fill order-leading
generation. It must not be after the current observation. The existing
120-second expiry and insert-once generation identity remain unchanged. Later
positive fill deltas earn only their own additional capacity; receipt capacity
does not overlap them. Complete reconciliation still owns convergence and
terminal state, and no synthetic fill rows or notifications are created.

The limit, cash proof and final schedule checks are separate obligations. No
quote GET is needed for a protected BUY, and no historical price is asserted to
be fresh. Retain all per-call authority brackets for this first implementation;
any future grouping of reads requires its own documented operation boundary.

## Required implementation boundaries

- Extend typed command/order terms and immutable fingerprints with order type,
  TIF, limit, execution-policy/reference hash and reservation economics. Preserve
  every historical MARKET/DAY command and its identity.
- Extend journal immutability, acknowledgement validation, exact-key recovery,
  observation provenance and restored-command comparisons to those exact terms.
  Current adapter bodies and acknowledgement checks explicitly require MARKET/DAY.
- Add separately typed historical-reference sizing and projection evidence.
  Replace live-ask affordability only for this new protected policy with its
  maximum-cost proof; preserve existing market/quote evidence semantics.
- Preserve partial fills and late reports. Current immediate canceled/expired
  submit responses are UNKNOWN; IOC needs positive terminal-receipt support,
  not a generic relaxation of uncertain outcomes.
- Report actual partial/deferred execution truthfully. No fill is not a target
  of zero, complete basket, successful execution or shadow fill. Do not rebase
  the retained book or replay the original October 19 command late.

Qualification must include price-band/tick/split arithmetic, canonical priority,
aggregate reservations, fees, partial fills, native buying-power lag, crashes,
UNKNOWN submit/cancel, contradictory limit/TIF responses, restart/adoption,
unsupported order features and late fills. It must then run the real cold
gateway at production input size with unchanged timing limits and prove that
the new route does not depend on a quote GET. Existing simulated quote tests or
the latency-only read-only profile do not certify this policy.

The private timing campaign may follow the scheduler's existing
RECOVER-to-READY_TO_EXECUTE-to-EXECUTE path when a conservative cash hold defers
later legs. Every callback remains under the real process supervisor and fresh
guards. Measure the first POST and the complete positively recovered simulated
basket from the SAME initial execution clock across all such callbacks. Retain
the 120-second first-order and 300-second complete-basket gates, the existing
540-second maximum execution lateness, and production resource limits. Match
both the application and database envelope: installed automation is 1 CPU/2 GiB
and installed PostgreSQL is 1.5 CPU/1 GiB. The earlier private database used
0.5 CPU/768 MiB, so its failed run is diagnostic and cannot establish whether
the installed resource envelope meets the gate. Correct only the private
qualification database limits to the installed envelope before the next run;
retain its independent system identifier, volumes, failed namespaces and source
history. No production/backtest resources change. Record both database and app
limits with the timing evidence. The private PostgreSQL retains smaller
shared buffers (96 versus 128 MiB), smaller `/dev/shm` (64 MiB versus 1 GiB)
and two versus ten WAL senders. These are recorded conservative differences,
not a claim of identical database configuration; any shared-memory error fails
the run. The application remains at the installed 1 CPU/2 GiB. A new callback
is not a fresh timing budget. Fail on no forward progress, a quote GET,
an unprotected BUY, a wrong basket or an unresolved broker outcome. These are
local provider timing fixtures, not native execution or subscription evidence.

## Other investigated options

Notional MARKET/DAY buys accept a dollar amount and let the broker determine
fractional shares. They remove client quote sizing in principle, but change the
current whole-quantity command/projection model and offer no per-share ceiling.
They require fractionable assets, fractional fill/residual recovery and separate
fee headroom; the API description does not establish an all-inclusive debit cap.
See [fractional rules](https://docs.alpaca.markets/us/docs/fractional-trading).

MOO has no price ceiling for fixed quantity. LOO has a ceiling but changes the
09:31 policy and creates an earlier broker obligation; account/venue eligibility
and auction cancellation freezes need separate evidence. Neither is the minimal
free-data redesign for the installed account.

Keeping free IEX preserves today's quote-dependent policy and possible missed
entries. Delayed SIP cannot satisfy its 60-second freshness rule. No redesign
can guarantee every fill while simultaneously imposing a strict price cap.

### Repeated pure work after the complete-basket rehearsal

The first full protected basket completed recovery at 311.9 seconds and failed
the unchanged 300-second gate. Reduce repeated pure work without sharing a
permission verdict: normalize freshly read catalog SQL through a bounded
512-entry cache keyed only by its exact stripped text. Convert arbitrary caller
objects to text on every call, preserve quoted SQL semantics byte for byte,
and retain every fresh catalog query and comparison. A changed catalog supplies
a new key and must still refuse; no schema identity or verdict is cached.

For protected historical-reference construction, obtain references and the
effective resolver together from the existing canonical
`feed_inputs._snapshot_identity_authorities` under the already authenticated
publication pin. This replaces two duplicate constructions with one. Continue
using the canonical provider-identity resolver separately, reread every required
RAW row on every invocation, and retain all per-broker authority brackets.
No new source module, Core computation, financial formula or timing allowance
is introduced. These changes require a new seal and fresh cold qualification.

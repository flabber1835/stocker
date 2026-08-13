# Sentinel paper activation path

> **Decision record, 2026-08-12.** This document defines the production
> preparation and execution boundary for Alpaca paper trading. It does not
> activate Sentinel, authorize a migration, or authorize an order. The
> operator remains responsible for running each named command at its named
> checkpoint.

## Authority boundary

Sentinel exposes four deliberately separate ordinary operations:

```text
inspect-paper-account broker + database reads only; proves the exact inherited
                      paper account and complete open book the operator is
                      being asked to approve
prepare-paper-plan   broker reads + durable state/plan writes; never broker writes
current-paper-plan   database inspection only
execute-paper-plan   broker writes, but only after explicit account/plan/session
                     confirmation and a complete repeat of every safety gate
```

The existing `migrate-account` command remains a separate fifth, administrative
operation. It is the only path that may classify an unbound account as legacy
or cancel legacy orders. Its exact-sized SELLs use durable execution-journal
keys; it does not use the unidentifiable broker-native close endpoint. Neither
preparation nor execution imports or calls that path. Migration itself requires an exact
`--expect-account` value and refuses an absent or unreadable broker account id;
paper credentials alone are never liquidation authority.

`inspect-paper-account --expect-account <ACCOUNT_ID>` is the mandatory
read-only approval checkpoint before that administrative operation. It uses the
same certified typed Alpaca execution adapter as preparation, asserts the exact
paper endpoint, reads the typed account snapshot, then requires a COMPLETE
orders/positions/orders observation. It reports the endpoint, exact account id,
ACTIVE/block flags, multiplier, Decimal equity/cash/buying power, canonical
PostgreSQL binding state, every position, and every working/open broker order.
It may run while the account is unbound. If a binding already exists, that
binding must match the observed account or inspection refuses. It never records
operator approval, establishes ownership, adopts a plan, submits, cancels,
replaces, or closes anything; its output always says
`broker_mutations_permitted: false`. Well-formed but unsafe account facts remain
visible and set `approval_ready: false` with named `approval_blockers`: inactive
or blocked status, a non-cash multiplier, buying power below cash (unsettled) or
above cash (margin), invalid balances, or an existing binding. Wrong identity,
malformed typed evidence, and an incomplete observation refuse outright. The
operator's approval is the deliberate act of reviewing an `approval_ready:
true` report, approving every inherited position/order it names, and proceeding
to the separately named migration command; the report itself grants nothing.
`approval_ready` is intentionally a migration-approval fact, not a general
account-health verdict: an existing binding makes it false because migration
must never run twice, while an already-bound, flat account may proceed to
`prepare-paper-plan` after that command's independent ownership, readiness, and
reconciliation gates pass. On a clean database the inspection checks for the
binding relation without creating it; an absent relation is reported as
`UNBOUND`, and inspection remains read-only.

The legacy `plan` command is retired because it derived ownership from the old
JSONL audit log. It cannot be used as an approval surface. Use
`inspect-paper-account` for the exact inherited account/open book and
`migration-plan` for the read-only target delta.

Migration may conclude that an inherited account has no working order only from
a complete administrative order read. Alpaca returns at most 500 orders per
response, so the shared administrative adapter pages `status=open` backwards
with the broker's exclusive, stable `before_order_id` cursor until a short or
empty page proves exhaustion. The read has a finite page cap, but reaching that
cap is a refusal, not a truncated success. A malformed page, missing boundary
id, duplicate order, or non-progressing cursor likewise raises and aborts
`migrate-account`; none of those responses may be converted into a flat
observation. This completeness rule belongs to the legacy administrative
adapter only and does not reintroduce broker-native liquidation into ordinary
Sentinel execution.

Preparation is "dry run" with respect to the broker, not with respect to the
database. It may reconcile read evidence, transactionally advance canonical
state, and atomically adopt one immutable current plan. It has no submit,
cancel, replace, or broker-native close step.

Ordinary reconciliation reads the complete open set plus a bounded closed-order
recovery window. That window starts before the durable processed-terminal
watermark (or, on first use, the account binding's establishment time) and is
paged only with Alpaca's stable `before_order_id` cursor. Recording a broker
observation does not advance the watermark. It moves only after every discovered
Sentinel order has been durably adopted or synchronized, so a crash replays
idempotently instead of skipping a fill that existed only at the broker. A page
cap, malformed timestamp, non-descending page, or open/closed re-read race makes
the observation incomplete and preparation/execution refuses.

The typed cash/NAV snapshot used for sizing is read only after the initial
complete clean reconciliation. Reading it first would leave a fill between the
two reads stamped into neither the observation nor the cash baseline. A fill in
the opposite gap is conservative: the earlier observation still names a
working order and initial adoption refuses it.

An unbound inherited account cannot have an executable plan adopted. That is a
necessary consequence of requiring account identity in every plan and refusing
before ownership is established. Before migration, an operator may warm and
inspect the target with the existing read-only `target-book` and
`migration-plan` commands. Durable current-plan adoption occurs only after the
explicit migration has established the binding and the execution adapter has
made a further complete, clean observation.

## Canonical state and first boot

There is one portfolio state: `SessionState.wealth_core`, which is the restart
form of the canonical Wealth Core `PortfolioState`. `SessionState.pending`,
`ledger`, and `feed` are likewise the canonical restart forms. The activation
path does not create a live portfolio model beside them.

On a fresh first boot, exactly 252 completed XNYS sessions strictly before the
decision session are passed to canonical `Feed.warmup`. This reconstructs only
rolling price/volume/split/identity features. Portfolio episodes, peaks, ages,
review flags, cooldowns, pending actions, controller memory, and event history
remain fresh. The decision session is then advanced exactly once through
`advance_and_persist`.

Feature-only first boot additionally requires a completely flat observation
with no working order. A broker book surviving while the canonical envelope is
missing is a restore/recovery incident; it is never interpreted as a new book,
because warm-up cannot reconstruct the lost path-dependent portfolio history.

On resume, the durable cursor and the version-3 envelope must name the same
`last_processed_session`. Every missing XNYS session is advanced once, in its
own transaction. Historical sessions update deterministic state only. The
final state transition and adoption/supersession of the one latest plan share a
transaction, so a crash cannot leave a newer state with an older plan still
current.

One outer corpus publication pin covers readiness, warm-up or catch-up, current
marks, and final plan adoption. Per-session loaders may take nested shared pins,
but they may not release the outer pin or commit the final state separately
from its plan.

Readiness is evaluated against the actual exchange-local observation time, not
against the operator-supplied `--through` value. The supplied session still has
to equal the visible frontier. This prevents a future-dated frontier from being
made to look current merely by supplying the same future date on the command
line.

Preparation also requires `--through` to equal the latest XNYS session whose
calendar-defined close has actually passed at that exchange-local observation
time. The close comes from the pinned XNYS schedule, not a hard-coded 16:00 ET:
an exchange half-day becomes a closed decision session at its 13:00 ET close.
Readiness deliberately treats a real current-session frontier published before
that session's close as `early`, because it is not stale; that is not sufficient
evidence for an immutable close decision. An early/in-progress session may
therefore be inspected, but it cannot be adopted as tomorrow's durable plan.
This is a preparation-only rule: morning execution correctly expects
yesterday's closed decision session while today's effective session is still
open.

Re-running preparation after that decision session is already current does not
re-size or replace its plan from a later account NAV. After a complete clean
re-observation, the command verifies every durable plan authority and re-adopts
the identical plan only to collapse any legacy duplicate-current rows. This is
the restart path. A same-session plan whose state, publication, account, or
strategy identity differs is refused rather than silently replaced.

## Decision adapter

The share target is derived from the canonical shadow, never from broker
positions:

1. Aggregate every filled episode's current shares by permanent security id.
2. Add canonical pending `OPEN_SLOT_POSITION` shares.
3. Subtract canonical pending `CLOSE_POSITION` shares. A pending close therefore
   cannot remain in tomorrow's desired target.
4. Value that target in the raw/as-traded close domain and divide by the
   canonical shadow estimated equity without renormalizing away Wealth Core
   cash.
5. Read the versioned rollout authority. In `PINNED_1_00`, multiply those
   weights by exactly `Decimal("1")` while continuing to record the controller
   transition for audit. In `CONTROLLER`, which is unavailable until a trusted
   issuer/signature contract is implemented and authorizes it, use the
   controller's durable `target_core_exposure`. Then use the existing
   whole-share projection.

Every value crossing the execution membrane is constructed as `Decimal` from
its canonical string representation. Whole shares round down. Negative,
non-finite, leveraged, or otherwise malformed input is refused.

### BIL and cash

The defensive sleeve is exactly `(1 - authorized_target_exposure) * account
NAV`; it is zero during the required `PINNED_1_00` rollout.
It does not absorb Wealth Core's own empty-slot cash or whole-share rounding
residual. Those remain explicit cash. This distinction preserves the controller
decision (Core versus T-bills) without changing Wealth Core's internal cash
decision.

`BIL` is a fixed Sentinel defensive instrument, outside Wealth Core membership.
Its current raw close is read from the same pinned published corpus. If its
permanent corpus identity or current mark cannot be established, Sentinel does
not guess: the sleeve stays cash, BIL is named unpriced, and any already-held or
working committed BIL quantity is preserved.

For any still-wanted unpriced Core security, the plan preserves the complete
broker observation's `held + signed working remainder`. A security the shadow
has actually dropped remains a zero target and may be reduced without a mark.
Unavailable price evidence can therefore prevent an increase; it can never
silently become a liquidation instruction.

## Immutable plan identity

The durable plan records all facts required to prove that it is still current:

```text
decision_session and next-XNYS effective_session
controller target exposure and share target basket
account NAV used for sizing, account-cash baseline, and explicit cash residual
unpriced securities and defensive instrument
corpus data_version and publication fingerprint
complete deployment/broker/account/takeover identity
SessionState fingerprint, controller-transition hash, strategy fingerprint
rollout mode/version and controller-authorizing certificate SHA-256, if any
```

The only valid production plan id is exactly
`sentinel-<ExecutionPlan.fingerprint()>`, where the fingerprint is the complete
64-hex SHA-256 deterministically derived from those
immutable economics. A restart recreating the same plan gets the same id and
must reproduce identical content; the journal refuses one id with different
economics. On every durable load that can bless a current plan, Sentinel also
recomputes this formula and refuses a row whose economics changed while its id
and other stamps remained unchanged. Execution performs that check before its
first broker read.

Rows prepared by a build that used the earlier shortened fingerprint or did
not stamp rollout authority are intentionally stale after this schema upgrade.
They are never rewritten in place. This repository has not activated a
production plan; if an operator has a pre-upgrade test database, inspect it,
leave the row unexecuted, and prepare a new plan from the next closed decision
session after upgrading.

`execute-paper-plan` loads `journal.latest_plan()` itself. No command-line
argument or caller may supply alternate weights, quantities, marks, NAV, or
plan economics.

## Execution gate

Execution requires all of the following while holding the single-writer lock
and a corpus publication pin:

- the exact Alpaca paper URL and the certified Alpaca execution adapter;
- a trusted-issuer-authenticated, unrevoked
  `sentinel.paper_execution_authority/1` certificate whose exact retained
  bytes and signature revalidate against the current runtime, source, strategy,
  and rollout mode. Generic `FINALIZED`/`PASS` rehearsal output and an operator-
  confirmed file hash are not sufficient. Trusted issuance is not implemented,
  so the runtime deliberately rejects even a pre-existing unsigned database
  row;
- the plan's rollout mode/version and certificate stamp exactly match the
  current durable rollout state. New databases start `PINNED_1_00`; changing
  to `CONTROLLER` is a separate audited administrative command and invalidates
  every plan prepared under the prior version. Changing back to
  `PINNED_1_00` is also separate and versioned, requires the literal
  `--confirm-pinned-rollout-may-increase-exposure` acknowledgement, and must
  never be described as de-risking: it forces 100% Wealth Core exposure and
  can increase risk from a controller target of 0, 0.55, or 0.65. A missing
  rollout singleton is corruption; preparation/execution refuse and startup
  does not recreate it;
- a `SENTINEL_OWNED` binding whose full identity matches both the plan and a
  fresh typed broker account snapshot;
- explicit confirmation of the paper account id, plan id, effective session,
  and the literal authorization flag `--confirm-submit-paper-orders`;
- a fresh passing readiness report, current publication fingerprint/version,
  and visible frontier equal to the plan's decision session;
- durable cursor, version-3 state, state fingerprint, controller transition,
  strategy identity, decision session, and next-XNYS effective session all
  matching the plan;
- durable plan id exactly equal to `sentinel-<plan fingerprint>` after the row
  is loaded; confirming a stale id cannot authorize changed basket or sizing
  economics;
- the actual exchange-local time falls within the calendar-defined open/close
  interval of `effective_session`, and its date equals that session. Future
  plans never execute early, and after-close or stale plans never execute
  through this activation command, including reductions. This uses the XNYS
  schedule, so a 13:00 ET half-day close is a hard stop rather than being
  mistaken for an ordinary 16:00 close;
- complete reconciliation in `RUNNING`, with no foreign positions/orders,
  unresolved ownership, UNKNOWN commands, or inconsistent observation;
- no split or other supported share-count action between the durable decision
  and execution. Such an action may explain broker holdings, but it also makes
  the immutable share target stale; this gateway refuses instead of trading a
  pre-action basket against post-action quantities;
- a permanent-id-to-broker-instrument mapping for every actionable leg.
  Observed stable asset identity is sufficient for a reduction; every increase
  re-resolves the asset and requires it to remain active and tradable.
- a cash-only paper account (`multiplier == 1`) whose typed buying power is
  within an absolute $1.00 tolerance of cash. A difference greater than $1.00
  with a lower value means sale proceeds have not become spendable; a higher
  value exposes margin. Sentinel waits/refuses in both cases and will not rely
  on the paper broker's margin facility to make a market order affordable;
- an account payload that explicitly reports `status: ACTIVE` and boolean
  `false` for `trading_blocked`, `account_blocked`, and
  `trade_suspended_by_user`. A missing or non-boolean flag is malformed
  readiness evidence and fails closed;
- a fresh typed account-cash balance equal to the plan's cash baseline plus the
  durable average-price proceeds/cost of every fill under that plan. Open orders
  are observed as a bounded complete set; when a durable nonterminal command
  disappears from it, an exact client-key lookup supplies terminal evidence,
  and the average fill price is persisted with the command for restart.
  Equity itself may move with market marks overnight without invalidating a
  fixed share plan. An unexplained cash difference is refused; it is never
  guessed into P&L or an external flow. This activation gateway deliberately
  has no same-session cash-flow re-projection authority: leave the plan
  unexecuted, resolve and record the flow separately, and prepare from the next
  closed decision session;
- no working broker order at initial plan adoption. That establishes an exact
  cash baseline. Working/partial Sentinel commands created by the adopted plan
  are subsequently recovered from the journal and complete broker observation,
  including their average fill price, without changing plan economics.

Only after those checks does the command delegate order handling to the existing
executor.

Binding establishment and restored-host epoch adoption use the same
single-writer lock. Preparation and execution load the binding only after that
lock is held, so an epoch cannot change between authority validation and plan
adoption or command creation.

The command exits zero only when the executor returns `RUNNING`, with no
refused or deferred legs and no `UNKNOWN` or rejected submission outcome. A
non-zero post-submit attention result is not permission to retry blindly: the
durable command key and normal reconciliation path must resolve it first.

The Alpaca adapter remains certified for DAY market orders, not broker-native
market-on-open orders. The operational choice is therefore an operator-invoked
DAY market transition during the named effective session, after the market is
available. Sentinel does not claim an exchange-native opening auction fill.
Adding `opg`/MOO is a separate adapter-certification decision.

## Two-phase transition

All exposure reductions are attempted before any increase. An increase is
permitted only after every required reduction command has reached `FILLED`, a
fresh complete reconciliation returns `RUNNING` and clean, and quantities have
been re-sized from that post-fill observation. The strict paper gateway then
re-reads the typed account snapshot and requires cash-only buying power to equal
cash; filled-but-unsettled proceeds therefore defer every increase. A rejected, cancelled,
partially-filled, UNKNOWN, absent, or still-working reduction defers every
increase. A foreign change or account mismatch discovered between phases also
defers every increase.

The barrier spans restarts and plan boundaries. Any durable in-flight SELL or
working broker SELL is a reduction whose proceeds are unavailable, even when
its signed remainder already makes the newly-computed delta zero. The executor
reconciles every such sale and permits no increase until all of them are
terminal and every required sale for the current target is fully filled. A
restart can therefore resume a reduction; it cannot skip around it to a buy.

This is stricter than merely observing that a reduction order is no longer
working. "Not working" includes rejected and cancelled; neither creates the
cash that would fund a purchase.

## Operator runbook

Prerequisite: configure the named **paper** account with Alpaca
`max_margin_multiplier: "1"` before this sequence, then verify the account
payload reports `multiplier: "1"`. Alpaca documents that paper account setting
at <https://docs.alpaca.markets/us/v1.1/reference/patchaccountconfig-1>.
Sentinel deliberately does not PATCH broker account configuration; changing it
is a separate operator action and this implementation did not perform it.

Set the compose command once in the shell:

```bash
COMPOSE="bash scripts/sentinel-compose.sh --run"
```

### Clean-checkout one-time prerequisites

Export the paper-only endpoint, the exact paper-account credentials, the
Sharadar key, and a non-default database password into the current shell before
running these checks. Compose may also read the repository `.env`, but a value
stored only there is not necessarily exported to this shell; source an approved
environment file with export semantics or export the four values explicitly.
These checks deliberately print no secret:

```bash
: "${ALPACA_API_KEY:?set the approved paper account key}"
: "${ALPACA_SECRET_KEY:?set the approved paper account secret}"
: "${SHARADAR_API_KEY:?set the Sharadar key}"
: "${SENTINEL_POSTGRES_PASSWORD:?set a non-default database password}"
: "${SENTINEL_BACKUP_DIR:?set the independently durable backup target}"
test -d "$SENTINEL_BACKUP_DIR/wal" -a -d "$SENTINEL_BACKUP_DIR/base"
test "${ALPACA_BASE_URL:-https://paper-api.alpaca.markets}" = \
  "https://paper-api.alpaca.markets"
$COMPOSE build sentinel
$COMPOSE up -d sentinel-postgres
$COMPOSE run --rm sentinel status
$COMPOSE run --rm sentinel check-data --today <POST_CLOSE_ET_ISO_8601>
```

If and only if that final command explicitly reports `the corpus is EMPTY`,
seed once, then publish the daily frontier and repeat readiness at a real
post-close instant (for example `2026-08-12T16:05:00-04:00`; use the
calendar-defined half-day close when applicable):

```bash
$COMPOSE run --rm sentinel feed-seed
$COMPOSE run --rm sentinel feed-daily
$COMPOSE run --rm sentinel check-data --today <POST_CLOSE_ET_ISO_8601>
```

Do not run `feed-seed` over a non-empty corpus. The nightly sequence below is
for an already-seeded corpus.

### Tonight: data, 252-session warm-up preview, and inherited-book dry run

These commands are read-only at the broker. On an inherited unbound account,
do **not** run `prepare-paper-plan`; it must refuse until migration binds the
account.

```bash
$COMPOSE run --rm sentinel feed-daily
$COMPOSE run --rm sentinel check-data --today <POST_CLOSE_ET_ISO_8601>
$COMPOSE run --rm sentinel inspect-paper-account \
  --expect-account <PAPER_ACCOUNT_ID>
$COMPOSE run --rm sentinel status
$COMPOSE run --rm sentinel migration-plan --sessions 253
$COMPOSE run --rm sentinel target-book --sessions 253 --cash <PAPER_ACCOUNT_EQUITY>
```

Checkpoints:

- inspection prints exactly `https://paper-api.alpaca.markets`, the expected
  paper account id, `observation_complete: true`, and
  `broker_mutations_permitted: false`;
- the paper account reports `status: ACTIVE`, `trading_blocked: false`,
  `account_blocked: false`, `trade_suspended_by_user: false`, `multiplier: 1`,
  positive equity, non-negative cash, and buying power within an absolute
  `$1.00` tolerance of cash;
  for an unbound migration candidate, `approval_ready` is `true`.
  Missing/malformed facts refuse inspection;
  well-formed inactive/blocked, unsettled, or margin-capable facts remain visible
  with `approval_ready: false` and are equally a hard stop;
- readiness has no FAIL and reports the intended frontier/publication version;
- `migration-plan` and `target-book` independently re-read the actual
  exchange-local clock and refuse unless their visible frontier is the latest
  closed XNYS session; the full post-close timestamp above is not a date-at-
  midnight freshness shortcut;
- the intended decision session is the latest XNYS session whose
  calendar-defined close has passed; a current-session frontier observed before
  its close is refused, and a half-day may be prepared after its 13:00 ET close;
- the target preview reports 252 warm-up sessions, the current shadow target,
  and every caveat/unpriced security;
- inspection names every inherited position and every working/open order; the
  migration preview agrees with that inherited book;
- no broker POST or DELETE occurred.

If the account is already bound and contains no inherited book, the durable
read-only preparation may also be run tonight:

```bash
$COMPOSE run --rm sentinel prepare-paper-plan \
  --through <DECISION_CLOSE> --warmup-sessions 252 \
  --expect-account <PAPER_ACCOUNT_ID>
$COMPOSE run --rm sentinel current-paper-plan
```

For that already-bound case, inspection reports
`approval_ready: false`/`account_already_bound`; this blocks a second migration,
not preparation. Preparation still must pass its independent binding, flat
reconciliation, publication, readiness, and account gates.

### Tomorrow: explicit legacy-book migration

Before inspecting, stop every prior automated or manual writer for this paper
account and revoke or remove its credentials from every retired host. Approval
is scoped to this exact account, not merely to a screenshot or yesterday's
position list. Inspect once more, approve that exact inherited book out of
band, then invoke the existing administrative operation explicitly. The
inspection output does not itself grant migration authority, and migration's
own fresh complete reads remain the liquidation authority:

```bash
$COMPOSE run --rm sentinel inspect-paper-account \
  --expect-account <PAPER_ACCOUNT_ID>
$COMPOSE run --rm sentinel migrate-account \
  --deployment-id <STABLE_DEPLOYMENT_ID> \
  --expect-account <PAPER_ACCOUNT_ID> \
  --notes '<CHANGE_TICKET>'
$COMPOSE run --rm sentinel status
```

Pre-migration checkpoint: account id and endpoint are exact, the observation is
COMPLETE, every displayed position/order is approved as inherited, the binding
state is `UNBOUND`, `approval_ready` is `true`, every prior writer is fenced,
and
`broker_mutations_permitted` is `false`. Any mismatch,
malformed account field, incomplete observation, unexpected position/order, or
existing ownership is a stop rather than permission to migrate.

Post-migration checkpoint: migration reports `migrated: true`; the administrative state
machine observed no working legacy order or position, obtained two stable flat
observations, and persisted a `SENTINEL_OWNED` binding for the expected account.
Do not treat an accepted cancel or close request as this checkpoint.

### Settlement, complete re-observation, preparation, and inspection

```bash
$COMPOSE run --rm sentinel check-data --today <ACTUAL_ET_ISO_8601>
$COMPOSE run --rm sentinel prepare-paper-plan \
  --through <DECISION_CLOSE> --warmup-sessions 252 \
  --expect-account <PAPER_ACCOUNT_ID>
$COMPOSE run --rm sentinel current-paper-plan
```

Checkpoints:

- the plan reports rollout `PINNED_1_00`, version 1 (or the currently audited
  pinned version), and no controller-authorizing certificate. Pinned
  preparation remains available for broker-read-only inspection; final
  execution remains fail-closed until formal certification emits a signed,
  zero-xfail, Wealth-Core-`GO` manifest and a separately reviewed trust-root
  implementation authenticates it;
- the typed execution adapter made a further COMPLETE, clean observation after
  migration, with no UNKNOWN or foreign activity;
- no working order remained when the plan established its account-cash
  baseline;
- exactly one plan is unsuperseded;
- plan account/binding identity, publication version/fingerprint, decision
  session, effective session, state fingerprint, and strategy fingerprint all
  match the displayed current authorities;
- BIL quantity, explicit cash residual, preserved unpriced quantities, and all
  target shares are inspected;
- account cash matches the durable baseline (or, after a restart, the baseline
  plus/minus every observed average-price fill under this plan); overnight
  equity mark movement by itself is not a cash-flow refusal;
- cash-only buying power differs from cash by no more than the executor's
  absolute `$1.00` tolerance; a larger difference in either direction is a
  settlement/margin stop;
- any unexplained deposit, withdrawal, fee, or other cash movement is a hard
  stop for the adopted plan. There is no activation-command override or
  same-session re-projection;
- preparation reports `broker_mutations_permitted: false`.

Before the final execution command, verify the exchange-local clock is inside
the displayed effective session's XNYS open/close interval. A normal close is
16:00 ET and an exchange half-day closes at 13:00 ET. The command refuses before
its first broker read when invoked before the open or at/after the close; do not
use a late invocation to queue the plan into a later session.

Execution also requires separately reviewed, trusted system-certification
authority. The repository cannot produce an authorized manifest while the
strict xfails and Wealth Core `NO-GO` remain, and it has no trusted
issuer/signature verifier. Do not edit a generic `PASS` manifest, confirm its
hash, or insert a database row to manufacture authority.

`install-system-certificate` is a reserved command and currently returns
`REFUSED` before reading the named file or opening PostgreSQL. The runtime gate
also refuses unsigned rows left by an older build or restored backup. There is
therefore no valid installation command or final-submission checkpoint in this
revision. `current-paper-plan` must report `system_certificate_valid: false`.

When a later PR defines a trust root, signed issuance, verification, and
rotation/revocation semantics, this section must be replaced with that exact
reviewed installation ceremony. Enabling controller exposure remains a
separate audited transition and requires a newly prepared plan.

### Final separately authorized paper submission

This is the eventual separately confirmed command surface. It is documented so
the authority boundary is reviewable, but **must not be run** in this revision:
the trusted-certificate gate always refuses before the first broker read.

```bash
$COMPOSE run --rm sentinel execute-paper-plan \
  --confirm-paper-account <PAPER_ACCOUNT_ID> \
  --confirm-plan-id <PLAN_ID> \
  --confirm-effective-session <YYYY-MM-DD> \
  --confirm-submit-paper-orders
```

Stop on any refusal. There is no force flag. Re-run preparation only after the
cause is understood; never substitute `migrate-account` or rerun migration
against a bound account.

Success means the result says `paper_submission_authorized: true`,
`operator_attention_required: false`, runtime state `RUNNING`, and contains no
refused or deferred leg and no `UNKNOWN` or rejected submission. An
`ACKNOWLEDGED` order is only durable broker acceptance, not a fill; continue
normal reconciliation and do not treat ACK as completion of the target book.

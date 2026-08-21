# Sentinel trial verification

Status: design contract for the autonomous Alpaca paper trial.

This document strengthens the read-only panel from an operational condition
display into a financial verification surface.  It does not change the trading
architecture: Wealth Core still chooses what to hold, Sentinel still chooses
exposure, execution remains the only broker-facing layer, and the panel remains
SELECT-only.

## 1. Two verdicts, never one ambiguous green

Operational safety and trial-performance verification are different facts.
`MISSED_STATE_ONLY`, `SUPERSEDED`, a killed service, or a refused increase can
be operationally safe while making realized trial performance incomparable to
the intended strategy.  The panel therefore keeps the existing diagnostic
rows but gives the financial headline only one of these meanings:

* `TRIAL VERIFIED THROUGH <effective session>` means that session has an
  immutable v3 verification whose verdict is `VERIFIED`, every later owed
  exchange session is absent only because it is not due yet, and the rendered
  page is inside its presentation-age budget.
* `TRIAL NOT VERIFIED — <reason>` is used for missing, failed, stale, future,
  contradictory, or overdue evidence.  Informational performance may remain
  visible, but never with verified styling.

Generic operational `OK`, and safe terminal cycle states, cannot manufacture
the trial headline.

Conversely, an immutable historical certificate cannot manufacture a current
green screen.  Verified styling for the headline and all trial-performance rows
requires every non-pending current operational row to be `OK` and every source
read to be healthy.  A corrupt or unreadable binding, canonical state/cursor,
behavior schema, publication, broker observation, automation authority, leader,
or owed cycle removes green without rewriting the historical certificate.

## 2. Durable evidence without an unattended schema repair

The behavioral schema has a strict, catalog-fingerprinted migration authority.
Routine automation must not add a table behind that authority.  The repository
already reserves `sentinel_processed_sessions` as a typed, namespaced durable
JSON store for independent cursors and immutable plan cash baselines.  Trial
evidence uses the same deliberate mechanism:

```text
trial-account:v1:<observation id>
trial-close-nav:v1:<effective session>
trial-fill-interval:v1:<effective session>
trial-verification:v3:<effective session>
```

The first row binds an actual broker account snapshot to the exact COMPLETE
reconciliation observation that preceded it. The close-NAV row binds an
adapter-accepted typed broker historical point to the exact account, XNYS
session and official close. It retains the declared source semantics/query,
opaque raw label and declared unit, the first request bracket, raw-response
digest, and its own canonical evidence hash. These retained strings are audit
facts, not a generic validator's claim that their provider meaning is trusted.
The fill-interval row separately binds the exact plan and account to one
COMPLETE, account-wide broker publication from the plan cash-baseline boundary
through a fixed inclusive upper boundary after the close. It retains every
native fill activity id, broker order id, optional client key, exact quantity,
price and execution time, plus the provider semantics/query and raw digest.
The ordinary command fill cache is never treated as proof that no other account
fill occurred.

Terminal outcomes have two paths. A non-success terminal cycle immediately
freezes one immutable `NOT_VERIFIED` row without waiting for close evidence. A
`SUCCEEDED` cycle freezes no open-time row; it remains due until both its
close-NAV and account-wide fill-interval rows exist and post-close verification
can run. Missing or future-dated source evidence never freezes an immutable red
row merely because the provider has not caught up. On close-NAV retry, identical
source economics are idempotent even when the later request bracket differs;
the first retained bracket and evidence hash stay immutable. A different source
point for the same effective session is an integrity refusal, not an upsert.
The terminal state transition and verification callback are separate durable
boundaries. Before any success can verify, the verifier scans every earlier
cycle for the same deployment/broker/account across all takeover epochs. A
nonterminal predecessor or a terminal predecessor without its exact immutable
verdict is `VERIFICATION_GAP`; a later success cannot hide a callback crash by
becoming a fresh anchor. Exact v1/v2 terminal rows satisfy this callback-debt
check across an upgrade, but remain ineligible as v3 NAV/return predecessors.

This is an equivalently strong per-session verification ledger: the namespace
and JSON `kind` are versioned, `cursor_name` is the primary key, the trading
session is duplicated in the typed DATE column and validated on read, and the
record contains a SHA-256 over its canonical evidence object.  A future physical
table may migrate these records only through an explicit reviewed behavioral
schema migration.

The broker-history verifier deliberately starts a new `v3` certificate chain.
Validly hashed `v1`/`v2` rows remain immutable historical evidence, but neither
is loaded nor accepted as a predecessor: those certificates did not bind an
independent broker historical-close source point or a complete account-wide
fill interval. They may only prove that the corresponding old terminal callback
occurred, as described above. A changed value, label,
semantics, query or raw-response digest for an already recorded close raises
`TrialCloseNavHistoricalRevision`; history is never overwritten.

## 3. When evidence is captured

Broker account evidence is captured inside the existing guarded paper gateway,
after a fresh account/cash read and a COMPLETE, RUNNING, clean reconciliation.
It is never captured by the panel.  The evidence names:

* deployment, broker account, and takeover epoch;
* reconciliation observation id, reconciliation request start/completion, and
  account request start/completion;
* the authority class of the claimed valuation timestamp;
* actual equity and cash;
* account status and blocking flags;
* broker cash-activity processed-through boundary, cumulative total, last
  non-zero native activity id, and accepted append-only identity scheme.

The per-session verification also projects any expected paper dividend from the
effective-session published bars and their active Sharadar ACTIONS source-row
identities.  It reconstructs the actual pre-open paper holding by reversing the
current plan's exact signed fills from the COMPLETE closing reconciliation.  A
buy at the ex-date open therefore earns nothing, while a sale at that open
retains the entitlement.  This is evidence projection only: the record contains
`compensation_applied: false`, and no projected amount is added to broker cash,
account equity, marked NAV or target sizing.

The persistent automation loop writes an immediate immutable `NOT_VERIFIED`
record for terminal states other than `SUCCEEDED`.  Success at the execution
checkpoint is necessary but not sufficient: an open-time account read cannot
certify a full session against a close that does not exist yet.  On the next
post-close preparation, the guarded gateway obtains a fresh account/cash read
and COMPLETE reconciliation for the prior plan's effective session.  Before it
advances state or supersedes that plan, it retains the broker historical-close
point and the complete account-wide fill interval, binds the now-published
close marks, and appends the final session verification. Any complete but
economically failed clause earns
`NOT_VERIFIED`.  The verifier never repairs inputs to obtain green.

### Defensive-fund evidence is a separate corpus domain

`SENTINEL:BIL` is Sentinel's fixed execution identity for the BIL defensive
sleeve.  It is not an SEP company and must never be inserted into
`sentinel_bars`, the Sharadar TICKERS projection, or the Wealth Core universe.
The stable SFP reference request therefore fetches exactly SPY and BIL together:
SPY `closeadj` remains isolated in the regime-sensor relation, while BIL's SFP
`close` and `closeunadj` are published in a dedicated fixed-identity defensive
mark relation.  `closeunadj` is the tradable paper-account mark; `close` is
retained only as the split-adjusted, dividend-unadjusted price-domain witness
needed to translate a reported distribution onto raw broker shares.  Neither
field is a Wealth Core signal input.

Planning and trial valuation resolve `SENTINEL:BIL` to that published BIL row
explicitly.  Readiness requires the same exact 41-session XNYS tail used by the
bounded SFP reference check, including a valid raw BIL frontier mark.  A missing
or invalid BIL mark never turns the target into cash and
never authorizes a synthetic valuation: the held/committed defensive quantity
is preserved, an increase is refused as unpriced, and trial verification is
`NOT_VERIFIED`.  Active published Sharadar ACTIONS rows remain the corporate-
action authority for BIL.  When a BIL dividend or special dividend falls on the
paper account's pre-open holding, the verifier records the exact source-row
identity and entitlement as an evidence-only paper limitation, sets
`ALPACA_PAPER_DIVIDEND_UNSUPPORTED`, and applies no cash compensation.  Missing,
non-finite, non-positive, or basis-untranslatable distribution evidence is
`DIVIDEND_EVIDENCE_INVALID`, not an assumed zero.

The pre-open share-unit gate uses active quantity rather than mere basket-key
presence. Nonzero BIL target, nonzero action-aged expected BIL, or an in-flight
BIL command requires explicit coverage. The conventional zero-valued BIL key
alone requires no coverage and exact-set validation rejects it as extra.

The current broker account observation supplies live equity at its observation
time and remains diagnostic. It is never the session-close performance source.
Clause 9 instead consumes `trial-close-nav:v1` after an adapter has returned an
accepted typed historical object. Persistence enforces the account and requested
session, requires the object's `valuation_at` to equal the official XNYS close,
requires its request bracket to begin at or after that close, and retains the
declared source, semantics, query, label/unit, and raw digest. It does not interpret or
whitelist those declared provider semantics. Local request brackets remain
provenance and cannot by themselves promote a source point.

Alpaca Portfolio History is the candidate source, but current documentation does
not establish the wire timestamp unit/label mapping, close-point finality or
revision timing needed by this contract. The adapter/parser is therefore
quarantined and advertises no production close-valuation capability until a
real bound paper-account acceptance covers normal and half-day sessions,
repeated post-close/T+1 reads, cash-flow cases, fractional positions and split
days. Those are future promotion requirements; the retained-object layer does
not currently enforce the Portfolio History-specific interpretations.
Missing/not-yet-mature evidence and transport/parser failure before an accepted
typed object exists are retryable and must leave a succeeded cycle unwritten
before a successor plan can supersede the due plan. An accepted object that then
fails immutable account/session/official-close validation is a hard refusal; a
different source point for an already retained session raises
`TrialCloseNavHistoricalRevision`.

Fill evidence has its own stronger capability and cannot be synthesized from
`recent_fills` or the Sentinel command journal. Its interval must start exactly
at the immutable plan cash baseline's processed-through boundary, be explicitly
COMPLETE, reach the official close and the later account/reconciliation
observation, and retain native account activity identities. Every account fill
must bind to exactly one current-plan command by both client key and broker
order id, with the same exact quantity and price, and must execute no later than
the close. Foreign, post-close, missing-key, mislinked, revised, or cache-only
fills block close-book attribution. The Alpaca adapter currently advertises no
account-fill-interval capability: Activity SSE remains useful for recovery and
cash evidence, but its correction/finality and fixed-boundary acceptance has
not earned this separate negative-space claim. A due successful cycle therefore
remains pending rather than manufacturing an empty fill interval.

## 4. Verification clauses

A succeeded session is `VERIFIED` only when one coherent database snapshot
proves all of the following:

1. The owned binding exactly matches the cycle, plan, and account evidence.
2. The cycle is `SUCCEEDED`, names an immutable current plan, and contains a
   last clean reconciliation id.
3. Canonical state/cursor, decision session, state hash, strategy fingerprint,
   rollout identity, and plan fingerprint agree.  The append-only
   `sentinel_trial_strategy_evidence` row for the decision session must exist,
   pass its own payload hash, and agree with those same state, publication,
   strategy, decision, and observation identities.  The verification retains
   that payload hash so financial and strategy evidence form one chain rather
   than two parallel claims.
4. The plan and cycle agree on the immutable decision publication identity.
   The later valuation publication is explicit, its visible Sharadar frontier
   is at or after the effective session, and exchange-calendar freshness
   reports zero owed sessions. This permits delayed finalization without
   relabelling a later frontier as the old close.
5. The readiness PASS was computed after that exact valuation publication was published
   and before any later publication, and every stored readiness clause passed.
6. The named broker observation is COMPLETE and RUNNING; its observed positions
   equal the reconciled expected book. Account evidence retains two exact
   action-aged targets: the close target through the effective session and the
   observation target through the later evidence session. The reconciled/live
   book must equal the observation target; only the close target is valued at
   the historical close. This prevents a supported post-close split from
   creating a false mismatch while also preventing later share units from being
   multiplied by old close prices. An explicit
   zero-quantity sleeve in the plan and its omission from the command-derived
   book are economically identical; all other union-of-identity differences
   retain the share tolerance. It has no foreign
   working order, and the command journal has no active, uncertain, rejected,
   or cancelled current-plan command.  Comparing post-action positions directly
   with the pre-action share basket is forbidden.
7. No plan security is unpriced. Effective-session published close marks exist
   and are finite for every nonzero close-target position.
8. The account evidence names the same observation and account, is not future
   dated, and its cash-activity cursor is complete through the evidence time.
9. Broker historical-close equity agrees within the existing one-dollar
   financial tolerance with independently reconstructed close NAV. Close cash
   comes from the immutable plan cash baseline plus exact signed notionals from
   the COMPLETE account-wide fill interval. The plan baseline must carry the
   accepted append-only Activity-SSE cash identity plus a separately retained,
   plan/account/session-bound fixed-interval finality witness. A global scheme
   string cannot retroactively promote old baselines. The current Alpaca source
   has append-only identity but no finality witness, so it reports
   `CLOSE_CASH_FINALITY_UNAVAILABLE` and the succeeded cycle remains pending.
   Once a future source earns both authorities, its cumulative total and last
   non-zero cash activity id must remain unchanged.
   A missing baseline is never backfilled from current cash or the current
   activity cursor: offsetting post-plan events could make that snapshot look
   numerically unchanged. A legacy/timestamp-paged baseline or any post-baseline
   cash activity refuses as `CLOSE_CASH_UNPROVEN` because the available business
   date cannot assign it to an intraday official-close boundary. The
   implementation does not yet assign even a recognized activity through the
   close. Cash is not taken from a later live account snapshot and is never
   derived as `equity - securities`. The v3 certificate embeds the exact
   plan-cash baseline and revalidates both that source row and its current
   finality acceptance on every load and ancestor link; finality revocation
   cannot leave a stale VERIFIED return in the chain. The
   close book is the action-aged exact target/command book, independently valued
   at effective-session published raw closes. The independently retained fill
   interval must start at the plan cash boundary, cover the entire account
   through both the close and the account evidence observation, and match every
   durable current-plan fill by native broker order identity and exact
   economics. Any foreign, missing, mislinked, or post-close fill makes
   `CLOSE_BOOK_INTERVAL_UNPROVEN` block. The
   immutable close-evidence hash is part of the v3 verification. Endpoint
   P/L/base-value fields never enter Sentinel's math. The later `/v2/account`
   equity/cash remain labelled live diagnostics and cannot explain the
   historical point.
10. External cash is identified from the durable broker/operator cash ledger.
    `JNLC`/legacy `JNL` cash journals are account-boundary capital; they are not
    strategy income. `JNLS`, `ACATS`, and `FOPT` securities transfers are refused until
    an accepted in-kind-flow valuation and time-weighting contract exists.
    Internal dividends, interest, fees, and other recognized activity stay in
    account economics, but that classification does not make a post-baseline
    broker activity assignable to the official close under clause 9. A
    malformed reserved activity row or a restored
    cursor/event inconsistency is `NOT_VERIFIED`.  The present broker evidence
    carries only an activity business date, not an independently marked NAV at
    the instant of an intraday external flow.  Therefore any nonzero external
    flow makes the session `NOT_VERIFIED` with no percentage return.  Subtracting
    it from closing equity and dividing by opening equity would silently assume
    boundary timing and is not TWR.
    Alpaca paper's dividend omission has a separate, explicit rule.  The
    effective-session published bar proves the raw-domain per-share amount, and
    the active Sharadar ACTIONS projection supplies the exact positive, finite
    source amounts and source-row identities.  Every held-ticker dividend row is
    aggregated, converted through the published signal/raw close domains, and
    required to equal the normalized bar amount.  The paper entitlement is
    reconstructed from that same
    session's COMPLETE closing broker positions by reversing the current
    plan's signed, exact filled command quantities.  This recovers the actual
    pre-open paper holding without reading the later post-fill book as
    entitlement.  Missing bars, action identities, price-domain conversion, or
    contradictory fill evidence is `DIVIDEND_EVIDENCE_INVALID`, never an
    assumed zero.  The effective-session verification is `NOT_VERIFIED` with
    `ALPACA_PAPER_DIVIDEND_UNSUPPORTED`, and retains that exact entitlement as a
    paper limitation.  Execution may continue when every ordinary safety gate is
    clean, but the financial chain cannot remain green.  The verifier neither
    waits for paper cash that Alpaca says it will not emit nor creates synthetic
    cash, fills, positions, orders or a second economic ledger.  Broker-native
    cash activity, if any, remains independently retained exactly once and does
    not rewrite the immutable limitation evidence.
11. Canonical unresolved/carried terminal state is zero.  Corporate-action rows
    for the session remain linked audit detail; reconciliation has already
    applied supported share transformations before classifying any mismatch.
12. Required timestamps are within the automation clock-skew allowance and the
    verification time is at or after all evidence it certifies.

The first successful session is a close anchor only. Its independently accepted
official-close equity is retained, but opening equity, strategy P/L, daily TWR,
and total return are omitted: the plan's later live sizing NAV is not a
historical opening mark. The next adjacent successful session uses that anchor's
official-close equity as its opening boundary. A gap or prior `NOT_VERIFIED` row
breaks the verified performance chain. Deployment/account/takeover identity is
part of a deterministic performance `chain_id`. An explicit account,
deployment, or takeover-epoch change starts a new certified anchor with no
opening equity or inherited cumulative factor; it never computes a return
across the boundary. Missing terminal evidence on the same economic account is
still detected across takeover epochs before that reset is allowed.

### Current deployment consequence

The present production adapter cannot issue a `VERIFIED` interval because
Portfolio History wire semantics have not passed the bound-account acceptance
and no complete account-wide fill publication has passed its separate
correction/finality/fixed-boundary acceptance; both advertised capability bits
are false. Independently, Activity SSE has append-only replay identity but no
accepted close-cash finality/fixed-interval watermark, so its identity scheme is
not close authority. Its documented Broker API endpoint/authentication also is
not the Trading/Paper account interface used by this deployment, so the Alpaca
adapter's account-cash capability and SSE scheme claim are both disabled. All
three source contracts must be accepted. The quarantined decoder also accepts
only completed (`status: executed`) USD events; foreign-currency economics are
not converted or interpreted as USD. Separately, the first detected paper dividend
produces `ALPACA_PAPER_DIVIDEND_UNSUPPORTED`; its successor receives
`VERIFICATION_GAP` within the same takeover epoch. An explicit takeover reset
starts a new chain but does not repair or reclassify the affected old session;
supported dividend treatment is required for an unbroken series. These are deployment
acceptance blockers for a multi-month verified performance series, not hidden
adjustments the verifier is allowed to approximate.

## 5. Performance semantics

For each unbroken verified interval with no external capital flow:

```text
strategy P&L = ending actual equity - opening actual equity - external cash
daily TWR factor = ending actual equity / opening actual equity
cumulative TWR = product(daily TWR factors) - 1
drawdown = cumulative TWR factor / prior factor peak - 1
```

`strategy P&L` remains an unambiguous informational numerator when external cash
exists, but that session cannot extend the verified return chain.  Supporting a
flow-bearing verified interval later requires a durable account NAV immediately
before each flow and immediately after the final flow, followed by the product
of those subperiod returns.  A business date, ingestion timestamp, Modified
Dietz estimate, or assumed open/close timing is insufficient.

Internal dividends, interest, fees, fill prices/slippage, fractional residual
cash, and terminal settlements remain in ending equity and therefore in
strategy return only when the broker actually reports those economics.  A
known paper dividend entitlement with no certified paper implementation breaks
the verified-performance chain even though ordinary automation may safely keep
running.  This separates an accepted simulator limitation from an execution
failure without pretending the omitted cash was received.  The UI calls the
primary figure `Total return`; geometric
annualization is labelled `Annualized TWR` and uses 252 exchange sessions. The
anchor is retained in the drawdown path but is not counted as a zero-return day
in the annualization exponent. Annualization is omitted when the chain is
shorter than two verified marks or contains a gap. The panel slices factors,
drawdown, and annualization to the latest immutable `chain_id`; an epoch reset
cannot turn a prior peak into a fictitious drawdown or cross-chain return.

Marked NAV and the cash equation are attribution controls, not the performance
source.  Performance uses actual Alpaca equity.

## 6. Session obligations and presentation freshness

Financial green is calendar-driven.  The server determines the latest owed
decision/effective session from the pinned XNYS schedule and automation timing.
Any owed session without a matching verification, any `sessions_behind > 0`,
or a verification for an older session makes the headline not verified.
Weekends and holidays create no obligation of their own.

The HTML embeds its UTC generation instant and a short presentation budget.
JavaScript has only negative authority: on `pageshow`, return to visible state,
`online`, or budget expiry it synchronously changes the badge to `TRIAL NOT
VERIFIED — NOT CURRENT` before requesting a full reload.  `offline` does the
same without attempting to invent a cached verdict.  It never calculates a
financial value or changes a not-verified page to verified.

## 7. Owner projection

The always-visible owner summary shows the exact verified-through session,
actual equity/cash, total return, annualized TWR when valid, current/max
drawdown, target exposure, decision/effective sessions, and concise feed,
reconciliation, accounting, and cycle status.

Read-only expandable sections expose target-versus-actual positions, current
and recent commands/orders/fills, classified cash activity, marked-NAV residual,
corporate/terminal events, and one row per trial session.  Healthy engineering
diagnostics remain available but are visually secondary.  No route, form, or
client event can submit, cancel, approve, migrate, or liquidate.

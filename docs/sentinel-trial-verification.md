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
  immutable v1 verification whose verdict is `VERIFIED`, every later owed
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
trial-verification:v2:<effective session>
```

The first row binds an actual broker account snapshot to the exact COMPLETE
reconciliation observation that preceded it.  The second is inserted only
after the automation cycle has reached a terminal state.  Existing rows are
read and compared byte-for-byte; a retry may confirm identical evidence but
may not rewrite history.  A different attempt for the same effective session
is an integrity refusal, not an upsert.

This is an equivalently strong per-session verification ledger: the namespace
and JSON `kind` are versioned, `cursor_name` is the primary key, the trading
session is duplicated in the typed DATE column and validated on read, and the
record contains a SHA-256 over its canonical evidence object.  A future physical
table may migrate these records only through an explicit reviewed behavioral
schema migration.

The corrected verifier deliberately starts a new `v2` certificate chain.  A
validly hashed `v1` row remains immutable historical evidence, but it is neither
loaded nor accepted as a predecessor: pre-fix certificates did not prove the
same dividend binding and close-timestamp semantics.

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
* broker cash-activity processed-through boundary and cumulative total.

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
advances state or supersedes that plan, it binds the now-published close marks
and appends the final session verification.  Any failed clause earns
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

The current broker account observation supplies live equity at its observation
time, while clause 9 independently marks positions at the effective-session
official close.  Those are different valuation instants during the post-close
delay.  A qualifying observation must carry broker-authoritative close timing
and prove the whole read sequence: reconciliation request start, reconciliation
completion, account request start, and account completion must be ordered; none
may precede the close; and all four must finish within the five-second allowance
after that close.  Missing legacy fields and local wall-clock brackets fail
closed.  The current Alpaca account/positions responses expose no authenticated
valuation timestamp, so production stamps
`LOCAL_RESPONSE_BRACKET_UNVERIFIED`, never
`BROKER_AUTHORITATIVE_CLOSE`.  Until the gateway durably captures supported
broker-authoritative close evidence (or a supported historical close mark),
the comparison is diagnostic only and cannot certify a verified NAV interval.

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
   equals the effective session, and exchange-calendar freshness reports zero
   owed sessions.
5. The readiness PASS was computed after that exact valuation publication was published
   and before any later publication, and every stored readiness clause passed.
6. The named broker observation is COMPLETE and RUNNING; its observed positions
   equal the reconciled expected book.  That expected book must itself equal the
   immutable plan target aged through the exact supported corporate-action
   multipliers for `(decision session, evidence session]`, captured alongside
   the same reconciliation in immutable account evidence.  It has no foreign
   working order, and the command journal has no active, uncertain, rejected,
   or cancelled current-plan command.  Comparing post-action positions directly
   with the pre-action share basket is forbidden.
7. No plan security is unpriced.  Current published close marks exist and are
   finite for every nonzero observed position.
8. The account evidence names the same observation and account, is not future
   dated, and its cash-activity cursor is complete through the evidence time.
9. Broker equity agrees within the existing one-dollar financial tolerance with
   independently marked account NAV: actual cash plus observed quantities at
   the effective-session published closes.  The complete reconciliation and
   account-request brackets must be ordered, post-close, within five seconds of
   that exact XNYS close, and backed by `BROKER_AUTHORITATIVE_CLOSE` rather than
   a local receipt time.  A later live snapshot is retained as diagnostic
   attribution but adds `VALUATION_TIMESTAMP_UNALIGNED` and cannot certify the
   interval even when its number happens to match.  This is the NAV attribution
   witness; the account balance is not allowed to explain itself.
10. External cash is identified from the durable broker/operator cash ledger.
    Internal dividends, interest, fees, and other recognized activity stay in
    account economics.  A malformed reserved activity row or a restored
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

The first session uses the plan's actual sizing NAV as its opening boundary.
Later sessions use the previous verification's actual equity.  A gap or prior
`NOT_VERIFIED` row breaks the verified performance chain.

### Current deployment consequence

The present production adapter cannot issue a `VERIFIED` NAV interval because
it has no broker-authoritative close timestamp; every account observation is
classified as local/unverified.  Separately, the first detected paper dividend
produces `ALPACA_PAPER_DIVIDEND_UNSUPPORTED`; its successor receives
`VERIFICATION_GAP`, so the chain cannot recover without an explicitly certified
epoch/reset rule or supported dividend treatment.  These are deployment
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
annualization is labelled `Annualized TWR` and uses 252 exchange sessions.  It
is omitted when the chain is shorter than two verified marks or contains a gap.

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

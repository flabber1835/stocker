# Current PAPER cash and an unsent legacy plan

Decision: 2026-11-06, before implementation. Complete the existing native cash
path and provide an explicit prospective transition for a never-dispatched
informational PAPER plan that predates immutable activity baselines. This does
not reconstruct a historical cash boundary or certify a return.

## Accept only current owned-account cash observation

The selected asset-ID PAPER adapter may expose `cash_observable`,
`account_cash_activity_evidence` and `financial_activity_sse`. The other adapter
variants and LIVE keep their previous claims. Fill-interval completeness,
terminal negative-space recovery, close valuation and cash publication finality
remain unaccepted. A native account balance is not evidence of finality.

Acceptance supplements the [owned-stream scope contract](paper-activity-account-scope.md).
The account was created September 22, after the provider's documented February
11 Activity-SSE history boundary. A private, GET-only qualification captured 252
events from account inception, repeated the terminated snapshot, verified native
cursor replay and stable native UUID/account identity before, between and after
the reads, and observed no open orders. All 252 events omit `account_id`; 236
are trades and 16 are cash activities. The corrected production parser replayed
the exact retained bytes in a credential-free, network-disabled process and
matched all 16 native references and Decimal amounts. Capture SHA256:
`695351d2ef54d7dcb3df4f6304c5e5c57ec87ccc2dd930278d004df6d335ba05`.
This qualifies the wire/identity traversal, not a completed trading interval.

Production uses the same complete bootstrap, bounded native event cursor,
account brackets, strict taxonomy/currency/status and immutable native cash
ledger. Require a native account creation timestamp on or after February 12,
2026, so an older account cannot claim full history from the provider's February
11 coverage boundary. Repeat initial discovery before accepting its first cursor. Unreachable
or contradictory source evidence refuses; corrections/busts and external
securities transfers remain explicit recovery conditions. Repeated identical
snapshots never become historical finality. Trade notionals remain in the
canonical durable fill journal and are not counted again as cash activities.
At the PAPER cash boundary, retain credential/authority refusals and classify
malformed evidence or an unsupported native correction as structural refusal.
Only actual transport unavailability earns an availability retry; parser or
ledger defects cannot become an unbounded PREPARE availability wait.

For subsequent plans, keep the existing immutable baseline/fills/native-activity
equation before every new decision. A newly published positive native cash total
can precede its appearance in account cash. If the baseline has accepted native
identity, the net activity delta is positive, and account cash still exactly
equals baseline plus durable fills without that delta, read-only recovery and
preparation report a retryable cash-source/account coherence wait. This earns no
cash explanation, plan adoption, new baseline, historical result or transport.
The next preparation may proceed only after the ordinary full equation balances.
Execution retains its strict cash refusal and original opening cutoff. Negative,
unidentified and other unexplained differences keep their existing refusals.
This semantic wait does not create, renew or extend the generic 120-second
endpoint-lag grace. PREPARE uses its existing availability-retry contract; no
RECOVER phase receives the unrelated unbounded source-publication flag.

## Retire an unsent legacy plan only during a new decision

The November 5 plan really observed cash 11079.88 when prepared. The broker's
positive 75.89 BIL dividend event was already published, but the account cash
first changed to 11155.77 overnight. Event publication, entitlement, cash posting
and the plan-time event boundary are separate facts. Neither a later balance nor
a newly reachable event stream can backfill the old plan's missing baseline.

Add an explicit request to attended `prepare-paper-plan` in reviewed
informational dual PAPER mode. The request confirms the exact legacy plan id
and fingerprint, one native cash-dividend reference, the observed fresh cash,
actor/reason and prospective-only retirement. It is not a general cash override.
The existing killed, signed PREPARE_READ authority and canonical execution writer
remain mandatory. Automation cannot request this transition.
Bind the disabled/killed control generation and repeat that exact fence and
absence-of-leader check immediately before appending the atomic receipt; an
intervening control change cannot consume an earlier qualification.

Admission requires a strictly later actual closed decision with a future
effective-session open; the exact owned binding; no legacy plan baseline; **no
durable command at all for that plan**, no unresolved account command or working
broker order; and clean complete canonical reconciliation. Reuse the settled
account/order/position bracket, including unchanged cash/status and book facts.
The accepted current cash cursor must match the bracket. The selected native
reference must identify one retained positive internal DIV flow, already settled
by the decision date, whose exact amount equals fresh cash minus the immutable
legacy plan cash. Native evidence with another type, account, amount or prior
retirement refuses. Other unexplained differences remain refused.

This is an attended prospective anchor, not an assertion about which side of the
old plan-time boundary the dividend belonged to. Preserve the old plan, its
absent baseline, failure and endpoint-lag clock, all commands/fills and canonical
shadow history. Record the historical cash interval as UNVERIFIED. No old cycle
is marked successful, no trial P/L or historical finality is earned, and no
same-session order or late opening BUY is enabled.

Build the next ordinary plan from the existing verified shadow and held-target
rules. Atomically adopt that new plan, record its own current immutable cash
baseline, and append an HMAC-bound retirement receipt in the existing
`sentinel_processed_sessions` store under the distinct, explicitly retained
`broker-cash-retirement:v1:` namespace. Bind the exact predecessor and successor,
native reference, current cash cursor, reconciled account/book facts, signed
authority and operator request. A separate keyed native-reference claim prevents
using one dividend to retire multiple legacy plans. Failed preparation rolls
back both the receipt and its new anchor. A repeated request authenticates its
existing receipt and validates the already adopted successor normally; it cannot
re-anchor that successor or consume the dividend twice.
Semantic restore validates every receipt/native-claim pair against its retained
predecessor, successor and successor baseline; it refuses orphaned or altered
evidence without treating retirement rows as ordinary plan cash baselines.

## Qualification and release

Exercise the actual selected adapter and guarded current-cash ingestion against
native-shaped HTTP fixtures and private PostgreSQL. Keep ordinary observations
independent of cash reads, and prove fill/finality/LIVE quarantine separately.
Cover unavailable, malformed, changing, duplicate and corrected stream evidence,
bootstrap replay and exact cursor restart. Falsify the capability and replay
guards. Qualify retirement binding, command/UNKNOWN, time, exact cash/dividend,
fencing, authentication, atomic rollback, duplicate-reference and restart guards,
plus the joined preparation/CLI route. Preserve the old missing-baseline refusal
for recovery, execution and unrequested preparation. No fixture golden is
re-pinned to confer financial authority.

Final delivery decision, 2026-11-06: PR 570 contains the complete dashboard PR
569 ancestry and this separately reviewed cash follow-up. Use PR 570 as the
single release after its complete required exact-head CI passes, retaining PR
569 as the dashboard review record. This avoids an intermediate installation
and duplicate financial activation. Obsolete predecessor CI may be cancelled;
no test or required check is omitted from the final combined candidate.
Software installation and financial activation remain separate; an accepted
source or retirement receipt alone cannot authorize trading. LIVE and the
protected backtest remain excluded.

The complete-source seal advances to version 14 for this execution-only
successor. Preserve all 13 retained source maps, original economic mappings and
historical lifecycle commitments. Refresh only the complete candidate map and
the checker's version/digest binding; do not add a software-only or uninstalled
candidate as an admitted financial predecessor. Record the current preparation
AST change and this policy separately in the existing lifecycle delta registry,
keeping both its original historical hash and the immediate predecessor hash.
Verify unchanged installed/candidate strategy economics independently. New
receipt names are execution metadata, never immutable shadow inputs; unknown
namespaces keep their economic classification.

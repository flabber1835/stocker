# Paper system incident and operational rehearsal

Decision: 2026-10-15. The owner authorized an attended test version using the
existing Alpaca **paper** account, buys, sells and cancellations throughout the
regular session, at most USD 5,000 in open test positions, no margin or shorts,
and closing all test positions before completion. The owner will reset the
paper account afterward. This authorization supersedes the earlier read-only
investigation restriction for this bounded rehearsal; it does not authorize
real-money trading, changing production economic history or replaying missed
production orders.

## Incident: confirmed facts and unresolved cause

The installed release was main `71abaa4c158ffbeae762d7272b6204d59590fee8`,
qualified through PR 521. Its current next-open cycle prepared the October 14
decision for October 15 execution at 13:31 UTC (06:31 Pacific).

On October 15 at 01:45:52 UTC, monitoring reported WAITING_FOR_LEADER.
The same worker reacquired the lease at 01:45:53.283689 UTC with fence 71.
The configured lease was 12 seconds and heartbeat interval three seconds.
Database and supervisor observations stalled during a full restore drill,
which ran approximately 01:42:39 through 01:49:01 UTC. No production container
restart, out-of-memory kill or Windows sleep event was observed in that window.
Resource contention from that drill is the leading explanation, but retained
telemetry does not prove which host resource caused the delay.

At 13:31:00 UTC, the cycle advanced WAITING_OPEN -> EXECUTING. It encountered
WriterLockUnavailable before creating any command or informational PENDING
record, then entered RECONCILING at 13:31:57. A read-only inspection at 13:33
found the shadow service holding execution writer lock `0x5E271E10` while
streaming snapshot rows. The trading recovery callback acquired the writer
subsequently. Recovery then failed permanently because raw-plan convergence
required the pre-mutation PENDING stamp that the failed execution had never
reached. At 13:39 the cycle was BLOCKED. Native account reads confirmed no
orders or positions and USD 50,000 cash. The missed production cycle remains
preserved; this document does not authorize reopening it.

The failure crosses scheduling, shared ownership, execution and recovery.
Successful tests of those components separately did not establish the complete
concurrent service workflow against Alpaca. Test counts and signed release
identity are not evidence that unexercised provider transitions have worked.

## Decisions before implementation

1. Rehearsal has a distinct, explicit paper-only operating profile and durable
   run identity. It may submit during the actual regular session. Production's
   next-open deadlines remain unchanged; no clock spoofing or late production
   replay is permitted.
2. Pause production order submission through supported controls before test
   broker mutations. Use a separate test journal/database and command namespace.
   Record the original book, plan, binding and failed-cycle history before and
   after; do not relabel test fills as production strategy performance. Preserve
   existing credentials. Test ownership is exclusive and bounded to the account,
   regular-session lifetime and approved USD 5,000 exposure.
3. Exercise the real execution membrane, not only API availability. Provider
   probes also cover a deliberately nonmarketable limit order and explicit
   cancellation without extending production order types. All test orders carry
   attributable identities and receive terminal-state reconciliation. Cleanup
   cancels only this run's working orders and sells only this run's positions;
   unexpected activity or UNKNOWN outcomes must stop new purchases.
4. A recovery entered before any transport must be distinguished from recovery
   after a submit might have landed. Missing PENDING evidence must never be
   invented for possible broker effects. A proven unsent plan can return through
   the ordinary executor, which creates the stamp before its first mutation.
   Contradictory evidence, stale authority and unresolved outcomes still refuse.
5. Background verification of an unchanged immutable publication must not hold
   the account's exclusive writer lock for a full corpus scan. Actual publication
   and book mutations remain serialized and independently revalidate their
   inputs and state before commit. Qualify the open-time interleaving explicitly.
6. Replace the hourly size-triggered backup ritual with one daily verified base.
   Prefer 09:00-12:00 UTC (before the US open), at least 12 hours after a fresh
   installation backup; fall back at 24 hours. Renew early at 8 GiB of WAL or a
   timeline/image change. The hard chain bound is 16 GiB / 1,024 objects. Do not
   start heavy work from 12:30 through 21:00 UTC, covering both US market hours
   and daily preparation across daylight saving changes. Existing archive,
   storage, age and chain guards still fence if headroom is exhausted; deferral
   never grants authority. There remains one full semantic restore per newly
   selected base, because accepting untested base generations would require a
   separate recovery design. Ordinary preparation, close, activation and restart
   reuse that result; they do not create another base or drill. Limit restore
   workers to half a CPU each, in addition to their memory and process limits.
   Reuse an in-process WAL content proof for at most five minutes, bound to its
   database, system ID, selected base and exact unchanged object metadata and
   checksum sidecars. Hash all new/changed objects twice immediately. Restart,
   expiry, base/timeline/metadata changes and any failed proof force a new full
   scrub. Coarse timestamps cannot prove content immutability: silent corruption
   that preserves size/metadata may therefore remain undetected until the next
   five-minute full scrub. This explicit bounded detection interval replaces
   full-chain byte scans at every nested callback. No proof may extend its
   original expiry merely because it was reused. Qualify expiry and tampering,
   daily cadence, deferral and hard bounds before accepting this policy.
7. Correct the dashboard's plan ticker lookup, dated preview, mobile tables,
   recorded-account labels, recovered-alert explanation, normal waiting wording
   and unkeyed disclosure preservation. Display freshness remains honest; no
   fabricated current account observation or performance is permitted.
8. Use the existing exact-source compatibility profiles to preserve the book
   across the reviewed changes. Extend the market-open profile to the unchanged
   worker path, pre-transport stamp classification, dated plan display and the
   separately approved backup policy. Preserve predecessor digests and pin the
   exact new bytes. Profiles naming the same files must agree on the reviewed
   successor, with their module/profile authentication intact. Compatibility
   grants no signed production trading authority and never reforms the book.
9. Isolated PostgreSQL 17 measurement at 1 GiB / one CPU found a maximum-chain
   cold proof took 58-66 seconds and unchanged-object reuse took 7.45 seconds.
   Replace per-object forked `stat` calls with a bounded GNU `find -P
   -files0-from` lstat pass over only required paths. Require both successful
   traversal and exactly two positive regular-file/single-link results per
   required WAL object, including its sidecar. Missing, omitted and aliased
   entries must refuse. Preserve directory/metadata checks and the post-proof
   recheck. Hash at most four objects per SQL statement, keeping statements
   within short caller timeouts without changing total proof bounds. The
   measurement is a local sparse-file result, not production-media certification.
10. The unchanged-session path verifies content and current publication once in
    a pinned read-only snapshot, retaining that snapshot's row-inventory digest.
    An existing valid health projection is reused. A missing, invalid or old-
    executable projection is repaired only under a brief account lock after its
    current inventory matches the verified snapshot. This lock is coordination
    for an auxiliary file, so it uses the nonfinancial/recovery lock mode and
    performs no backup scan or book mutation. Busy ownership defers projection
    repair; it must never move full content verification back inside the lock.
11. Move attended native-command checks ahead of the adapter using the existing
    canonical GuardedExecutionBroker. A refusal then carries its single-use
    no-transport proof and restores only SEND_PENDING to PLANNED through the
    existing journal operation. The HTTP client consumes a short-lived,
    exact-request ticket issued after those checks, rather than repeating
    refusable quote I/O inside submit. Keep the real adapter's capabilities,
    clock, next-open window and certification requirements intact. This fixes
    test-boundary placement. Existing UNKNOWN records remain untouched.
12. The owner approved the remaining timing changes on October 15. A clean
    READY_TO_EXECUTE recovery before execute_at enters RETRY_WAIT with its wake
    at execute_at; only expiry beyond the existing upper cutoff supersedes it.
    Recovery never itself submits. The default service obligation remains XNYS;
    a private overridable schedule method permits an isolated test service to
    use a persisted intraday slot, with real wall time and PostgreSQL time.
13. Intraday tests use a distinct AttendedPaperExecutionGrant naming one run,
    account, plan, effective session and at most 30 minutes within the real XNYS
    session. The canonical guard keeps instrument, clock, quote, cash and
    pre-transport checks, but applies this explicit window to attended grants.
    That grant never receives a composition-issued certification identity.
    A tools-only Alpaca subclass reads actual IEX quotes using the canonical
    parser throughout the approved test window; only quote-acquisition timing
    differs. It fixes the PAPER endpoint and inherits the actual submit,
    cancellation, lookup and observation implementations. Production's adapter,
    quote acquisition window, default schedule and late cutoff are unchanged.
    Fresh owner/budget/paused-production checks remain mandatory per mutation.
14. The isolated service campaign reuses AutomationService and its durable
    cycles, lease, heartbeat, retries and recovery. Its callbacks authenticate
    the copied publication/book, build the canonical allocated plan, and use
    the native execution journal, reconciliation and executor body. They have
    no signed production activation authority. Record real service concurrency,
    pre-transport writer refusal, recovery and restart separately from provider
    probes and deterministic fault tests. Test scheduling and paper fills must
    never appear as production strategy history.
15. Unchanged-session verification must retain the existing bounded garbage
    collection pass; skipping it strands obsolete price payload. Run that pass
    after the read-only verification has ended, through its existing best-effort
    ownership and pin checks. Defer its writer acquisition from 15 minutes
    before the actual XNYS open through 10 minutes after it, so neither a cold
    backup proof nor cleanup competes with opening execution. This deferral
    grants no financial authority and never changes retention pins or bounds.
16. Production supervision forks each callback. The attended callbacks must
    therefore reload their plan and native instrument mapping from durable
    evidence at every boundary; no parent object mutation is a handoff. A
    post-prepare recovery without that exact plan is a refusal, never a clean
    empty-account success. Forked callbacks must not use an inherited psycopg
    connection. They verify the parent's exact advisory owner through a fresh
    connection, matching backend PID, backend start and the account lock key.
    Parent death or lost ownership prevents subsequent mutations. Preserve the
    first service fixture as FAIL: it produced no orders and its empty-plan
    terminal state is not evidence that the basket succeeded.

The owner explicitly approved decision 6, including its five-minute integrity
interval and 8/16 GiB limits, and decision 8's exact compatibility-profile updates
on October 15, 2026. Implementation follows those approvals; deployment is not
claimed by this design record.

## Attended test profile

The actual database is copied into an isolated PostgreSQL server. Historical
book reads authenticate the original retained identity; they do not claim the
candidate process has signed production admission. A separate native execution
database owns only rehearsal plans, commands, observations and cycle events.
No production database rows are copied back. The test account allocation is at
most USD 5,000, sized by the canonical account-scaling adapter over the unchanged
Wealth Core state. The original USD 50,000 account value is retained as an
independent provider fact; the test allocation is explicitly labelled.

Completion requires the real automation state machine, canonical plan adapter,
PostgreSQL journal, reconciliation and executor body. The implemented provider
and native-journal probes do not yet complete the automation-state-machine
campaign. The intended transport
boundary independently requires the owner-approved account, exclusive test
ownership, production disabled and killed, the real open session, the exact
durable test command, fresh prices, cash, long-only quantities and the USD 5,000
cap including working purchases. Production's signed activation, database-
incarnation and next-open scheduling fences remain unchanged. Their expected
refusal on the isolated intraday test database is recorded separately. The
attended profile supplies the distinct test boundary around the reused executor
body; it never marks those production fences PASS or manufactures a signed
certificate. This distinction is necessary because a restored test database
started during the session intentionally cannot acquire ordinary production
next-open authority on the same day.

Kill the test process after an accepted submit but before its acknowledgement
is journalled, then recreate it against the same execution database. Positive
exact-key reconciliation must settle SEND_PENDING without another economic
order. Finish the bounded basket, verify repeated execution submits nothing,
then run an explicit test cleanup plan to flat. Do not claim a provider partial
fill or cancellation race occurred unless the native evidence actually shows it.

## Required qualification record

The native SPY restart probe passed: process death after provider acceptance left
SEND_PENDING; exact-key recovery reached FILLED without another purchase. The
larger canonical basket has **not** passed. Five buys filled, then the test HTTP
guard refused ATEX with a 34.7-second quote. Placing that local guard inside the
adapter caused the conservative adapter to retain UNKNOWN. Native absence is
not finality evidence and that record was not rewritten. Five confirmed holdings
were closed through the separately journalled, explicitly owner-authorized API
probe cleanup. The combined ledgers reconcile; the failed native journal is
closed to further use. The candidate now checks the attended grant through the
canonical GuardedExecutionBroker before calling the adapter, with an exact,
single-use HTTP ticket. A refusal at that boundary uses the executor's existing
one-use proof of no transport. Targeted tests pass; real-provider basket
requalification uses the now-approved isolated schedule. Do not fabricate
a broker rejection or retroactively restore UNKNOWN to PLANNED.

The owner approved both scheduling decisions following automatic approval
review. Early READY_TO_EXECUTE recovery is a source edge-case finding, not the
observed cause of the October 15 miss. Its repair and the isolated intraday
profile require targeted falsifiers and actual service rehearsal before review
readiness; approval is not a qualification result.

Keep a scenario ledger with expected transitions, actual provider evidence,
command identities, timestamps, cleanup, result and untested limits. Cover:

- Startup, current data, canonical book and controller, dated preparation,
  account binding, first execution, native fills and cash reconciliation.
- The exact writer-contention -> unsent recovery -> fresh execution path, with
  real service concurrency and the actual retained production-scale inputs.
- Submit/lookup/observe, buy and sell fills, resting-order cancellation,
  terminal cancellation, duplicate-key behavior, accepted acknowledgement loss,
  process restart and recovery without duplicate economic orders.
- Partial fills and cancellation/fill races when actually observed; deterministic
  simulation covers cases the provider cannot reliably produce. Do not call a
  simulated or unobserved provider scenario a live-provider PASS.
- Kill/deactivate/restart, foreign-activity refusal, UNKNOWN preservation,
  insufficient permissions/funds, stale quotes and closed-session refusal.
- Daily source/book preparation and notifications, full restore and retention,
  failure visibility, mobile and desktop status consistency under refresh.

The final PR includes the root-cause report, fixes, exact tests and the real
paper-provider ledger. A valid delivery is one reviewed feature branch and PR
against current main; test execution alone is not repository delivery.

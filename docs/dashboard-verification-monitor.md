# Independent dashboard verification and background refresh

Decision: 2026-10-11. The operator observed repeated CHECK IN PROGRESS and a
worker-status timeout while the actual shadow publisher and paper scheduler
were healthy. The financial reader currently uses one identity for independent
shadow proof and PAPER transport observations. A paper cycle or observation can
therefore discard a valid shadow proof. Refresh is also driven by HTTP requests,
so an idle or sleeping browser returns to a cold financial check.

This decision supersedes the combined identity and request-driven refresh in
`current-dashboard-evidence.md`; its original validity and failure rules remain.

## Proof ownership

Keep the canonical full retained-data verifier and its original ten-minute
display lifetime, five-minute refresh threshold and five-minute execution
deadline. Its result is display evidence and grants no trading authority.
Separate shadow and PAPER observations and their invalidation identities.
Broker observations, commands, activation control and scheduler progress belong
only to PAPER. Shadow proof binds the immutable book, accepted publication,
reviewed executable/configuration and the rollout/plan facts actually used in
its exposure and book annotations. A changed economic input or annotation
withdraws the affected current proof immediately. Neither scope can promote
the other's failure into a financial failure or conceal a current failure.

The panel owns one background monitor for its fixed configured database. It
starts at HTTP application startup and checks both identities independently
while no browser is connected. The HTTP path still reads current compact
identities and operational facts; it does not trust a monitor snapshot after
identity change. It reads the owned observations without starting extra jobs.
Configuration changes replace the monitor's scope, never replay old results.

At most one expensive financial observer executes per panel process. Separate
scope jobs share one finite execution slot and cannot multiply the existing
1 GiB panel budget. A queued observation has at most five minutes to acquire
that slot. Its five-minute work deadline starts only when acquired; its total
queue plus work interval is at most ten minutes from the original request.
Queueing and checking carry explicit finite recovery evidence and different
wording. A stalled worker, failed observation, unreadable identity or exhausted
bound remains a failure. Shutdown stops the monitor; finite subprocesses retain
the existing parent-death and reap rules.

## Worker liveness

The worker reader remains a finite spawned filesystem observation. Avoid the
large feed/publication import used only to compute an HMAC by sharing the exact
existing receipt-signature primitive in a small dependency module. Under the
production CPU quota, even importing the producer's schema in each spawned
reader can exhaust the two-second deadline. The spawned probe therefore reads
only a bounded raw filesystem snapshot, including negative markers before and
after the status file. The already initialized panel authenticates and validates
that snapshot with the canonical producer schema and attempt/binding guards.
No filesystem observation is moved into the unbounded HTTP thread. Preserve
canonical bytes, purpose domain, configured secret, constant-time comparison,
runtime/database/attempt identity, critical-marker dominance, original producer
clock and 60-second expiry. This changes startup cost, not timeout or authority.
Do not extend a proof or convert an unreadable worker into healthy.

## Presentation

Keep a still-current successful result visible during routine refresh, with
its original last-verified time and a background-refresh detail. Expired values
are visibly LAST KNOWN and unverified. Pending work says what is being checked,
elapsed time and its original deadline. Known failures stay visible through
retry. Waiting for the market open and untransported paper alignment remain
amber. Failed or unreadable required facts remain red; finite refresh alone
does not make otherwise verified independent facts red.

## Qualification and release

Exercise the actual Reader, monitor lifecycle, JSON, HTML and browser refresh.
Prove independence on broker-only changes and withdrawal on shadow input or
annotation changes. Cross several proof lifetimes with no HTTP traffic, queued
and slow work, identity changes during checks, failures, expiration, rollback,
shutdown and concurrent requests. Falsify guards to prove stale/negative evidence
cannot stay green. Measure actual spawned worker reads under CPU contention and
reject missing, stale, tampered, foreign or critical observations.

Pin the exact UI/source transitions and additions in a separate independently
authenticated retained-source profile, including complete preceding and
installed source closures. Preserve the actual canonical book, account binding,
old cycles, receipts and command journal. Qualify the exact candidate with
isolated PostgreSQL and retained production data read-only. Merge only after
required exact-head checks pass, install the protected certified image, perform
the normal retained activation and any necessary generic unsent recovery, then
verify current dashboard colors and next-open paper readiness. No manual orders
or unreviewed execution changes are introduced.

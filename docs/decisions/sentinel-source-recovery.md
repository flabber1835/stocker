# Source identity reconciliation and autonomous recovery

The September 2026 NAS failure exposed an assembly gap: restated SEP symbols
and lagging TICKERS metadata can describe the same security without sharing a
label. Repeating a full historical capture cannot repair that join. The
production worker already uses `RecoveryAutomationService`, whose recognized
temporary failures do not expire. The base service's finite retry budget is
not the production availability policy.

## Identity authority

Permanent identity continues to come from TICKERS. A separate pure projection
may join labels using paired, same-date ACTIONS `tickerchangeto` and
`tickerchangefrom` records. The NAS response proves that the primary ticker is
restated: `tickerchangefrom.ticker` names the successor, its `contraticker` names
the predecessor, and the matching `tickerchangeto` can have the successor in
both fields. Accept that exact shape or the un-restated reciprocal shape; do
not discard a self-labelled `tickerchangeto` as a meaningless event. Both source rows
are retained; a relationship, merger, company name, relatedtickers token or
price resemblance never grants this authority. A component must have exactly
one TICKERS permanent identity and an ordered, nonbranching, acyclic rename
chain. Conflicting identities or incomplete pairs cannot supply aliases.

Source aliases cover the anchored listing history because Sharadar restates
historical SEP under the new label. Broker labels remain effective-dated. An
active predecessor ending on the exchange session immediately before a proven
rename may extend through the explicitly bounded observation horizon; this
adds an expected security to coverage rather than excusing absent prices.
Delisted predecessors cannot grant this extension. Exact canonical membership,
duplicate identity detection, price domains and split checks still apply.

Raw TICKERS, ACTIONS and SEP are never rewritten. Seed coverage commits to both
the TICKERS observation and rename source-row identities. Candidate and
published resolvers must derive the same mapping from their own publication
scope. A source-only mapping cannot become a broker mapping before its ACTIONS
generation publishes. Existing historical rebuild guards remain in force.
Rebuild replacement checks use the same derived intervals as replay, so stale
raw listing endpoints cannot turn a missing renamed bar into deletion authority.
A newly discovered or changed rename older than the daily ACTIONS window must
take the retained full-source recovery path before daily publication. Compare
the effective rename claims with published ACTIONS before that exact window;
name-only changes do not alter this identity comparison. This keeps the
preflight and database resolver consistent without redownloading full history
for an ordinary rename inside the daily window.

## Recovery

Recognized source incompleteness stays a durable REFRESH wait. Source waiting
does not authorize a plan, advance a publication or release a kill switch.
Unknown programming failures, credentials, schema and signed authority defects
retain their existing blocking behavior. Historical identity changes take the
existing bounded retained-corpus recovery path.

For a known exact-coverage refusal, persist a bounded probe hint (failed
session and missing permanent identities) with the retry diagnostic. Subsequent
attempts first read only those TICKERS records and one SEP session. An unchanged
failure avoids another historical download. A successful probe permits a fresh
full proof; the probe never certifies a publication. No failed candidate data is
promoted or reused as authoritative source evidence.

The real worker, lease, callback subprocesses, durable wake and restart path
must be tested with PostgreSQL and a controlled HTTP source. Preserve separate
tests for signed authority and the paper execution membrane. Test reports must
name any fixture seams rather than presenting an injected callback test as a
complete NAS deployment. Required falsifiers include missing reciprocal rename
evidence, conflicting permanent identities, source waiting beyond the old retry
budget, process restart and healing, kill fencing and expired execution windows.

Durable retry transitions store notifier metadata inside `diagnostic`. Live
enqueue and crash reconstruction consume that canonical shape, with a fallback
for existing flat events. They must emit one idempotent notification without
stopping the worker when it enters source waiting.

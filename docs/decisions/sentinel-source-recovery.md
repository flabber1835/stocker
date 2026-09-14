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
`tickerchangefrom` records. The NAS response proves that the primary ticker can
be restated with a later label. In the same-primary representation the two
`contraticker` fields name the event's predecessor and successor. Accept that
paired shape or the un-restated reciprocal shape; do not discard a self-labelled
`tickerchangeto` as a meaningless event. Both source rows
are retained; a relationship, merger, company name, relatedtickers token or
price resemblance never grants this authority. A component must have exactly
one TICKERS permanent identity and an ordered, nonbranching, acyclic rename
chain. Conflicting identities or incomplete pairs cannot supply aliases.

The follow-up NAS run at `0620545` exposed restatement of *older ACTIONS*
primary labels as well. On 2019-04-02 both CYCNV-to-CYCN rows carry primary
`ticker=KRSA`; on 2019-03-15 and 2019-10-29 both CHACU-to-CHAC and CHAC-to-PHGE
pairs carry `ticker=HLSQ`. In this representation the same-date, same-primary
`tickerchangefrom.contraticker` is the old symbol and
`tickerchangeto.contraticker` is the new symbol. The primary ticker is a source
label, not necessarily the symbol introduced on the event date. Retain support
for the reciprocal representation where the two primary tickers are the event's
old and new symbols.

Build every explicit pair before validating the complete chronological chain.
A restated primary label must be the event's successor or a later successor in
that same proven chain; an unrelated primary label grants no alias. Every rename
claim touching the component must be accounted for by its pairs. Unpaired or
competing claims, branches, cycles, reused symbols, conflicting permanent IDs,
and unsupported listing intervals continue to refuse. The observed full chains
are `CYCNV -> CYCN -> KRSA` and `CHACU -> CHAC -> PHGE -> HLSQ`; they are regression
inputs, never production exceptions. Pair source-row identities remain in the
publication commitment, and the effective broker ticker follows the event dates.

Regression coverage must include the complete older and newer rename history,
its actual exporter CSV representation through the production capture wrapper,
historical SEP membership on 2025-07-01, and published/candidate resolver scope.
Testing only the latest September pair does not exercise this source contract.
The bounded production rebuild regression runs four market sessions and 5,606
identities with the complete ten-row historical ACTIONS export. Its only replaced
external inputs are HTTP transport, clock and test producer identity. Production
capture, exact coverage, PostgreSQL identity rebuild, normalization, post-seed
source/local proof and atomic publication execute together. A missing older pair
must preserve the prior publication without starting a database replay. This
fixture proves feed assembly for the observed source shape; it does not certify
the NAS's full history, runtime image, backup horizon or strategy warmup.

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

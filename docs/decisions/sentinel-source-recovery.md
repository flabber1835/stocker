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
The test image carries the existing Sharadar replay simulator package alongside
its tests so this integration executes against the packaged runtime without a
checkout on the import path. The deployable image does not acquire this fixture.

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

## Dated ticker reuse (September 14 follow-up)

The `eded086` NAS failure includes a second, unrelated CHACU/CHAC history.
TICKERS identifies CHACU as permanent ID 644444, listed 2025-05-19 through
2026-03-26, while PHGE is ID 113467. ACTIONS takes the older CHACU/CHAC
occurrences to PHGE/HLSQ in 2019/2026, and the newer occurrences to XNDU in
2025/2026. An undated connected component joins unrelated businesses. This
supersedes the blanket refusal of reused symbols above, not the prohibition on
ambiguous identity or incomplete rename evidence.

Build dated paths of paired rename events: a successor continues into its next
departure only before another arrival reuses that spelling. Separate departures
from a starting spelling are distinct candidate occurrences. Each candidate
still requires a complete, strictly chronological, nonbranching path, valid
restated primary labels, and exactly one permanent identity/category anchored
by TICKERS overlapping the corresponding occurrence (including its transition
date). Unpaired claims in that occurrence or naming its terminal primary refuse
the path. Disjoint paths anchored to the same permanent ID refuse together.
Rows for a later occurrence are context, not anchors for the earlier business.
Undated or overlapping competing anchors remain ambiguous and grant no alias.

Restated source aliases may span the anchored security's history, but must be
clipped before a later reuse and after a prior occurrence. Raw TICKERS rows are
unchanged and remain in the ambiguity check. Never let HLSQ resolve to 644444,
or CHACU prices in 2025 resolve to 113467. Broker labels remain event-dated.
All consumers reconstruct the same projection from scoped raw observations.

Tests must carry the actual reused CHACU TICKERS row and both ACTIONS lineages,
including incomplete unrelated lineages, competing overlapping anchors, mixed
pair formats, input reordering, missing real prices and duplicate canonical bars.
Run those observations through exported CSV capture and PostgreSQL publication,
not just the pure resolver. Record which missing source rows are synthetic.
The reused listing replaces a synthetic ordinary listing: the revised fixture
has 5,606 eligible identities on the failed July session and 5,605 in the four
September sessions, after the reused CHACU listing's recorded end date.

Before annual SEP capture, check exact membership on the first and last market
sessions using bounded date requests and the same canonical identity/coverage
rules. This is diagnostic only: it contributes no publication evidence and does
not replace stable full-history capture, source bracketing, or post-seed proof.
Use the first and last self-contained sample sessions: dates with existing
reviewed source-onset exceptions require observations from other sessions and
are left to full capture. Sampling must not invent their first-observation
evidence or introduce a new refusal for an already supported source boundary.
A failed sample must stop before an annual download or database replay. The
known-failure retry probe must fetch TICKERS for all discovered historical labels
as well as requested permanent IDs, so it sees the same reused-label context.
Bounded structured coverage diagnostics retain rejected paths, reason codes,
anchor intervals and source-claim fingerprints in the GO bundle instead of
losing the reason behind a truncated exception string.

## Concurrent source symbols (September 14 market-wide capture)

The operator capture `sep-identity-evidence-20260914T200116Z-50da6578.zip`
(SHA-256 `89bb5da971cc2f886a1ee1e9a086c53a526224ee8997a859e87e358a24978488`)
contains two matching reads of all 20,966 SEP TICKERS rows, 26,220 rename
ACTIONS rows, and market-wide SEP on July 1 and September 11. The first date
has no identity collision; the second has two: OCLTU/OCLT -> 6401005 and
BRTMU/BRTM -> 6399775. Both successors lack their own TICKERS identity. Their
bars have different prices and volume. These are actual source rows, not a
synthetic population substituted around a single failure.

Issuer filings independently explain the distinction: OceanLight's
[September 10 release](https://www.sec.gov/Archives/edgar/data/2137679/000182912626010007/oceanlightacq_ex99-1.htm)
and B&R's
[September 8 release](https://www.sec.gov/Archives/edgar/data/2131350/000119312526385209/d102609dex991.htm)
describe separate trading of shares while unseparated units continue trading.
Those filings explain the diagnosis; they do not supply a Sharadar permanent
identity or become an alternative runtime data source.

Paired rename records are therefore insufficient when observed SEP symbols
collide at the permanent-security/session grain. Do not resolve this by
first/last price, volume, ticker suffix, a generated permanent ID, ignoring the
successor, or reducing the eligible denominator. Keep the entire candidate
unpublished. Collect every collision in the acquired sample before refusing,
with deterministic bounded examples, total counts, and a digest covering all
collision witnesses. Preserve the source prices, native listing anchors,
derived aliases, and paired rename evidence in the existing GO diagnostic
envelope. A true repeated source key remains a separate integrity failure.

Run the small membership samples using independently repeated rename-only
requests before the complete ACTIONS export and annual SEP capture. Repeat the
check against the captured complete ACTIONS authority before history replay;
the early sample grants no publication evidence. Both endpoints are acquired
before reporting a collision, so a first-date conflict cannot hide a second.

The typed identity-collision refusal is a source-data wait in REFRESH. Its
durable hint retains the involved symbols as well as permanent IDs: querying
only aliases that still resolve can hide a conflicting successor after a
metadata update. Bounded rechecks must retain that context and refuse unknown
or duplicate resolved identities. Corrected TICKERS may establish distinct
identities; a successful recheck then permits the full proof, never publication
or broker execution by itself. Unchanged captured data must continue to refuse.
The code repair cannot manufacture the provider metadata needed for GO.

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

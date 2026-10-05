# Acquisition that makes progress across retries

The September 28 NAS bundle for `3172e41c` shows cached SEP passes of 12,
14 and 14 partitions, each restarting at the first partition, then a reference
checkpoint refusal. Hash-only checkpoints did not retain reusable staged input.
The existing unchanged, tiny-source tests did not establish eventual completion.

## Decisions (before implementation)

Retain validated acquisition parts in logged PostgreSQL tables. A part contains
its component/window, provider generation, transport provenance, canonical
content commitment and either reference payload or staged price rows. The
part and its complete receipt commit atomically under the current job fence;
an interrupted write is never reusable. Bind parts to immutable preparation
requests. Reuse checks stored content, not just a completion flag. Price readers
use retained parts directly in session/ticker order, preserving exact source
numeric text and the existing canonical normalization. The download cache is
still optional: evicting a ZIP cannot invalidate a complete retained part.
The part schema versions its validation semantics; a future incompatible source
validation change must change that schema, not silently trust older parts.

Re-observe export metadata on every attempt and at final corroboration. Retain
references across transient pauses, but compare live TICKERS and SPY/BIL before
publication. The generation and canonical source content are consistency
identities; ZIP timestamps, compression and row order are transport provenance.
An unchanged generation with complete retained data needs no new ZIP download,
CSV parse or staging. Missing/corrupt retained data is never trusted; refuse
corruption and rebuild missing retired data through the ordinary source path.

A typed source revision terminates the current attempt. Foreground GO may make
at most three successor attempts, all with the original absolute database
deadline and exact frozen request. A successor reuses verified matching parts
from its predecessor, excluding the changed reference; changed SEP generation
invalidates all affected SEP parts. Arbitrary integrity, authentication, schema,
resource-limit and ownership failures never enter this recovery path. READY
candidates remain immutable and are never repaired in place. A target-session
change still refuses. Restart links persist the retry bound across processes.
Scheduled callers keep their existing single-attempt scheduling semantics.

Network slices apply to individual acquisition units, not an ever-replayed
prefix of the complete window. The absolute job deadline and renewable fenced
lease still bound the work. No extra concurrency or limit increase is introduced.
Retained prices are preparation material, never a publication or trading
authority. Existing source corroboration, coverage, normalization, publication
CAS and atomic visibility remain mandatory. New tables install only through
the explicit feed migration. Old hash-only attempts are preserved and can be
superseded within the same bounded policy; no operator database reset is needed.

Retention deletes bulk acquisition payload only when no nonterminal job binds
it (directly or through its predecessor chain), under the existing maintenance
locks. A source-refused predecessor retains its parts until its original deadline
to close the refusal-to-successor gap. Receipts/restart history remain.
An active predecessor can hand matching parts to its successor without a
cleanup race. Publication retains its own canonical source/reference evidence;
these temporary parts do not become an additional historical corpus.

## Required evidence

Reproduce repeated acquisition with the old code. Then exercise nineteen price
partitions with forced pauses and fresh worker instances. Assert exact publication,
unchanged absolute deadline, no duplicate rows and one download/stage per
unchanged retained part. Exercise reference/SEP revisions, repackaged ZIPs,
cache eviction, partial writes, payload corruption, ownership loss, bounded
successors and retirement. Falsify reuse integrity, fencing and restart limits.
Use real PostgreSQL and actual source/publisher composition with only provider
responses and time boundaries simulated. Do not repeat the full economic suite.

Progress must distinguish provider waiting, downloading, retained-part reuse,
staging and source-revision restart, with partition/window and bounded counters.
Mismatch diagnostics carry safe component/hash identities, never URLs or rows.

This supersedes the no-successor foreground policy in
`acquisition-certification.md` and the hash-only worker reuse in
`rolling-snapshot-jobs.md`. It grants no economic or broker authority.

## Local evidence and limits

The nineteen-partition regression failed on the original implementation because
already completed references and SEP partitions were acquired again. The corrected
path completed nineteen partitions through at least five forced pauses, with ZIP
cache eviction and changing export packaging timestamps: 21 export transfers,
each exactly once, 758 distinct price rows and one publication. The exercise uses
the real ZIP parser, database jobs, retained storage and publisher, with simulated
provider responses. Lost commit acknowledgement also resumes on a new database
connection without reacquiring a committed part.

Targeted PostgreSQL tests cover source revisions, fixed deadlines, legacy
hash-only jobs, partial writes, lease loss, retained corruption, exact source
decimals, schema migration, GO preparation and retirement/restore. Deliberate
guard removals must cause behavioral test failures, not collection errors.

This establishes local acquisition recovery behavior. It does not establish live
Sharadar availability, NAS throughput or end-to-end deployment success. Previous
scratch-staging resource measurements do not measure the new logged retained-part
path; its capacity should be measured separately before making capacity claims.

## Alpaca reference reobservation

Decision: 2026-10-05. A real certified cold GO captured 19,037 eligible
cash dividends, then Alpaca stopped returning three of those records before
publication. The inconsistent candidate must remain unpublished. Classify a
changed action projection as the existing typed `SourceRevision` for `ACTIONS`,
so foreground GO and daily scheduler slices enter the same bounded successor
path instead of latching an unrelated operational refusal. Preserve the exact
request, original absolute deadline, maximum successor count, writer fence,
retained-payload authentication and final source corroboration.

Refresh the action component and rebuild the candidate. Reuse asset,
classification, benchmark and monthly price parts only when their existing
component generations still match. A cash-dividend change alone leaves the
raw/split price generations compatible; a changed structural-action dependency
requires acquiring the incompatible price parts again. Do not ignore changed
amounts, identities, dates or participants to obtain a verdict.

A changed Alpaca asset inventory invalidates the whole captured source generation
(`*`), including the dependent classification plan and selected universe. Merely
refreshing the inventory while retaining the old aggregate `TICKERS` component
would mix incompatible views. Reacquire that generation within the same bounded
successor policy. Malformed observations, retained corruption, lost authority,
exhausted restart limits and expired deadlines remain refusals.

Qualify removal and correction of dividends, structural-action changes, asset
inventory changes, persistent instability, and foreground plus daily-slice
recovery with real PostgreSQL. Prove zero stale publication, compatible price
reuse, incompatible-generation reacquisition and unchanged deadlines. This is
source-acquisition recovery; strategy, economic accounting and broker authority
are unchanged. Certification does not establish provider-data immutability.

# Rolling feed display metadata without a financial corpus pin

Decision before implementation,2026-11-06. The installed67458b207 runtime's
durable operator history recorded feed failure891 at06:46:36.519556UTC and
recovery893 at06:46:39.599062UTC. The condition code was
FEED_PUBLICATION_PIN_REFUSED, not a negative corpus validation, future clock or
expired input proof. The associated normal open-wait/PAPER warnings also cleared
at recovery. Fifteen-second observation samples missed this three-second fault;
neither current observation window is a clean qualification merely because its
sampled verifier/owner/worker counters are zero. Preserve that durable history.

The exact historical exclusive holder is not established. The architecture
permits normal retention to hold the same exclusive corpus lock with a five-
second statement cap, while feed display retries its shared pin for two seconds.
The existing `readers.status_snapshot` takes that pin even for the rolling
publication's immutable metadata and already recorded, publication-bound verdict.
Financial bar readers need that exclusion because the legacy corpus is mutable;
display metadata does not read those bars or create a current financial verdict.

Options considered: qualify every possible writer as a normal wait, or remove
the unnecessary dependency from the display read. Select the latter for rolling
publication display only. Keep the existing default reader, financial pinning,
legacy paths and every execution/readiness admission rule unchanged. Do not
increase a timeout, classify every lock refusal as healthy, retain a fabricated
positive verdict, extend a proof clock or acknowledge the incident as the fix.

## Separate display read, same authenticated metadata

Add an explicitly named `readers.display_status_snapshot` API for the panel.
It must run in a new REPEATABLE READ, READ ONLY transaction before any data
query. Reject autocommit connections, on which a standalone SET TRANSACTION
would not bind subsequent queries to that transaction. Reuse the exact existing authenticated `current` publication dispatch,
rolling operational binding/manifest/evidence checks, and `snapshot_matches`
fingerprint comparison. For a rolling publication only, return its declared
window end, the already measured matching readiness snapshot (or None), and
the exact optional publication version. Never read bars, recompute readiness,
enter a financial reuse scope, acquire a corpus pin, write state or contact a
broker. Do not treat missing/mismatched verdict as False or PASS. A malformed
publication, invalid authentication or binding still refuses.

A single repeatable database snapshot binds publication, operational metadata,
validation evidence and cached verdict even if a peer commits a new publication
between their reads. Immutable candidates and versioned publication metadata
remain the source of those display facts. An in-flight uncommitted change is
not visible; a committed bad binding must fail its existing check on the next
fresh observation. Ordinary PostgreSQL locks and the original SQL/parent bounds
still apply. This API grants no financial authority and is not financial replay.

For no publication or a nonrolling legacy publication, delegate to the original
`status_snapshot` with its original corpus pin behavior. Keep `status_snapshot`,
`pinned`, `readiness`, `frontier`, strategy and execution callers unchanged.
The panel is the sole new API consumer. This does not implement version history
for mutable legacy bars or relax their snapshot-stability contract.

## Transaction ownership and publication fence

The real-writer qualification exposed a second, implicit transaction-level pin
inside `rolling_store.manifest` through its parent-row reader. Separate row
decoding from financial admission: the default parent and manifest readers keep
their existing pin; an explicitly named display manifest reader must first
verify server-side REPEATABLE READ and READ ONLY, and reject autocommit. Both
manifest paths use the same candidate, layout and evidence validation. Factor
operational binding validation into one implementation with two explicit entry
points, so the display path selects only that guarded metadata reader. The
default binding and all financial consumers continue selecting the pinned
manifest reader. Reuse the existing authenticated publication dispatch without
calling the financial `current` entry point on the rolling display branch.
There is no ambient bypass flag or reusable financial authority.

The panel's acquisition-status read can leave a successful transaction active.
Its owned display helper must explicitly roll back that SELECT-only transaction
before starting the new display transaction, reapply the original remaining
statement limit, and roll back its own display transaction after returning or
refusing. Never roll back an arbitrary financial caller's transaction. Preserve
the existing two-second feed-pin retry, four-second connection limit and twenty-
second operational collection ceiling; only existing typed legacy pin refusal
may use the existing bounded retry path.

The operational publisher still checks source context and independent subjects
before and after composition, under the original owner/input locks. A newly
committed publication invalidates a superseded view through that existing
fence; display metadata cannot renew an older financial receipt or overwrite a
new negative one. All row original times, expiry, freshness, next-session and
post-close workflow rules remain in force.

## Qualification and source identity

The private data-only producer fixture uses a declared absent deployed-policy
marker and a private signing identity while constructing synthetic publications.
Its PostgreSQL WAL archiver is real. This explicit fixture scope does not claim
to qualify external-media durability; the deployed policy, backed release gates
and existing durability tests remain unchanged. Do not add this module to a
legacy bypass registry or use a production volume, key or account.

Use actual private PostgreSQL to prove rolling display succeeds under a real
exclusive corpus lock while default financial/legacy readers still refuse.
Prove a peer publication/cache commit cannot produce a mixed frame; run a
removed-isolation falsifier. Check read-only enforcement, immutable binding and
authentication failures, missing/mismatched cached verdict, unchanged original
times, default API compatibility and bounded retry. A valid display read must
not execute an expensive readiness assessment. Use existing canonical fixtures;
do not create a second strategy book or repin economic goldens.

Refresh the complete candidate source seal while preserving all twelve exact
retained predecessor maps, including the actual installed67458b207. Do not add
the uninstallede0ad188ae build as a claimed financial predecessor. Requalify the
changed readers/panel paths, source compatibility, drain fix and host delivery
before a new local PAPER operation. The prepared uninstallede0ad operation and
all failed/unfinished observations remain retained; they are not overwritten.

Future stability qualification must also inspect durable FAILED, REVIEW and
STARTED transitions since its initial head, so a failure/recovery between
samples cannot qualify as a clean interval. Bounded sampled HTTP/native facts
and durable history complement each other. A new actual stable interval,
required CI, authorized merge, signed PAPER installation and honest final
operational review remain distinct gates. LIVE stays forbidden.

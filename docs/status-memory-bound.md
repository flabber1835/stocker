# Single-request shadow status memory

Base: main `99410e5aff363f9d3d1b0b8d3dbc4e9b93ef4b45`, with reviewed #417
`c661821cc383836c74746d27faa9fcc14a609b2f` integrated as a dependency. Delivery
is a feature-branch PR; neither pending PR nor main is rewritten.

## Decision before implementation

Reduce duplicate live representations at the existing verification boundary.
Keep canonical SessionState decoding, economic validation, every genesis/record/
state commitment, publication pin and authenticated checkpoint binding. Do not
cache a verification verdict, introduce a parallel economic state, weaken a
capability, or increase the panel's 512 MiB budget.

PostgreSQL JSONB decodes are fresh, privately owned plain JSON objects. The store
can transfer these objects to its caller without another serialize/parse copy;
generic observation stores retain their defensive canonical copy. Verify a
retained genesis against the database with full JSONB equality and its row
session rather than decoding a second complete genesis. The expected genesis
still comes from canonical state decoding and its normal commitment checks.
Absence and disagreement stay distinct; only the existing initialization path
may insert an absent genesis. No projected or cached row stands in for the full
stored payload.

Cold-start restore should return its already verified observer with the result
when the checkpoint loader needs both. Bind the checkpoint against the fully
verified observer and history instead of separately preloading both payloads.
Daily closure should construct its
result from the history it just verified rather than retaining that history
while verifying a second copy in the same transaction.

For read-only status, use an explicitly consumed observer: after full genesis
verification, retain its small chain/configuration anchors and release the seed
before loading session records. The existing history validator still decodes and
validates each retained canonical session and recomputes strategy economics.
Do not return that observer to advancement callers; further observer use refuses.
Mutation/recovery callers that require a reusable observer keep the normal path.
Hash shadow commitments incrementally with the same sorted, ASCII, strict JSON
encoder rather than constructing a second whole encoded string. Genesis state
hashes cover the canonical state emitted by the already validated SessionState;
re-decoding that same emitted object is unnecessary. Independent byte-oracle
tests must prove the digest is unchanged, including non-finite refusal.

Use a cursor-local JSON decoder for the large observation rows. It preserves
the standard JSON scalar types and values, while sharing repeated immutable
short strings and float tokens within one cursor. Both token caches are bounded
to 4,096 entries of at most 64 characters and disappear with that cursor.
Mutable dictionaries and lists are never shared across rows or reads. This
changes allocation only: independent standard-json comparisons must include
negative zero, exponent forms, Unicode and nested payloads. Do not alter the
connection-wide decoder or a caller's unrelated database reads.

Canonical SessionState serialization also creates full JSON strings solely to
validate or hash them. Consume the same strict sorted encoder incrementally for
those operations. Keep the externally returned dictionary fully detached: copy
non-feed fields as before, form the bounded feed directly, then detach each
series individually. This avoids a complete deep copy of the feed immediately
before constructing another bounded copy. Feed retention, type/finite checks,
schema migration, field presence, hash bytes and economic values are unchanged.
Retain the old serializer as a test-only independent comparison loaded from the
reviewed base; compare complete dictionaries and hashes and mutate returned
payloads to verify ownership in both directions. No golden artifacts are repinned.

Acceptance must compare canonical hashes and independently expected economics,
prove read-only behavior and corruption refusal, and falsify removed checks.
Measure a fresh full-status process after a separately built 5,000-security
fixture. Retain intermediate outcomes; do not declare the resource defect fixed
until the complete request is measured below the unchanged limit. First-origin,
advanced checkpoint and HTTP/concurrency coverage have separate evidence scopes.
## One pinned read-only verification

Status resume requires a real PostgreSQL repeatable-read, read-only transaction.
Within that snapshot it compares the fully decoded retained genesis directly
against the newly reconstructed canonical genesis, including all fields and
commitments. It need not encode and send the same 68 MiB object back to PostgreSQL
for equality, or reread it during the immediately following consumed history
check. This is one verification operation within one held database snapshot,
not a verdict retained between requests. Ordinary reusable observers continue
to reread/compare the database. The status observer is consumed immediately and
never returned to an advancement caller. Tests must reject the optimized resume
outside the required transaction and prove full retained-payload corruption is
still rejected through the public status path.
## Stream complete observation payloads

For rolling read-only status only, transfer the record header with its
`initial_state.feed.series` (genesis) or `state.feed.series` (session) removed,
then stream every key/value of that object through a named PostgreSQL cursor
with a 32-row fetch batch. Reinsert the complete object before the unchanged
canonical state and record verification. This bounds wire/decoder buffers;
it does not omit any feed data or replace full commitments with metadata.
Header and entries are read in the same checked repeatable-read snapshot.
If the series path is absent or not an object, preserve that shape so canonical
decoding/refusal remains authoritative. Rolling status requires exactly one
retained checkpoint session; inventory excessive suffixes before loading their
payloads and refuse, rather than allocating multiple large records first.

Immutable scalar caches live for one cursor and remain bounded as above;
mutable objects remain independent. Generic/reusable stores keep their existing
query path. Verify full JSON equality against a direct database read, including
missing/non-object/empty series, corruption in the last streamed security, and
snapshot/row-key mismatches. The server's allocation and target throughput remain
part of qualification; moving the wire buffer is not permission to exceed the
PostgreSQL service budget.

Register a fixed pair of JSONB text/binary loader classes with the cursor adapter
map; instantiate the scalar decoder inside each loader instance. Psycopg retains
registered classes in a global optimization cache, so neither per-cursor classes
nor closures attached to classes are permitted. The first weak-reference test
caught this leak even when bypassing its JSON-specific factory cache. Decoder
caches must disappear after cursor disposal while the connection decoder remains
unchanged. Repeated full requests must also pass the unchanged process cap.

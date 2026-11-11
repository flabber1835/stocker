# Opening proof work ownership

Decision, 2026-11-10, before implementation. The owner authorizes a qualified
local PAPER correction of opening delay and repeated work. Preserve the
canonical Wealth Core algorithm/book, immutable intent, command identity,
financial deadlines, fresh broker checks and all signed authority boundaries.

## Evidence and bounded scope

The completed opening trace records approximately 243 seconds from EXECUTING
to the cash-activity refusal and another 180 seconds to clean retirement. Two
automation scans waited approximately 69.5 and 34.5 seconds behind verifier
and shadow readers. Those are advisory-lock waits, not executing slow SQL.
The cash policy is a separately owned correction; this design grants no new
cash or order permission.

There is concrete nested repetition inside one cold committed proof:
`rolling_daily_checkpoint.load` calls `runtime_admission.bind_context`, which
reads and authenticates origin/daily checkpoints, then loads them again. The
origin restore path calls `bind_context` again. Each complete read detoasts
large JSON, checks the HMAC and typed shape, and serializes the same input.
Existing callback structural material prevents later complete reconstructions
but does not remove these nested canonical checkpoint reads.

## Selected exact read reuse

Give `committed_read.proof_connection` one private checkpoint-read owner. The
only admitted members are the existing origin and daily checkpoint cursor
names. The first access runs the original complete canonical reader. Retain
only its authenticated result as private in-process bytes, never a readiness,
GO, certificate, lease, broker observation or authorization result. Restore a
detached object for each caller, including the first, so nested dictionaries
cannot mutate the private source of a later read.

Every reuse must prove the exact connection object/backend/database, active
read-only repeatable-read transaction, original transaction timestamp, native
relation identity/filenode/transaction epoch, exact cursor row
session/tableoid/xmin/ctid, the live original publication pin when present, and
the receipt-key identity. Read the small native metadata before and after the
canonical load; reject movement. A transaction boundary, different connection,
changed relation/row/key/pin, expired owner or nested foreign scope cannot
inherit an earlier result. Unknown cursor names use the original reader.
Outside the owned proof connection both readers retain their complete behavior.

This raw read reuse does not replace any current executable-context, retained
admission, runtime-source, state commitment, publication, readiness, account,
control-generation/fence, lease, revocation, clock or broker guard. Those remain
at their original callers and boundaries. There is no disk, cross-process or
cross-callback cache and no new daemon or parallel memory-heavy proof worker.

## Resource admission

The heavy-scan slot remains a resource gate, never financial evidence. Any
early release must occur only after the complete finite canonical proof and
its integrity/readiness inputs have been built and authenticated, with exact
input ownership rechecked before subsequent use. It must precede unrelated
client work and cannot admit a cold load on a warm-only miss. No shorter wait,
higher quota, skipped proof, abandoned mutation or longer financial deadline
is selected. A more specific resource-boundary change will be documented here
before its implementation once the actual call boundary is established.

The call-boundary review confirmed that the existing slot ends when the finite
committed status/guard proof returns, before execution/recovery calls a broker.
ClientRead samples inside it describe Python verification between statements.
Do not shorten that existing integrity boundary or add a new priority queue on
this evidence. Reduce its nested proof work instead. The gateway's additional
`SessionState.to_dict/from_dict` round trip also validates and normalizes state;
this patch leaves it intact rather than returning an aliased mutable graph.

## Qualification

The checkpoint files are existing `STORAGE` ports in the economic manifest,
and also legacy semantic-source seams. Preserve every manifest map/dependency
and the earlier action-compiler witness exactly. Add a separately named closed
checkpoint-read source-pair witness rooted at actual predecessor
`e4d8671cb84af325fb5000cf8eaa2a4e0cf454c7`. It authenticates complete old/new
module hashes and its own normalized reader. Only the exact qualified wrappers
may reverse to the old full bytes before the existing seam comparison. Unknown
neighbor/domain changes keep their actual contribution. The actual image/source
attestation always contains the real new reader, wrapper and witness bytes.

Use real private PostgreSQL to count complete canonical origin/daily loads,
decodes and HMAC calls for a single nested cold proof, compare exact output
against the uncached canonical path and require one complete load per cursor.
Exercise real signed checkpoints and bad signatures/shapes. Mutating a public
return must not affect another return. Prove no reuse across transaction,
connection, relation/row version, key or publication-pin changes and nested
scope exit. Missing rows retain their original meaning. Execute omission
falsifiers for the ownership/version/detachment guards. Existing warm/cold
admission, fresh readiness, source/context and writer/pin falsifiers remain
required. Measure saved work; do not claim a passing opening SLA from a count
test or one microbenchmark.

## Focused qualification result

The final consolidated private Python 3.12/PostgreSQL 16 cohort passed all 40
cases in 69.50 seconds: `test_opening_checkpoint_read_work.py`,
`test_snapshot_scan_admission.py` and `test_opening_observation_isolation.py`.
The actual nested retained-binding verifier reduced complete origin reads and
HMAC/shape decoding from two to one and daily reads from two to one, with exact
canonical output preserved. Unscoped reads remain complete. Guard-removal
oracles detected lost transaction, version, detachment and read-reuse guards.
All owned source/test/fixture hashes stayed unchanged during qualification.

Preserve the earlier development failures: the first source-equivalence test
found a new wrapper-normalization fallback error, corrected before the final
run. A full formation setup correctly refused absent backup durability in its
private synthetic database; a real archive-enabled retry still refused its
missing independent target. The final test uses the existing signed retained
admission fixture and performs no acquisition, rather than bypassing either
backup gate. This focused work-count evidence is not a complete gateway latency
or production opening SLA qualification.

## Finite private read buffers

Before implementation, cap retained serialized checkpoint material at 64 MiB
in total per committed proof. The observed automation limit is 2 GiB and its
opening peak approximately 672 MiB. Primary row storage sizes are about 3.1 MB
for origin and 10.2 MB for daily, but compressed PostgreSQL storage size is not
a decoded Python or pickle-size estimate. An 8 MiB cap could unnecessarily
disable the useful daily reuse. The 64 MiB choice bounds added retained bytes
while leaving the actual canonical graph and its real operating peak subject
to qualified installation measurement.

Enforce the byte bound while Pickler writes to its private buffer. If it cannot
fit the remaining per-proof allowance, retain no entry and return the original
complete authenticated read. This fallback changes no proof or authority.
Evict invalidated bytes before performing a replacement load. For the first
successful read, retain only immutable serialized bytes and return the original
authenticated model, avoiding an unnecessary simultaneous second model graph.
Later callers still receive independent decoded graphs. No mutable model is
stored privately and no cache outlives its exact proof owner. The retained-byte
bound does not claim to bound all transient canonical decoder/serializer memory;
the count tests do not certify production peak RSS/cgroup usage.

The final buffer-bounded version passed the same consolidated focused cohort
with five additional memory/ownership cases: 45 passed in 67.14 seconds. The
first buffer run preserved 44 passes and one test-fixture failure: the aggregate
budget used a constructor model's pickle size, whereas the actual canonical
decoded model retains different Pydantic field metadata. Sizing the actual
canonical model corrected the test without changing runtime bytes. The passing
run's complete owned source/test/fixture hashes were unchanged before/after.

Before implementation, retain a negative serialization-admission memo for an
oversize checkpoint under its exact metadata, reader function and remaining
buffer allowance. Repeated unchanged reads must still execute the complete
canonical reader/HMAC/shape validation; they only avoid attempting the same
doomed serialization again. The memo contains no checkpoint payload or proof
result. Metadata, reader or remaining-budget movement invalidates it, and scope
exit clears it. Count tests and an omission falsifier must distinguish one
serialization attempt from repeated complete authentications.

The final memo version passed all 47 focused checkpoint/admission cases in
71.15 seconds with unchanged owned source/test hashes. Oversize inputs still
performed complete canonical authentication on every read, while only the
first identical buffer admission attempted serialization; metadata, reader,
budget and owner changes invalidated that admission memo.

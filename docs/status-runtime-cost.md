# Status and daily-transition cost review

Verified main `e255a78aaf4f89d25fc634864aafd2656c6cd176`; reviewed #418 head
`846de2cd8eb3aef23052e42781739083e109421b` is an unchanged dependency. Work and
delivery use an isolated feature branch and a PR against main. No NAS or real
broker account is accessed; no certification gate is declared complete here.

## Measurement decision, before implementation

Profile the existing production initialization, status and adjacent-session
transition before choosing a performance change. Keep the previous scale
artifacts immutable. Use isolated PostgreSQL and the same deterministic input
generator. A small-universe call profile identifies work; it cannot qualify
5000-security resources. Retain profiling overhead separately from ordinary
wall-time measurements.

Measure the production runtime in a fresh process under its configured 4 GiB cap, with
input production in a separate process and PostgreSQL under its own 1 GiB cap.
The earlier 2.82 GiB setup peak includes synthetic producer data and must not be
attributed to production initialization. Status retains its 512 MiB/no-swap
cap. Record effective controls, image/source identities, OOM events and economic
outputs. An expected OOM or refusal is evidence of a gap, not a reason to raise
the production limit or synthesize authority.

The earlier handoff mentioned a 2 GiB runtime budget. Compose already specifies
4 GiB following the documented #235 correction; this work does not change that
limit. The panel is configured for 0.5 CPU, the runtime for 2 CPUs, and PostgreSQL
for 1.5 CPUs. Measurements must report actual controls rather than attributing
the earlier 2-CPU panel timings to the deployed 0.5-CPU configuration.

Any optimization must retain complete canonical bytes, economic invariants,
input-content hashes, row/command identity, transaction/ownership fencing and
restart behavior. Do not retain a verification verdict across requests or durable
commits. State copying/serialization changes require independent comparison to
the existing implementation, malformed-input tests and removed-guard falsifiers.
Source-identity changes use the existing reviewed continuation boundary.

The 100-security baseline profile attributes 3.92 of 6.12 status seconds to
Python JSON iteration. Use the standard strict JSON encoder for scalar spelling
and batches of at most 256 small scalar values. Traverse containers incrementally,
preserving sorted keys, ASCII escaping, compact separators and cycle refusal.
Long strings, large integers and unusual mappings fall back to ordinary bounded
iteration. The helper belongs in the already identity-bound session module and
is shared by session and observation commitments. No validation result is cached.
Independent standard-library serialization, adversarial values, final-element
mutation and batch-size controls must verify the change.

Real retained reference/action history is a distinct workload. Inventory local
authoritative inputs; if unavailable, retain exact missing inputs and a replay
procedure. A synthetic stress fixture can establish computational behavior and
refusal integrity, but cannot establish real provider completeness or historical
economic returns. NAS qualification and provider C1/F6/F19/C3 remain separate.

## PostgreSQL write bound (decision after isolated failure)

The isolated 5,000-security initialization OOM-killed a PostgreSQL backend under
1 GiB while `PostgresShadowObservationStore.append` inserted the full JSON text.
The cgroup recorded one OOM kill and initialization refused; the earlier shared
8 GiB fixture did not measure this service boundary. Do not raise the database
limit or omit feed history to manufacture a pass.

Build the same JSONB value inside the caller's transaction from bounded groups
of feed-series objects. Use a uniquely named, transaction-local temporary table
and balanced pairwise JSONB concatenation: no full text parse and no aggregate
that expands every nested scalar in one accumulator. Insert the complete final
row atomically into the existing append-only table with unchanged conflict
handling. The temporary table conveys no authority and is dropped on success
or transaction end; a failed transaction cannot expose a partial durable row.
Do not change the durable schema, record bytes/commitments or commit ownership.
Histories of at most one 128-series batch retain the direct insert, avoiding
temporary-table overhead for small payloads while using the same parsing bound.

The isolated storage follow-up reproduced a second OOM in the old single-SQL
genesis equality recheck. Replace its full-text parameter parse with one SELECT
and a cursor-local exact-decimal JSON decoder in the 4 GiB writer. Compare every
value recursively, preserving JSON types (true is not 1) and exact decimal
numeric equivalence to the expected canonical float spelling. A float-decoded
comparison could collapse distinct JSONB decimal values; it is prohibited.
Independent PostgreSQL JSONB equality and sub-float-precision corruption tests
must falsify lossy decoding. The SELECT supplies one coherent snapshot; no
cross-query or cached hash-only verdict replaces full evidence equality.
The 512 MiB status path keeps its consumed-observer, snapshot-bound streaming.
Test full values, last-series corruption, idempotent/conflicting retries, rollback
and temporary cleanup; measure the writer and database caps independently.
Append readback likewise owns one fresh exact-decimal compact-decoded JSONB value
and uses the same complete, type-aware comparison without another encode/decode
copy in the writer. Conflicting retries must reject sub-float-precision changes.

This helper must enter the data-semantics source identity. An old book cannot
silently adopt it without the existing reviewed continuation procedure.

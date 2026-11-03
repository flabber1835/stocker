# Exact OWN628 parent admission and historical epoch hydration

This helper design supports the IAC unit-continuation design. It grants no new
financial input authority. The sole parent is root-admitted628 through June 30,
2020, descriptor SHA
06157fd8d37a92bd5e623081374e00b2b8253b6750fa761234b19a467c798ef6.
The new helpers authenticate that exact original financial checkpoint and its
existing source516/canonical224 map, eleven inputs, committed prefixes and all
38 current/historical checkpoint gzip files. They do not adopt qualifier state
or reconstruct an older financial predecessor.

The new public predecessor specification is a deliberately limited projection
of the root admission: exact run/head/artifact/request/CP/source/input hashes,
byte lengths, dates/counts, base policy/source map, original eleven descriptors,
committed journal descriptors, immutable checkpoint-file descriptors and the
existing approved quote descriptor. Local paths, reporting precision records,
NAV/accounting values, roles, prices and quote response payloads are excluded.
The projection has its own OWN628 schema and root-admission hash. The inherited
original515 binding remains distinct from the current516 source map.

The host parent API is `admit(root, key, spec)`, returning a newly authenticated
read-only predecessor directory. `validate_contents(root, spec)` performs only
hash/raw-JSON checks and returns its current checkpoint mapping. Admission pins
the actual468 request bytes, its entire source closure, seven public/archive
members, the actual export-crypto marker, capacity receipt, both GCM inventories
and three successful stopped worker identities/entrypoints/fences. The private
request is a whole byte copy, not a JSON reserialization. Original crypto
protocol/key separation and current financial protocol pins stay distinct.

`historical_epoch(old, out, spec, quote_root=..., quote_descriptor_path=...,
checkpoint_path=None)` does not copy or write a financial book. The caller owns
all book/journal/archive copies. The context verifies the exact active516 tree,
authenticates and registers the approved historical market quote, installs the
original nine input codecs plus the CELG tenth and grouped factual eleventh,
and loads all eleven original archives in order before yielding. The eleventh
archive retains its original526 raw430 provenance; it is not relabelled628.
Ledger/SessionState restoration may occur only after the context yields.

The yielded binding exposes `parent`, `source_map`, `quote`, `descriptor`,
`objects`, `source_gate`, `source_receipt_path` and `source_args`. The latter
retains the archived `--source-successor` flag because the frozen backtest's
initial base construction omits the existing receipt metadata. A new
IacEpochSourceGate supplies the identical admitted base and returns binding
None, so no source archive/boundary is appended. It accepts only the actual628
checkpoint or one explicitly registered input-zero checkpoint.

After an unchanged zero-session628 startup, the caller's new input codec may
adopt the separately reviewed twelfth input. `gate.allow_input(next_cp,
overlay_sha256, earliest)` invokes the unchanged canonical adoption checker,
requires the same full SessionState, base, source cursor and completed count,
the original eleven descriptors followed by exactly one new input, a future
effective date and valid full checkpoint commitments. Only that exact checked
input-zero mapping may subsequently pass the archived source gate. No second
registration, arbitrary hash, state graft or repeated source boundary is
allowed. Hosted qualification must check actual source/input watch counts and
full prefixes; a helper load counter is not proof of boundary preservation.

The helper layer imposes no corporate-action role policy. The main design's
unsupported old-IAC source state is checked before the event. Independent child
target holdings/orders/exit flags and already-consumed old-Match roles remain
ordinary state and require preservation/qualification under the established
target-independence standard. Post-event New-Match-unit admissions are not old
IAC pending state merely because the SID is unchanged.

Direct tests use actual cached immutable628 metadata/prefix/archive bytes,
synthetic GCM payloads and typed stubs. They cover wrong parent/receipt/source
map/request, changed historical archive provenance, input authentication before
restore, full-state mutation, repeated input registration, wrong event date and
guard-removal falsifiers. No local Core/controller/account replay, container or
provider call is part of this preparation. Actual hosted zero/input-zero and
continuation proofs remain mandatory before financial admission.

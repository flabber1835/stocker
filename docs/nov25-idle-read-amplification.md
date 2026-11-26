# November 25 idle database reads

The live PAPER trace and broker-free read-only probes identified three independent
sources of repeated reads. The standing authority check reads the full current
reference bundle and fetches source evidence twice to compare the metadata date.
The scheduler repeatedly fetches the waiting cycle and older diagnostic history.
The scheduler health reader returns the full cycle diagnostics to report a few
fields. The PAPER verifier reads full historical mirror rows before consulting
its explanation memo. Idle phase timings also stop in the spawned reader.

## Selected changes

- Limit scheduler health responses to the diagnostic fields the health reader
  consumes. Preserve the existing clock-coherent control, lease, cycle,
  unresolved-order, and signed-authority checks. The existing-cycle lookup
  fetches only the current activation's row. Generation replacement continues
  to read and validate the complete prior lineage.
- The scheduler may reuse the result of a full waiting tick only for the same
  ordinary initial PAPER cycle before its opening wake. Recheck the current
  control, lease, and schedule, and require the same materialized row and
  complete event row versions, guarded physical database and DDL identity,
  and no other actionable or newer cycle. A missing, changed, oversized or
  overdue witness takes the full tick. Only a full tick bracketed by identical
  witnesses can populate the slot. Keep the control wake running normally on
  a hit. Replaced cycles and every due or recovery path use the original tick.
- In the dedicated, broker-free idle reader alone, keep one compact result of
  the canonical standing PAPER metadata proof. Every use pins the current
  publication, validates its binding and manifest and authenticates the current
  referenced input bytes. The same exact comparison-validation digest is
  required and its evidence must still authenticate. Cache only the date, row
  count and digest. Only a successful full canonical read can fill the slot.
  Changed publication, manifest, comparison evidence, retirement, missing
  evidence or observer restart selects the canonical path or its refusal. The
  signing and lifecycle checks still run. Financial callbacks and standalone
  authority checks cannot access the idle observer's slot.
- The optional historical PAPER explanation can reuse its signed memo before
  restoring full records. Bind it to the authenticated existing history context
  and to exact row versions of the dependency and pending rows, in a qualified
  read-only repeatable-read snapshot. Use the existing DDL epoch and the
  database, transaction wrap and relation identities. Re-read current command
  presence every time. Missing witnesses use the original canonical path.
- Include bounded, fixed-name elapsed times and row counts in the idle child
  response and emit through the parent's existing worker sink. Diagnostics
  remain independent of the proof result and may be discarded if malformed.

All current control and revocation checks, order and position gates, opening
deadlines, saved plans, and original alert and reconciliation history retain
their existing authority. No intermittent observation is promoted to a PASS.

Extend the exact retained source inventory from the installed PR #635 merge
`830357d275762ef5252afa67c8de813308c69308`. Validate the complete replacement
inventory and preserve the existing historical profiles. Source compatibility
does not grant trading authority.

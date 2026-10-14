# Backup renewal across a runtime transition

Decision recorded 2026-10-13 before implementation. The replacement runtime's
financial GO admitted its executable over the retained book, but the selected
base backup's immutable recovery marker predated that admission. The full drill
correctly restored to that marker and refused `RETAINED_RUNTIME_ADMISSION_REQUIRED`.
Repeating that same historical restore cannot prove the newly admitted runtime.

Maintenance treats an identity-bound full semantic restore receipt for a different
immutable runtime as a renewal trigger, alongside the existing age, WAL and
timeline triggers. The receipt must match the selected base, metadata digest,
cluster, marker and target LSN, with `physical_only` exactly false and a valid
immutable image reference. Missing, malformed, foreign, unbound or physical-only
evidence does not establish a runtime transition. Historical evidence authorizes
only creation of a successor; it never authorizes current-image readiness,
retention, broker activity or paper activation.

The sole existing media-lock owner creates and selects the successor through the
ordinary capacity-checked producer. Its marker captures the already committed
financial admission. The new image then must pass the ordinary exact-path status
check and full physical and semantic restore before any retention. The old marker,
receipt, book, account binding and failed-cycle histories remain immutable. There
is no admission injection into a restored database, later recovery target, cached
certificate substitution or guard bypass.

A successful producer changes the selected generation. A retry with that new
generation but no successful restore receipt repeats its restore; absence of a
receipt alone never creates another base. A successful current-image receipt
returns to the existing proof-reuse and bounded hot-retention path. Producer,
restore and evidence failures continue to refuse within existing deadlines. This
repair changes only the host maintenance coordinator; financial code, economic
identity and source history are unchanged.

Qualification covers a young predecessor with an old-image full receipt, creation
before restore before retention, a failed successor restore followed by restart
without repeated allocation, current-image reuse, and rejection of each receipt
binding/type fault. An omission falsifier must fail when runtime renewal is removed.

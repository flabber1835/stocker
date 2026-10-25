# Complete installed image identity in GO children

Decision: 2026-10-25 UTC, before implementation. The signed installation of
`dda0195ce0374c4bb4a9c322937ba6dd0819b34f` succeeded. Its separate activation
refused during daily preparation because the child lacked
`SENTINEL_TEST_IMAGE_DIGEST`. Preserve the refused request and keep execution
disabled and killed. Do not patch installed source or weaken artifact validation.

The installer independently verifies the signed software and records both
runtime and test image digests. Its activation runner carries those facts into
GO. The feed-bound preparation adapter forwards the exact bound commit and
runtime digest, but omits the already supplied test digest from Compose's
explicit child environment. Ordinary Compose deliberately grants no standing
artifact authority, so ambient host presence alone cannot supply this fact.
The retained owner-PAPER reader correctly refuses the incomplete tuple.

Forward the existing `SENTINEL_TEST_IMAGE_DIGEST` unchanged with an explicit
per-invocation `--env` argument for the feed-bound preparation child and the
operational-parity, readiness and database-health children that consume retained
runtime state. The host feed gate must still bind the exact commit/runtime image.
Do not invent a test digest, default it to another image or copy one from a
financial certificate. Missing, malformed or mismatched facts must still refuse
at the real runtime-artifact and owner-PAPER identity validators. The existing
single-runtime owner policy still requires matching runtime/test digests.

This forwards nonsecret deployment facts through existing owned GO operations;
it grants no trading authority. Preserve lifecycle locks, source and book
admission, account binding, backup guards, deadline rules and broker isolation.
The ordinary manually started Compose service remains without artifact or broker
credentials. Read-only probes remain broker-free; only the existing preparation
child receives the approved GET-only market-data context.

Qualification must capture each actual public command generator, reconstruct
only the environment its explicit Compose arguments would deliver, and execute
the real artifact and owner-PAPER validators in a child process. Cover valid,
missing, malformed and foreign test digests, and remove the forwarding argument
to prove that the test fails. Do not replace the runtime validator with a success
stub. Retain existing feed-binding and broker-isolation tests. Host scripts and
tests may change; the 403-module Sentinel source seal, financial expectations and
historical source witnesses remain unchanged.

Deliver through a new PR, exact-head CI and signed main publication. Install the
new release fenced, then queue one request from its new immutable receipt. Reuse
the verified base/WAL through the supported coordinator; do not manually repeat
backups, manufacture recovery proof or replay either refused activation request.

## Explicitly authorized local host patch

The owner subsequently authorized a local patched version while the PR runs.
This patch changes host orchestration only. Keep the installed signed runtime,
its clean runtime checkout, private environment and completed installation
receipt unchanged. Do not use the historical application-only installer, whose
archive-off requirements do not fit this backed installation.

For this one local operation, retain a separate immutable host-patch manifest:
the installed receipt/image/commit, qualified feature commit and source hashes,
qualification evidence, exact four forwarding changes and the patch loader's
hash. Identify it as locally qualified host code, not CI-certified host code.
The runtime still truthfully identifies its original signed release.

The local loader may install only the three qualified probe function definitions
and the preparation forwarding tuple. Mechanically compare each whole function
with its installed counterpart after removing the single new test-digest
argument; compare the tuples likewise. No other executable difference is allowed.
Apply these definitions only inside the original verified GO entry, through an
operation-scoped interpreter launcher. All other Python calls delegate to the
original interpreter. The canonical shell, real kernel lifecycle lock, current
CI verification of the unchanged runtime, feed gate, output guard, financial
checks, promotion and post-validation remain intact. Never replace a validator,
rewrite evidence or treat a failed operation as a pass.

Qualify the loader against the unchanged installed command generators and real
child artifact validators, including neighboring-code and missing/mismatched
identity refusals. Retain input hashes and the actual producer result. Only a
fresh completed canonical GO may be supplied through the coordinator's existing
operator-reviewed bundle/digest interface. Queue a new request; never replay a
refused one. Full semantic/physical recovery, reconciliation and maintenance
handoff remain prerequisites to kill release. The local operation is PAPER-only,
requires REQUIRED_V1 backups and preserves the backtest and canonical book.

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

## Historical local host patch

The one-time GO interpreter overlay applied only to the signed
`dda0195c` installation. Current releases carry the artifact handoff in the
installer and exercise every current GO child directly. Retirement of its feed
probe also retires the overlay entry point. The archived Git sources and
original byte witnesses identify that installation. The separate activation
loader still verifies its receipt and its shared helpers at their recorded paths.

For that release, a separate manifest bound the installed receipt, image and
commit to the host patch, its qualification evidence and the four environment
forwarding changes. Whole-module comparison limited the change to three GO
probes and the preparation environment tuple. The real installer now covers
preparation, parity, data readiness, database health and activation. Each
child verifies its artifact identity and refuses a missing or foreign digest.

## Activation review handoff

The completed local GO passed on October 25. The subsequent read-only activation
review independently exposed the same omission in
`_reviewed_shadow_lineage_preflight`: its explicit environment list carries the
runtime digest but drops the test digest. Forward the caller's existing test
digest unchanged there too. Do not default or replace it. Extend the real-child
qualification and its missing/malformed/foreign identity cases to this route.

The owner-authorized local activation repair may replace only this qualified
host function in memory. Compare the entire original module against the proposed
module after removing that one tuple member; pin the original module's SHA256.
Run the unmodified coordinator's `--request` entry under its usual systemd owner,
locks and current-image verification, with a separate immutable local-patch
manifest, qualified commit/report hashes, and retained start/result evidence.
Keep the installed checkout, signed runtime and original GO bundle unchanged.
The original coordinator must still perform every authority, restore,
reconciliation and backup-handoff gate before releasing the kill switch.

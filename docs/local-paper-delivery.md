# Resumable local PAPER delivery

The 2026-10-30 owner-authorized notification/dashboard repair uses an explicit
operational qualification manifest (`sentinel.local-paper-qualification/2`,
scope `SENTINEL_AND_CHANGED_TRACKED_V1`). Hash every tracked Sentinel packaging
input, the local-delivery host package/entry point, and every changed tracked
path. Verify the clean feature commit and predecessor ancestry before and after
qualification/build. The exact allowed-delta check still rejects unapproved
changes outside operational roots. Unchanged protected backtest/data trees are
not opened or copied merely to qualify an operational patch. Runtime packaging
must remain complete; omitting a Sentinel file, changed path or host-delivery
input refuses. The version-1 complete-tree contract remains unchanged.

This records the earlier application-only software delivery path. The owner
restored backed-up CI/PR releases on 2026-10-24; use
[the full release transition](paper-backed-release-20261024.md) for that work.
The November 5 owner-authorized local patch uses the backed adapter and its
[bounded PRE_OPEN operator-review completion](database-recovery-local-patch.md#pre_open-software-completion-with-operator-review-november-5-2026),
retaining actual amber history without acknowledgement or financial admission.
The application-only path retains its original archive-off invariants and uses the tracked
`scripts/sentinel_local_delivery.py` command on the Linux/WSL Docker host. It
does not merge a PR or grant financial authority. See the
[current operating contract](sentinel-deployment.md) and
[consolidation design](code-simplification-20261023.md).

## Required inputs

- A clean, committed feature checkout descended from the installed predecessor.
- Its completed predecessor installation receipt. The first generic delivery
  accepts the retained completed installer receipt; later deliveries consume a
  generic operation's authenticated `receipt.json` at `VERIFIED`.
- An independently reviewed JSON list of the exact changed paths and its SHA256.
  The source-only builder accepts additions/modifications, not deletions,
  renames or dependency changes. Allowed roots are `sentinel/`, `scripts/`,
  `tests/`, `docs/` and `tools/`, plus the exact reviewed `README.md`,
  `docker-compose.sentinel-automation.yml` and
  `docker-compose.sentinel-local-paper.yml` host artifacts. Other root build/
  configuration and environment files remain refused. Qualification-only tools are host inputs bound by this exact
  path list and the full qualified source hashes; they are not copied into the
  runtime image. The builder and each resumed candidate check reject any extra
  changed path outside the reviewed list.
- A completed qualification report and its SHA256, retained logs and complete
  tracked-file hashes. The report must describe the exact clean commit.
- A private operation directory **outside the qualified source checkout** with
  an existing parent. Use a distinct directory and operation ID per delivery.

The qualification schema is `sentinel.local-paper-qualification/1`. Its exact
top-level fields are `schema`, `commit`, `predecessor_commit`, `at`,
`source_files`, `results`, `source_files_unchanged` and `final`. The last two must
be true; `at` must be an aware UTC timestamp. `source_files` maps every tracked
path to its actual SHA256, including tests, scripts and documentation.

Each result has `name`, `exit_code`, `passed`, `skipped`, `deselected`, `log`,
`log_sha256` and `command`. Names are unique, exit code is zero, passed is
positive, and skipped/deselected are zero. Logs use absolute paths and retain
their exact hashes. Their final passing summaries must agree with the recorded
counts. A Boolean claim of success, an incomplete file list or a changed log is
insufficient. Produce this report from completed qualification; do not invent
results or re-pin historical fixtures to satisfy admission.

## Build, prepare and inspect

### Build ownership independent of installation attempts (November 8, 2026)

A completed build is an immutable artifact selected by the SHA256 of its original
`build.json`, not by an installation attempt's directory. A fresh operation may
use `prepare --build-record <original-build-directory>/build.json --build-sha256
<original-digest>` without invoking Docker build, copying the source context,
retagging the image or producing new BuildKit attestations. Prepare creates the
new private operation directory when its parent exists. The original build,
context, log, qualification and predecessor receipt remain in place; incomplete
builds and changed evidence still refuse. There is no automatic cache search or
fallback rebuild when explicit artifact admission fails.

For an external artifact, prepare exclusively writes `build-reference.json`
containing its original absolute path, digest and the new request digest. All
backed delivery readers, including predecessor-chain recovery and access-path
bootstrap, resolve that same pinned artifact. Legacy operations with their own
`build.json` keep their existing interpretation. A directory containing both
forms is ambiguous and refuses. An interrupted prepare retains its reference for
inspection and refuses replacement. A fresh directory can reference the same
original artifact; no rebuild or receipt edit is needed.

Reuse applies only to completed build evidence. Prepare still validates current
qualified source bytes, exact allowed changes, retained qualification logs,
predecessor receipt and candidate image/source identity. The backed adapter still
requires the actually installed predecessor. Each new operation gets its own
request, journal, canonical/current-state proof, drain and original freshness
clocks. Abandonment or expiry of an earlier operation grants no installation
authority to its replacement. A moved tag, absent image or changed predecessor
refuses; it does not trigger a rebuild.

This owner-authorized local patch changes the host installer only. Deploy its
qualified standalone checkout through the host's installer selector, preserving
the installed runtime checkout, exact image and all running services. It requires
no application-image build, application roll, financial activation or database
migration. PR delivery follows the owner's requested local stability period.

The local host selector is `/home/bron/sentinel-local-installer-current`.
It selects the qualified host tool, independently of `--source`, which still
names the exact qualified runtime source in the retained build. For reuse:

```sh
python3 -B /home/bron/sentinel-local-installer-current/scripts/sentinel_backed_local_patch.py prepare \
  --operation-dir <absolute-fresh-operation-directory> \
  --build-record <absolute-original-build-directory>/build.json \
  --build-sha256 <original-build-record-sha256> \
  --operation-id <fresh-operation-id>
```

Select the same host tool for `advance`, `resume` and predecessor recovery. Older
tools do not understand referenced operations. An installed build whose original
foundation is no longer the running predecessor cannot authorize another roll;
artifact reuse never substitutes for current predecessor admission.

The following are templates, not literal paths or identities. Replace every
angle-bracket placeholder with the independently verified value. These shell
examples run in Linux/WSL; never shell-source the installed `.env`.

```sh
python3 -B <source>/scripts/sentinel_local_delivery.py build \
  --source <absolute-source-checkout> \
  --deployment <absolute-installed-release> \
  --predecessor-receipt <absolute-completed-predecessor-receipt.json> \
  --qualification <absolute-final-qualification.json> \
  --qualification-sha256 <qualification-sha256> \
  --allowed-delta <absolute-approved-path-list.json> \
  --allowed-delta-sha256 <approved-path-list-sha256> \
  --operation-dir <absolute-new-operation-directory> \
  --commit <exact-40-character-candidate-commit>
```

Build is offline from the already installed exact foundation image. It copies
the qualified Sentinel sources into a new layer, preserves dependencies/runtime
configuration, verifies actual source and economic identities, and records
`build-started.json`, `build.log`, `source-context/` and `build.json`.
An existing build-start marker refuses automatic rebuilding. Preserve and
inspect it after failure instead of erasing it and guessing the outcome.

Use the `build_record` and `build_sha256` returned by the successful command:

```sh
python3 -B <source>/scripts/sentinel_local_delivery.py prepare \
  --operation-dir <absolute-operation-directory> \
  --build-record <absolute-operation-directory>/build.json \
  --build-sha256 <returned-build-json-sha256> \
  --operation-id <unique-lowercase-operation-id>

python3 -B <source>/scripts/sentinel_local_delivery.py status \
  --operation-dir <absolute-operation-directory>
```

Prepare validates the retained build/qualification and creates an immutable
`request.json`; it refuses to replace an existing request or receipt. The
digest-linked `receipt.json` binds each completed stage and its artifacts to
that request. Do not hand-edit either record.

## Advance and recover supported stages

### One bounded application-readiness gate (November 8, 2026)

After the shadow handoff, Compose starts the other roles without its separate
`--wait` polling loop. APPLICATIONS_STARTED records started processes, not a
claim of readiness. One final gate owns exact six-role health, advancing stable
leadership and the actual dashboard validator. It uses a single deadline:
the earlier of START_REQUESTED's original journal timestamp plus 230 seconds
(the prior 120-second Compose health, 75-second leadership and 35-second final
reader allowances), or the original successor proof timestamp plus 900 seconds.
Resume cannot restart that allowance. A monotonic bound also prevents wall-clock
adjustments during a call from extending the wait. Expired operations refuse.

Health uses one Engine event subscription for the exact candidate container IDs;
events only wake fresh inspections. Death, OOM, restart, replacement or changed
image refuses. New APPLICATIONS_STARTED records retain the observed process
incarnations so resume also detects a restart before its first health read.
Older unfinished journals lacking this field bind their first observation;
their original deadlines still apply. Health has at most its prior 120-second allowance within the common
deadline. Leadership has at most its prior 75 seconds within that same deadline;
initial absence may settle, but a changed holder, generation or fence after first
acquisition refuses. The fenced BLOCKED_UNSENT policy still requires inactivity.

The final dashboard wait is one bounded read-only child in the panel container.
It reads existing published snapshots, never starts collection, recomputes a
canonical proof, restarts applications or acknowledges history. It retries only
loopback connection refusal, HTTP 503, or explicitly named startup liveness
conditions (leader, sender, shadow worker) with no unrelated negative
condition or source error. Non-startup modes keep their exact existing dashboard
contracts. Polling published snapshots is limited to once per five seconds.
An explicit FINANCIAL_VERIFICATION automatic CHECK IN PROGRESS row may also
remain pending within its original unexpired, at-most-600-second recovery bound.
This applies only to the named shadow/book/exposure/terminals/PAPER verification
rows; a financial FAIL/UNKNOWN or an untyped/expired wait still refuses. The
ordinary strict validator must pass after completion, within the common deadline.
Strict validation runs once on the eligible snapshot, without a second HTTP read.
Malformed data, unexpected HTTP errors, financial negatives, changed plans and
strict-validator failures stop immediately. Pending diagnostics retain condition
names; unchanged diagnostic output is not repeated. The successful panel result
retains changed pending-condition summaries and the observation count, so the
receipt can explain time spent waiting after recovery. Current failures never
count as readiness, and historical review/ACK remains visible under its existing policy.

Before VERIFIED, recheck the same process incarnations, current stable leader,
all preservation/broker/notification guards and the original common cutoff.
The accepted PRE_OPEN panel's original finite health/observation boundary must
also still hold after those final guards; an expired page cannot complete.
No proof, lease, snapshot or receipt expiry is extended. This is a host-installer
patch through the existing local selector; no application-image rebuild or roll
is needed to deploy it.

### Metadata observations owned once per boundary (November 8, 2026)

Candidate validation uses the qualification validator's single fresh HEAD,
worktree status and branch read; do not run a second identical clean/ancestry
check in the same candidate boundary. Exact-object Git queries retain their
existing closed, graft-checked memoization. Current source bytes, qualification
and log hashes, installed configuration and all mutable runtime observations
remain freshly verified at each real boundary.

One Host invocation shares immutable image inspection results by exact local
digest or authenticated RepoDigest. Return independent copies; failed or malformed
inspections never populate the memo. Mutable tags are always inspected anew.
Candidate validation still performs a fresh exact-digest presence/label inspection
at every source/mutation boundary, so deletion or substitution cannot hide behind
cached ancestry metadata. Backed predecessor traversal and immutable runtime
resolution reuse those facts instead of repeatedly inspecting the same image.
The memo is neither persisted across commands nor a cache of container health,
running state, image availability at mutation, configuration or broker evidence.

```sh
python3 -B <source>/scripts/sentinel_local_delivery.py advance \
  --operation-dir <absolute-operation-directory> --one-stage

python3 -B <source>/scripts/sentinel_local_delivery.py resume \
  --operation-dir <absolute-operation-directory>
```

`advance` and `resume` use the same coordinator. Without `--one-stage`, they
continue supported stages until completion, a pending bounded schema page, or a
refused gate. With it, they
perform only the next transition. An exclusive host lock prevents competing
delivery operations. Inspect `status` and retained evidence after interruption.

| Stage | Meaning and supported continuation |
|---|---|
| `NEW` | Read-only old/new canonical proof, current prepared future plan/source, configuration, native PAPER positions and zero open orders are checked. |
| `PREFLIGHT_PASS` | Retain the full original proof and record the exact shadow container/drain target. |
| `DRAIN_REQUESTED` | Request a finite authenticated incarnation-bound drain. Existing work finishes naturally; new worker admission is held. The exact-b2 bridge uses the separately qualified kernel barrier below. |
| `DRAIN_ACKNOWLEDGED` | Preserve the original authenticated quiescent acknowledgement. Recheck it before recording stop intent. |
| `STOP_REQUESTED` | Revalidate exact identities, original proof expiry and the still-valid drain, then stop predecessor application roles. |
| `APPLICATIONS_STOPPED` | All predecessor application roles are stopped; no source/financial work is interrupted. Record additive schema-install intent. |
| `SCHEMA_INSTALL_REQUESTED` | Install exact catalog-pinned operational extensions explicitly, then verify observation/mirror history in bounded committed pages. Pending pages retain this stage and resume their existing checkpoints. |
| `SCHEMA_INSTALLED` | Preserve authenticated installation metadata and completed coverage, verify unchanged financial state, then record Compose-install intent. |
| `COMPOSE_INSTALL_REQUESTED` | Install only the qualified Compose bytes. Interrupted per-file replacement accepts only exact predecessor or candidate bytes. |
| `COMPOSE_INSTALLED` | Install exact candidate runtime fields and start only shadow; recognize a matching interrupted start. |
| `SHADOW_STARTED` | Wait for exact-image healthy shadow, then require its full canonical proof to equal preflight. |
| `SHADOW_VERIFIED` | Retain the fresh successor proof; verify unchanged state and record application-start intent. |
| `START_REQUESTED` | Recheck original successor proof freshness and unchanged state, then start all exact candidate application roles. |
| `APPLICATIONS_STARTED` | Verify six healthy exact-image roles, advancing leadership, unchanged holdings/history and a fresh green dashboard with the same saved plan. |
| `VERIFIED` | This operation completed at its recorded time; retain its receipt as a historical installation witness. |

New requests use `sentinel.local-paper-delivery/3`, with an explicit
`handoff_mode=PRE_OPEN` by default. The backed adapter also accepts
`prepare --handoff-mode POST_TRADE` under the distinct
[completed-cycle contract](dashboard-posttrade-recovery.md). Version-2 requests
retain their original PRE_OPEN meaning and original handoff clocks; an expired
deferred request cannot become a post-trade operation. Completed version-1 receipts
retain their original eight-transition historical scope; an unfinished version-1
operation cannot resume under the new coordinator.

The first exact `b2e308bb664718da373175f1a7d988d07b159ae2` predecessor has no native
drain. Its qualified compatibility path first holds that exact shadow container's
restart policy at `no`, stops only its single-thread supervisor through a bound
Linux pidfd, proves no admitted child/pending/critical work, writes the fsynced
finite authenticated barrier, then delivers fatal SIGKILL while it remains stopped.
Busy work is resumed before barrier publication and its restart policy restored.
Ambiguous publication remains stopped with restart disabled and requires recovery
of the same operation. Other predecessors use cooperative drain. This bridge is
not an account/financial recovery API and cannot signal another workload.

A future current-generation `WAITING_OPEN` plan must have over fifteen minutes
until execution, completed matching publication and no active source job,
overlapping financial cycle or uncertain/working command. Installation does not
create another plan or extend its trading window.

Preflight and successor handoff proofs each have a fifteen-minute freshness
bound. A persisted stop/start intent does not extend it. Stale proofs refuse
resume; diagnose the current state and choose an explicitly reviewed recovery.
Never change clocks, relax deadlines, edit receipts, reset a consumed stage to
`NEW`, or fabricate a replacement readiness proof. A passed preflight is reused
within its original bound; resume does not silently run a new canonical pair.
If `NEW` fails before any pass is recorded, inspect the retained failure before
deciding on an explicit retry; that retry repeats the read-only preflight.

`status` reads the receipt only. An old `VERIFIED` result is not a fresh health,
trading or readiness check. Continuing an already completed operation does not
refresh its verification time. Check the current dashboard and operational
evidence separately when a current assessment is needed.

## Preserved boundaries and private evidence

The literal environment parser retains credentials privately; commands use a
sanitized ambient environment. No credentials belong in source, requests,
reports, shell history or public diagnostics. Expanded command failures stay in
the operation's private error log; inspect it without printing secrets.

Database comparisons run server-enforced read-only with bounded statements and
small per-row hashes. Canonical corpus contention alone has a typed finite retry
inside its original proof deadline. Broker observation uses PAPER GET requests
for the exact configured account and requires zero open orders.

Only shadow, automation, panel, alert dispatcher, verifier and GET-only execution
collector are rolled, shadow first. The sender has no broker credentials; the
collector has no push signing key. The panel consumes durable finite proof
receipts and never starts an expensive observer.
PostgreSQL, its physical identity, canonical book, plans, controls, authority,
commands, UNKNOWN outcomes, fills and notification history remain preserved.
This command submits/cancels no orders and sends no synthetic notifications.
Backups, archives, maintenance, restore drills and backup verification remain
disabled. The backtest and all its files, outputs, processes and resources remain
untouched; do not reset/prune Docker or WSL to recover an installation.

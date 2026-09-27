# Host lock ownership verification

## Linux 3.10 compatibility decision (2026-09-26)

The NAS at source `78fcaa85017e6bcfa0f110f71a1a6fda8c91845b` acquired a
temporary exclusive flock successfully but its fdinfo contained only `pos` and
`flags`. The backup child therefore rejected its inherited lock and attempted
to acquire the parent's lock again. The resulting contention message did not
establish another backup job. GO uses the same verifier and has the same defect.

The decision below supersedes the fdinfo-only host prerequisite and the
read-only-verifier restriction in the original review. Keep the existing
descriptor/inode checks, lock scopes, inheritance and GO run token. Retain the
bounded fdinfo proof when a lock record exists. Malformed, unreadable or
oversized fdinfo still refuses. When readable, valid fdinfo has no lock record,
use two nonblocking kernel operations on regular local lock files:

1. Independently reopen the supplied descriptor through `/proc/self/fd`, and
   verify its device/inode. Try a shared flock on that independent description.
   If it succeeds, close that probe and refuse: there was no exclusive owner.
   Only EAGAIN/EACCES contention permits the next step; other errors refuse.
2. Reassert `LOCK_EX | LOCK_NB` on the supplied descriptor. A descriptor
   independent of a continuing exclusive owner cannot succeed. The inherited
   owner can. Never accept contention alone and never issue LOCK_UN on the
   supplied descriptor.

This fallback establishes exclusive ownership at completion, not an immutable
history of acquisition. If an owner exits between the two operations, the
second operation may acquire the now-free lock. That is safe for serialization:
success still requires exclusive ownership on the supplied, inode-bound
description. A shared-lock transition during that race can also be converted
by the kernel; callers must not concurrently mutate the supplied descriptor or
rely on preserving a shared lock after a refusal. Stable shared and unlocked
descriptors refuse before that operation. No verification path releases an
existing exclusive owner's lock, and no work proceeds on failure. This explicit
acquisition contract avoids pretending that old procfs can provide the original
read-only proof. It requires neither global `/proc/locks`, PID ownership,
privileged kcmp, kernel-version guesses nor environment opt-outs.

The autonomous deployment launcher's inherited-lock check must also bind the
descriptor to its exact lock inode and use this shared helper. Its former bare
flock call could accept a descriptor for an unrelated file. All three entry
paths must validate immediately after acquisition, before spawning work, so an
unsupported filesystem or procfs reports a capability refusal rather than
recursive apparent contention.

Acceptance covers both procfs formats with real flocks: owner/duplicate,
independent descriptor, shared/unlocked descriptor, parent death, genuine
contention, probe errors, an owner disappearing between operations, and a
replacement owner winning that race. The old-kernel format is injected only at
the fdinfo read; locking remains real. Python 3.8 and shell composition tests
must exercise the helpers. Actual NAS backup/restore remains a post-merge check.

The related host audit includes GO, deployment, backup/maintenance/media locks,
boot identity, CPU/cgroup capability selection and host memory evidence.
Container-only GNU utilities are not host prerequisites. Missing MemAvailable
must remain UNMEASURED, not healthy or a fabricated memory estimate. No database,
strategy, broker authority, backup generation or production permissions change.

Step 1 review on main `65e261312ec219e014f062c0b6b374066db19d75`
found that the backup and GO lock verifiers established contention at the lock
inode, but did not establish that their supplied descriptor owned that lock.
An independently opened descriptor is not the same open-file description as
the inherited owner descriptor. Accepting contention alone can break the
single-publisher backup and single-lifecycle GO contracts.

Before implementation, retain the existing flock acquisition, lock paths,
descriptor inheritance, inode binding and GO run-token contracts. Replace the
verifiers' independent contention probe with a shared read-only ownership
check against Linux `/proc/self/fdinfo/<fd>`. The
[kernel documentation](https://www.kernel.org/doc/html/latest/filesystems/proc.html#proc-pid-fdinfo-fd-information-about-opened-file)
defines descriptor-associated lock records. Require exactly one whole-file
`FLOCK ADVISORY WRITE` record whose device/inode matches the supplied descriptor.
Read at most 4096 bytes plus an overflow byte; absent, malformed, oversized or
unreadable evidence refuses. The verifier never acquires, upgrades or releases
a lock. A shared lock is insufficient. Do not use global `/proc/locks` or PID
equality as an ownership oracle: inherited descriptors must remain valid when
their original lock parent dies.

Supported host qualification now explicitly requires Linux descriptor lock
records in procfs. No fallback to contention-only verification is permitted.
This preserves Python 3.8 host compatibility and adds no external dependency,
database schema, broker access or new service. The shared helper must accompany
both host entrypoints in retained/provisioned script bundles.

Acceptance uses disposable lock files and real Linux descriptors/processes:
exclusive owner, duplicated/inherited owner, independent descriptor, shared or
released lock, parent death while the child retains ownership, child exit and
subsequent legitimate acquisition. Negative cases must leave the actual owner
and lock mode untouched. Existing GO phase admission, nested GO/backup
contention and backup publication lifecycle tests remain required. Focused
falsifiers must detect a disabled descriptor-ownership check and acceptance of
a shared lock. These tests invoke no NAS or real broker account.

The defect is P1 serialization integrity; it does not demonstrate that deployed
backup data was corrupted or that historical strategy outputs changed.
Recurring maintenance, directory discovery, proactive horizon rollover,
retention and full filesystem-stall qualification remain separate open gates.
Existing scope also remains explicit: backup locks use canonical target plus
host UID, and GO locks use the checkout's lock path. Different host UIDs,
different hosts sharing backup storage, or independent GO checkouts do not gain
a shared lock from this change. The deployment/maintenance ownership contract
must resolve those scopes before claiming global single ownership.

## NAS qualification handoff

After owner-reviewed merge and exact-head CI, run the retained ownership and
composition tests on a disposable clone using the supported host Python and
actual NAS kernel/procfs configuration. Preserve source/image/kernel/Python
identities, raw logs and pre/post lock evidence. All positive ownership cases
must pass; independent/shared/released descriptors must refuse without changing
the owner's lock. Parent death must preserve the inherited child's ownership,
and child exit must permit a subsequent legitimate acquisition. Missing procfs
lock records is a failed prerequisite, not permission to weaken verification.
Run the existing disposable backup publication/restore harness before deploying
these helpers. No production backup or broker mutation is authorized by this
local evidence.

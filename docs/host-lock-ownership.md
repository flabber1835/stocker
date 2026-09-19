# Host lock ownership verification

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

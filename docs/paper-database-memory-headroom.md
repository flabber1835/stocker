# Local PAPER database memory headroom

The October 26 recovery found repeated scheduler leadership losses during bulk
source processing. Production PostgreSQL had a 1 GiB cgroup ceiling, about
1.0 GiB resident usage, more than eight million memory-limit reclaim events and
measurable memory/I/O pressure, without an OOM kill. The shared WSL kernel had
5.45 GB available out of 7.96 GB. Current connection probes were fast; this
measurement does not establish that every earlier timeout had the same cause.

For this existing owner PAPER primary, choose a 2 GiB resident-memory ceiling
with a 3 GiB combined memory/swap ceiling, preserving the previous 1 GiB swap
allowance. Keep its 1.5 CPU allocation and PostgreSQL settings unchanged. This
is a live cgroup update to the exact inspected container, not a database restart
or a change to lease, execution, authority or recovery deadlines.

Before applying, require the expected primary container ID, start time and
`sentinel_sentinel_pgdata` mount, and at least the additional 1 GiB plus 2 GiB of
available host memory. Record the exact old and new limits under the owned
recovery operation. Preserve the container, image, process start time, command,
volume, system identifier and archive-on configuration. Do not reset Docker/WSL,
restart PostgreSQL, change source data or touch a backtest.

Retain a deployment override naming these two memory limits with the operation
evidence. The generic Compose template remains the 1 GiB baseline; current
application-only rolls exclude PostgreSQL and preserve this explicit primary
resource adjustment. A later planned primary reconfiguration must account for
the retained override rather than silently reverting it.

Observe reclaim pressure, connection latency and leadership continuity after
the adjustment. More memory is not readiness evidence: current source, canonical
verification, reconciliation, the next-open plan and supported application
handoff must still pass. Any remaining leadership failure needs separate
diagnosis; alerts are not suppressed to make this adjustment appear successful.

## Whole-host headroom correction

Later observations found only 300--445 MiB available on the Windows host,
roughly 3.4 GB nonpaged pool, 6.2 GB paged pool, and severe paging. WSL's
available-memory report alone was insufficient admission for a larger resident
database cache. PostgreSQL's 2 GiB usage was predominantly file cache (about
2.0 GB), with approximately 75 MB anonymous memory and 141 MB shared memory.

Revert this operation's live cgroup change to its exact original 1 GiB resident
and 2 GiB combined memory/swap ceilings. Recheck the exact primary container,
start time, image, command, mounts and archive-on settings before and after;
record both observations. This is an undo of the inspected resource adjustment,
not a restart or financial change. Preserve the original adjustment evidence
and label its retained override superseded rather than silently applying it.
Future increases require Windows physical headroom as well as WSL headroom.
Observe paging, database pressure and leadership after reverting; do not claim
that undoing the increase alone resolves the kernel-memory condition.

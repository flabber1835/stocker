# Physical backup client writeback budget

Decision: 2026-11-07, before implementation. The installed daily backup client
repeatedly exhausted its 256 MiB memory cgroup while copying the approximately
19 GiB physical database to the independent ext4 target. Docker recorded OOM and
exit 137. One kernel report charged 225,792,000 file bytes, including
217,403,392 dirty bytes, plus 31,735,808 socket bytes; `pg_basebackup` itself had
only 256 KiB anonymous RSS and approximately 6 MiB file RSS. Available host memory
was not exhausted. This is a client envelope that does not cover dirty
writeback/cache and replication sockets, rather than an unbounded Python heap.

An attended adjustment of one exact disposable client to 2 GiB RAM and 2 GiB
RAM plus swap preserved the primary database, pinned client image, isolated PID
namespace, external bind, 0.5 CPU and original deadlines. During the real copy,
an early charged-memory peak was 1,528,225,792 bytes with zero OOM/kill events.
At 100% copy completion, the sampled peak reached the full 2 GiB cap, still with
zero OOM/kill events. This does not establish spare total-memory headroom.
Verification and publication results must be retained before claiming the real
backup successful. A bounded `syncfs` assistance attempt had not solved
the 256 MiB failure and is not part of this design.

Give the canonical run-only backup client a finite 2 GiB memory envelope and an
explicit equal 2 GiB combined memory/swap envelope. Choosing an equal combined
limit avoids Docker's implicit additional swap allocation and bounds this role
independently of database size. Retain the existing 0.5 CPU limit. The measured
peak supports this envelope for the observed workload; it is not a universal
hardware, arbitrary database-size or worst-case storage-latency certification.

Keep the primary database's existing envelope and volume, canonical target and
media locks, original copy/cancellation deadlines, verification and manifest/WAL
proofs, retention, restore qualification and activation gates. A larger client
budget never makes an incomplete base selectable or grants financial authority.
Preserve the client's separate PID namespace, pinned PostgreSQL image, shared
primary network namespace and database-only credentials. PAPER remains the only
installed financial scope. No runtime Python or economic source identity changes.

Qualify the composed isolation and finite resource contract, including falsifiers
for the former 256 MiB envelope, an absent or excessive combined swap limit,
an excessive RAM envelope and a removed CPU limit. Execute the memory-guard
removal against those falsifiers. Required CI precedes the authorized source
delivery. The attended running-client adjustment is not delivery of this
recurring configuration.

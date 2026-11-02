# Exact diagnostic suffix recovery and immutable anchor proofs

This design applies only to hosted disposable discovery on PR 542. P03 and
P05 retain their independently authenticated 461 and 773 transition prefixes.
The original strict financial parents remain distinct; a diagnostic checkpoint
never becomes a financial predecessor. No canonical strategy runs locally.

The shared anchor qualification retains the exact original source-bound
prepare and after methods, including actual original prepare refusal,
missing/wrong-source falsifiers, unchanged prior state/current bars/window and
actual next-state adjacency. Replace only the exclusive cumulative proof save
with one immutable proof per newly qualified source use and an append-only
hash-chained index. Each proof additionally binds the actual source record,
financial-source hash, input hash, prior state and actual next state. This
prevents the second-use FileExistsError without rewriting prior proofs or
writing successively larger copies. Historical qualifications can seed the
seen set only through authenticated proof/committed source-record bindings.
Fresh P10/P11 discovery uses the same writer without a seed.

An exact suffix restores its own diagnostic runtime checkpoint and cursor,
round-trips it through the canonical runtime, checks the original ordered
date axis, inputs, full committed journals and event/anchor chains, then
continues through source-bound AST reuse of the existing P01 suffix. A new
disjoint book contains complete original journals; actual Journal.recover
preserves and removes unsent tails before any new append. Preserve the exact
old gzip, all complete original journals, original unsent event/anchor tails
and prior proof bytes in lineage. Only committed event and anchor prefixes
seed the active chains. No tail, other candidate, restarted origin or grafted
financial state is adopted. Checkpoint immediately after the first new
transition, then at ordinary month ends and normal/signal stop.

Reuse completed authenticated source/crypto/three-case qualification evidence.
The new worker validates exact adjacency, runtime round-trip, original source,
input and committed prefixes; it need not repeat completed historical Core
or financial cases. New transport first performs an actual marker
encryption/authentication/decryption before any parent fetch or worker. Keep
one 2 CPU/8 GiB/offline/no-swap worker per hosted VM, read-only source/frozen/
old/previous mounts, bounded traversal and export headroom, durable allowlisted
public phase/error/actual-stop receipts and seven-day key-separate AES-GCM
artifacts. UNKNOWN never permits a mutable snapshot.

P06/P07 can supply an explicitly source-bound discovery context extension
without modifying this common continuation machinery. Any such extension
must retain the same prior checkpoint and membrane and document its own
qualification. Exact float trims still refuse; no trades, prices or terms
are rounded, invented or skipped. PAPER, main and production remain untouched.

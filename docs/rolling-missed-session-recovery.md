# Preserve the book across missed sessions

User-approved recovery policy: preserve the existing canonical strategy state
and replay missed XNYS sessions in order. Never replace the book with a fresh
performance segment. Holdings, pending decisions, stop history, cooldowns,
controller state and the original capital/genesis remain continuous. Broker
reconciliation is separate; reconstruction creates no historical orders.

## Dated inputs, not backdated current data

The first supported recovery source is retained, authenticated operational
publications, one for each missing decision session. Require exactly one
eligible publication after the predecessor version, published after the
reviewed source-final not-before and before that session's following open.
Authenticate its receipt, acquisition strategy, sealed snapshot, source coverage,
reference history and ordinary adjacent-session continuity. Multiple eligible
publications are an ambiguity, not permission to guess which one was used.
Late publications cannot prove historical availability. Missing/retired dated
inputs produce an explicit waiting dependency naming the session; they never
cause a reset, a fabricated empty input, or acquisition using today's TICKERS.
Import of separately supplied PIT history needs its own provenance adapter and
qualification. A complete feed outage therefore remains data-dependent.

## Reconstruction evidence and fresh authority

Reuse the existing ShadowObserver, transition, input archive and checkpoint CAS.
A versioned reconstruction checkpoint records the actual recovery clock after
the following open, with a distinct status. It never claims BEFORE_NEXT_OPEN.
The canonical session append, input archive and checkpoint remain atomic.
A separately committed, authenticated reconstruction receipt binds that exact
checkpoint and predecessor receipt. It shares the append-only per-session
namespace with prospective runtime authority, with a distinct schema and scope.
There can be only one receipt per session. A committed candidate whose open was
missed receives reconstruction evidence without executing its transition again.
Crash or lost acknowledgement resumes from the existing checkpoint/receipt.

Structural inspection admits reconstructed state for the next continuation,
but current SHADOW_GO/VERIFIED requires a prospective receipt. Reconstruction
cannot be upgraded in place. The next fresh session must pass current input,
source-final, backup, runtime identity and post-commit deadline checks normally.
The production service processes at most one historical session per wake;
catch-up progress is reported as reconstructed, never current performance GO.
The same service returns to normal adjacent advancement when it reaches a
fresh decision. No broker-facing code participates in this path.

## Retention and restore

While a rolling checkpoint exists, pin every operational snapshot beyond its
session until consumption. Preserve the current checkpoint's snapshot too.
This deliberately retains outage inputs; capacity limits and storage alarms
must be qualified on the NAS, rather than deleting inputs needed for recovery.
Explicit feed migration installs this pin rule; read-only catalog checks must
refuse a stale rule. Restore distinguishes reconstructed receipts from live
attestation and authenticates the same checkpoint closure.

## Acceptance

Use isolated PostgreSQL with dated, receipted fixture publications. Compare a
continuous run and an interrupted run on identical inputs and initial state,
including real holdings and pending state. Require equal canonical economic
state, the same genesis, exact restart, and zero execution plans/commands/fills.
Falsify missing, late, ambiguous, retired and altered inputs; broken continuity;
checkpoint/receipt tampering; false prospective claims; and deletion of
unconsumed publications. Interrupt after candidate commit and after receipt
commit. Missing authoritative PIT data and deployed retention capacity remain
explicit certification gates.

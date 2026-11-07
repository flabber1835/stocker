# Backup display evidence owns its cadence

Decision: 2026-11-06, before implementation. The backup maintenance producer's
append-only observation clock determines current backup display evidence.
Trading-cycle retry timestamps cannot expire or renew an independent backup.

The retained 14:28–15:28Z observation has eight backup-red interval starts.
Each followed a trading retry wake while the latest successful runtime-chain
check was 25–310 seconds old. At 14:48:46Z the chain was only 24.69 seconds old,
but the cycle's 14:48:29Z retry wake was used as its expiry. This is a projection
ownership error, not evidence that those WAL chain checks failed.

Use a ten-minute display lifetime measured from the runtime-chain producer's
original database observation. This is the existing active fallback budget,
made explicit for the independent maintenance cadence (observed approximately
five and a half minutes). Never use request time or the next trading wake to
extend it. A stopped producer must go stale even when the next decision is hours
away. A fresh successful check must not fail because unrelated reconciliation
is running. This display rule grants no financial backup authority.

Publish the row's exact minimum of base-observation plus 26 hours, semantic
restore-observation plus 31 days, and runtime-chain observation plus ten minutes.
The signed operational envelope must expire before any such boundary. Preserve
all existing proof/cluster/base/WAL-integrity checks, typed BACKUP recovery and
the exact authenticated maintenance-progress exception. No cache clock, capacity
proof, archive guard, bounded continuity policy or maintenance interval changes.

Qualify the complete operator-source composition against real private database
evidence with elapsed and future unrelated retry wakes. Refuse stale runtime
proof even with a distant future wake; preserve hard proof failures. Test expiry
of an already composed row and remove the producer-clock selection and row
deadline to falsify the oracles.

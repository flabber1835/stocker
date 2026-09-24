# Rolling inputs in GO

The owner confirmed that the NAS never became operational and GO never passed.
Treat this rollout as a first deployment. There is no operational portfolio to
migrate. Failed-attempt rows still require an explicit inventory; preparation
must preserve them and refuse unexpected behavioral state, never reset or adopt
it. No deployment or database cleanup is part of this implementation PR.

## Shared data boundary

GO preparation selects the existing operational snapshot publisher for the exact
source-final session. A matching current snapshot is terminal success only after
its receipt, strategy request, content and current input requirements validate.
Otherwise enqueue the exact request, retaining its original deadline and job
checkpoints on retries, and invoke the existing worker. Concurrent calls use the
existing request coalescing, worker fences and publication CAS. No implicit
seed/reseed, multi-year recovery or second daily pass follows success.

Schema installation remains explicit in the existing certified preparation.
Acquisition may run outside the next-open window, but that cannot pass the
separate prospective trading deadline. Preparation issues only DATA_ONLY
publication evidence; it creates no portfolio, shadow authority or broker work.

Read-only GO probes select by the receipted publication's storage contract.
Legacy readers continue to reject snapshot versions. Snapshot readiness verifies
sealed content, complete identity coverage, the exact calendar/benchmark axis,
current price domains and population, reference/action resolution, publication
chain and selected strategy request. It has a distinct versioned scope, not a
fabricated set of legacy CDC/reconciliation cursors.

The snapshot startup/restart parity probe uses the canonical rolling cold-start
inputs, feature warmup and kernel, under one repeatable-read read-only publication
pin. It has a new explicit input scope and commits no state. Retained behavioral
state is inventoried separately and cannot be implicitly turned into a fresh
book by this proof.

Database health verifies the actual snapshot relations and indexed bounded
queries, exact schema, real shared-lock exclusion, stable publication, complete
warmup input and measured validation duration. Report the snapshot contract
explicitly. Never report legacy-table query plans as proof of snapshot behavior.

The independent writer-exclusion connection uses the caller's original database
connection configuration, including authentication. A driver's diagnostic DSN
is not reconnect authority: psycopg deliberately omits its password. Both
connections must reach the configured database; connection or authentication
failure refuses health rather than counting as successful writer exclusion.
Validate the actual GO health payload against password-authenticated PostgreSQL,
as well as the existing shared-pin removal falsifier. Credentials must not enter
the health report or retained evidence.

## Authority and rollout

The [rolling shadow runtime](rolling-shadow-runtime.md) now connects these data
proofs to a distinct bounded runtime verification scope and daily service route.
GO accepts only the explicitly supported runtime contract paired with the exact
rolling input scope and snapshot binding. An unversioned rolling data proof
still refuses activation. Historical certification, runtime attestation, paper
activation and their source/account/backup boundaries remain independent.

Retirement/retention and actual NAS
qualification follow. Replacing Sharadar is outside this rollout.

## Validation

Use real PostgreSQL publications with synthetic vendor fixtures. Verify fresh
preparation, same-publication idempotence, resumable job identity, changed source
strategy refusal, malformed content, missing domains, population loss, stale
frontiers, read-only probe behavior, immutable source inputs, canonical restart
equivalence, exact pin exclusion, unexpected behavioral state and refusal to
promote an unversioned data proof into runtime authority. Remove guards in child
processes to prove their focused falsifiers fail.

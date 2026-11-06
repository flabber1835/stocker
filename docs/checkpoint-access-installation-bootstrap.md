# Checkpoint access-path installation bootstrap

## Observed dependency and selected boundary

Two owner-authorized local PAPER attempts on November 6 stopped at `NEW`,
before `PREFLIGHT_PASS`, drain, maintenance handoff, schema installation or any
application restart. Candidate `d150caf99c537f2e135acf2185333b3565c01bdc`
executed the exact pre-index `ORIGINAL_QUERY` during its complete canonical
preflight. PostgreSQL canceled that query at the existing 15-second statement
limit. The second attempt was an explicitly reviewed single fresh attempt,
not an automatic retry; neither attempt issued a handoff proof or clock.

Retained private diagnostic SHA256 values are
`dc04c3d3bf63229f18f212e4d89db3c1c763c915bbb9141fab772968866b2920`
and `eabfbed3f5fcdfb8c2c783e205a04b550e1836e22cde8c4daef6febd3583524b`.
Both failures remain retained. No further attempt under that decision is selected.

The old installation order requires the candidate to complete the expensive
lineage absence proof before stopping applications, but can install the index
which bounds that proof only after stopping them. A cache-dependent retry is
not the selected durable bootstrap. Installing the new catalog while old
executables run would also violate their authenticated schema contract.

Decision before implementation: add one explicitly selected **local backed
PAPER PRE_OPEN bootstrap**. Preserve the complete authenticated predecessor
proof before drain. Require the candidate's unchanged complete canonical proof
after the additive access-path migration, while every application remains
stopped, and before Compose installation or any application start. This changes
proof sequencing, not the proof contents, financial state or broker authority.

## Explicit request and eligibility

The default installation path remains pre-drain candidate qualification. The
bootstrap uses a new strict request schema `sentinel.local-paper-delivery/5`
with required `canonical_proof_phase=POST_SCHEMA_ACCESS_PATH` and
`handoff_mode=PRE_OPEN`. A backed local `prepare` option explicitly selects this
phase. Old schemas do not accept the new field; generic/archive-off delivery,
POST_TRADE, POST_TRADE_SUCCESSOR and BLOCKED_UNSENT cannot select it. There is
no timeout-driven automatic fallback or reinterpretation of an existing request.
The two failed operations remain immutable; the new source/build/request is a
separate qualified operation.

Eligibility requires all existing source/build/qualification/image, Compose,
healthy predecessor, physical database, configuration, current future-plan,
source-idle, no-command and GET-only native PAPER account checks. In addition:

- The pinned predecessor must be a completed `VERIFIED` journal, not an
  APPLICATIONS_STARTED or allow-started witness.
- `BackedHost.predecessor_canonical_proof(state)` must return a nonempty proof
  from that authenticated receipt with exact preserved-state equality and
  its existing successor-proof digest. Missing or changed state refuses; the
  bootstrap never creates a predecessor proof or runs a weaker substitute.
- A bounded server-enforced read-only candidate probe must authenticate the
  existing operational installation and catalog, and prove genuine clean
  absence of `checkpoint-lineage-access:v1` and every owned component object.
  Installed, orphaned, partial or malformed components refuse this phase.
- The candidate and host must support this exact bootstrap contract. Runtime
  source/image identity and the component's exact DDL digest remain qualified
  inputs. The normal economic-runtime/Wealth Core equality build checks remain.

The metadata probe uses at most the existing canonical SQL/lock bounds
(15 seconds and one second), with a finite smaller child bound. It does not
read checkpoint payloads, run the foreign-lineage scan, grant readiness, install
DDL, change a financial row, contact a broker, or manufacture a successful
candidate canonical result.

## Immutable evidence and host interface

`host.access_path_canonical_bootstrap(state, retained)` authenticates the
eligibility above and returns metadata with `authority_effect=NONE`. Bind it
to the immutable request digest and operation ID, predecessor/candidate runtime
identities and candidate source identity, preserved-state digest, retained-proof
digest, physical PostgreSQL system, original authenticated operational-marker
hash and exact access-component DDL digest.

At `PREFLIGHT_PASS`, record this immutable
`access_path_canonical_contract` and `predecessor_canonical_proof`. Do **not**
record a candidate `canonical_proof` or a success-completion artifact. The
contract records selected sequencing and predecessor facts, not candidate
financial qualification. Preserve all ordinary preflight artifacts and the
original preflight instant. Journal artifacts are append-only: no pending flag
may later be overwritten with a different completion value.

The existing drain, matching acknowledgement, stop, financial/native snapshot,
notification, migration-owner, writer exclusion and source-lock checks remain.
The access migration preserves the original operational marker, canonical
financial contents and signed coverage body/through/head, using the separately
qualified inventory-only DDL-epoch handoff. Nothing starts during migration.

At `SCHEMA_INSTALLED`, require every application still stopped and all original
configuration/database/financial/native facts unchanged. Invoke
`host.verify_access_path_canonical_installation(state, contract)` to authenticate
the installed component marker, exact catalog and DDL digest, same physical
system and unchanged original operational marker. Then the **coordinator** runs
the unchanged full `evidence.canonical_check` using the exact candidate image,
with the original server read-only transaction, 15-second statement, one-second
lock and 300-second process bounds. It must equal the complete retained
predecessor proof exactly. Check unchanged financial/native/database facts and
the original preflight interval again after it returns.

Only that actual success permits `SCHEMA_INSTALLED` to advance to
`COMPOSE_INSTALL_REQUESTED`, adding the real `canonical_proof` plus a new
immutable `access_path_canonical_qualification`. Bind completion to the same
request, state, preflight contract, authenticated installed metadata and actual
canonical-proof digests. Audit completion time does not replace or renew a
handoff clock. The normal 900-second preflight handoff interval is unchanged.

Every later Compose/start/resume/final route for schema /5 must require the
bound completion and real proof. Missing, malformed or mismatched completion
refuses before any start. Ordinary schemas retain their existing artifact shape
and behavior. A lost acknowledgement before the completion journal append
requires another complete proof through the same original gates and clock;
partial child output is never promoted to PASS.

The same pure contract/installation/completion validator must also run when a
schema /5 receipt is consumed as a future predecessor witness or retained
canonical proof, including an explicitly allowed APPLICATIONS_STARTED recovery
witness. A digest-linked stage history alone does not replace its bound
completion evidence. Keep this validation in a small shared portable host module
so delivery and receipt consumers use the same predicate; older receipt schemas
retain their existing acceptance rules. Add positive future-predecessor and
missing/altered-completion falsifiers before qualifying the new request version.

## Refusal, recovery and qualification

A refusal before migration leaves predecessor applications in their existing
state. A refusal after index commit leaves applications stopped, retaining the
same book, journal, original marker and all operation artifacts. Recovery is
through an explicit capable qualified forward operation, not an old executable,
index removal, proof fabrication, stage reset, deadline extension or financial
acknowledgement. Maintenance keeps the previously reviewed same-unit ownership
and descriptor-release protocol; this design does not add a second loop or
physical restore job.

Targeted qualification must cover strict request/CLI selection; rejection of
unsupported/started/stale predecessors and installed/partial components;
authenticated metadata before/after a real private migration; no candidate
canonical result at preflight; complete post-DDL equality and unchanged state;
and refusal before every resumed Compose/start route when completion is absent
or altered. Add executed falsifiers for omitted canonical comparison and omitted
completion guards. Keep existing ordinary-path and prior-receipt tests passing.

The already completed d150 regression (1,783 tests in 47 modules) and 797-MiB
index/migration qualification remain evidence for their unchanged runtime and
migration bytes, not tests of this new host sequencing. Requalify all changed
host paths and their direct regressions on the final frozen source, with exact
commands and file hashes. Do not rerun or repin an unrelated Wealth Core golden
fixture. Required CI, PR delivery, local installed observation and signed PAPER
installation remain separate gates. LIVE remains forbidden.

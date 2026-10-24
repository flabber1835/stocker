# Consolidating the current PAPER implementation

Decision: 2026-10-23, documented before implementation. The owner authorized
all changes from the read-only simplification review and their qualification.
The verified starting point is `0067e90b9f3a0e3e0b8c859fe4a90212e750ef16`.
Delivery follows the existing owner-authorized local PAPER workflow.

## Scope and preserved behavior

Consolidate dashboard state, local installation, repeated account/funding
validation, retained-runtime compatibility and publisher identity ownership.
Remove unused presentation, clarify the current operating contract and give
historical tests explicit historical inputs. This is a structural refactor,
not a strategy, controller, order-type, sizing or timing-policy change.

Preserve the canonical book and its origin, processed sessions, publication,
saved plan, deployment/account/epoch/control generation, commands, UNKNOWN
outcomes, fills, notification payloads/subscriptions/delivery history and
original evidence clocks. Preserve long-only/unlevered execution, whole-share
persistent targets, authenticated prior-close references, the 100-basis-point
BUY cap, DAY terms, fixed funding ceilings and independent allocation checks.
No schema migration or ledger replacement is part of this change.

Backups, maintenance, archives, restore drills and backup verification remain
disabled. The backtest, its files, outputs, processes and resources are untouched.
Qualification uses isolated synthetic databases and a local simulated broker;
it grants no new broker authority and sends no synthetic push notifications.

## One display projection and one presentation

Introduce a typed, display-only cycle recovery projection shared by summary,
expanded execution steps and broker status. Its order is: typed availability
refusal/wait, protected DAY wait, clean execution continuation, generic bounded
retry. Contradictory typed refusal cannot fall through to a generic allowance.
Preserve phase/failure-domain filtering and the original finite deadlines.
Legacy attempt-count fallback remains explicit at the callers that already
support it; source readers retain their stricter phase-count requirement.

HTML and JSON consume the same eligibility decisions for saved future intent,
current trading run, recorded account, order outcomes and canonical slots.
These remain distinct evidence types. Missing, malformed, future or expired
evidence cannot gain current authority through rendering. Historical values
retain their original dates and negative-authority withdrawal remains intact.

Use one final stylesheet preserving the current mobile appearance, responsive
layout, keyboard accessibility, reduced motion, freshness states and push
controls. Remove unreferenced casino decoration and superseded style layers.
Share the observer row codec. Production requires the lifecycle-owned separate
shadow and PAPER monitors; an absent monitor returns unknown rather than
starting an expensive competing combined observer from a page request.
Explicit historical observer fixtures retain their named scope.

## Reuse computation, keep fresh financial boundaries

Extract common pure account eligibility and funding-evidence checks while
preserving call order and each caller's NotReady versus Refused classification.
Do not add freshness requirements at quiescent-basis recording or reuse observed
savings/deposits as new purchase funding.

Load a verified local account binding once inside each public guard invocation.
Keep the existing Boolean binding guard compatible; a new binding-returning
helper and combined runtime/configuration guard obtain their own fresh binding.
No caller-provided token, global cache or cross-transaction authority is accepted.

A private protected-projection view parses policy/references and performs its
independent allocation verification once per public operation, bound to the
exact plan/projection. A composed submission helper may return current checked
references and immutable order terms; the private view never escapes or becomes
a readiness cache. Every final submission still checks current source,
account/cash, commands, configuration, signature, ownership and clock.
Allocation construction and its independent verifier remain separate.

Expose typed share-unit evidence validation for both prior-close references and
persistent targets. Remove artificial namespace objects and private cross-module
calls. Reuse a loaded predecessor within one immutable re-derivation, retaining
its fingerprint, action evidence, episode continuity and historical behavior.

## One strict retained-runtime registry

Historical manifests and their original checker bytes remain immutable. Some
manifests authenticate the checkers themselves and the predecessor/successor
chain; deleting or rewriting them would invalidate historical provenance.

One current registry owns profile loading, strict digest/shape/source-record
validation, ordered successor edges, atomic additions, required scopes and
administrative classification. The historical modules remain authenticated
witnesses/adapters, rather than an expanding current call graph of validators.
The registry must reproduce all existing acceptance/refusal results, including
unknown neighboring edits, partial additions, altered checkers, missing files,
foreign origins and economic mutations. Specific successor edges remain
explicit; no blanket transitive compatibility or generic AST wildcard is added.

Bind the exact reviewed structural transition to the verified starting source
closure. New current helper files and modified operational files require their
exact reviewed hashes in this transition. Historical profiles are not re-pinned.
The actual current executable/source/dependency/environment identity is always
checked; registry acceptance grants no financial or submission authority.

## Publisher economics and operational lifecycle

Keep the existing logical publisher contribution in economic source identity.
Extract the fixed source/candidate/validation/corroboration/publication pipeline
into an explicit module. Its exact reviewed initial bytes contribute the
authenticated predecessor's economic hash; any economic pipeline edit has a
different contribution and cannot inherit the prior strategy identity.

The lifecycle retains schema/registration/idempotency, producer identity,
ownership/lease acquisition, bounded writer scopes, diagnostic capture and
uncertain-session disposal. A narrowly typed scope driver may provide only
operational contexts and stage observation: it cannot select the source,
replace arguments/results, skip/reorder stages or choose another pipeline.
The pipeline imports its canonical transformations directly. Keep all three
queued writer turns, reentrant mutation guards, CAS checks, checkpoint binding,
original deadlines and failure ordering.

The full executable identity covers the actual pipeline, lifecycle, registry,
scheduler and diagnostics. Qualification proves the extracted pipeline against
the installed baseline and exercises actual stage order, READY resumption,
failures, cancellation and real PostgreSQL reader/writer fairness. Move
qualification-only AST proof code to test support and migrate offline image
smokes too; runtime source acceptance remains strict and deterministic.

The same sealed structural transition contains exactly two additional economic
source mappings: `execution/held_targets.py` and
`execution/target_reprojection.py`. Only their exact reviewed candidate bytes
contribute their independently authenticated `0067e90b` source hashes. The first
uses the public share-action factor and removes the redundant predecessor read;
the second adds that typed factor without changing its existing projection
implementation. Qualification mechanically reconstructs each complete baseline
module and verifies its original byte hash, proves the extracted factor against
the old factor body, and retains financial refusal and re-derivation tests.
Every unknown neighboring byte sequence contributes its actual hash. No module
is removed from the economic source list, and full runtime identity continues
to cover all actual changed sources.

## One resumable local installer

Replace copied release-specific helpers with a tracked, reusable local PAPER
delivery command. Inputs are exact predecessor/candidate identities, an approved
source delta and an immutable operation receipt. The operation stages are
read-only preflight, quiescent application handoff, successor shadow proof,
application resume and final live verification. Preserve each stage receipt;
resume never guesses completion or restarts earlier expensive work silently.

Each resume validates current literal configuration, exact image/source,
unchanged financial/source state, PostgreSQL identity and stage ownership.
An exclusive, nonblocking host file lock serializes stage-changing invocations;
status inspection is read-only. The request is immutable and receipt stages
form an append-only digest-linked history with atomic replacement of the
current receipt. A new operation cannot reuse another operation's receipts.
Reuse only fresh exact preflight evidence; an active worker refuses the stop.
Gracefully roll only the four application services with no dependencies;
PostgreSQL remains running. Server-enforced read-only canonical comparisons and
the real account's GET-only holdings/open-order check surround the handoff.
No control, plan, authority, journal, broker order or backup writes are allowed.
Native credentials stay secret and are never shell-sourced or printed.

## Current documentation and tests

Make `sentinel-deployment.md` the concise current operating contract. Preserve
the prior chronological document separately with an explicit historical label
and links for existing anchors. Historical certification remains historical;
current readiness and current-source qualification are described separately.

Current dashboard tests assert the selected collapsed-details design.
Historical profile tests use independently authenticated historical source
fixtures; they never compare a frozen old release hash with arbitrary later
source or update immutable golden hashes to make tests pass. The two existing
excluded dashboard assertions must gain correct scopes and run again.

## Qualification and delivery order

Qualify each owned area with narrow static checks, regression tests and
falsifiers. Then run the complete affected Sentinel/script test set together,
with no blanket skips/deselections. Use the same real PostgreSQL lock tests,
actual publisher coordinator, legacy compatibility matrix, protected funding
and recovery tests, composed HTML/JSON/browser/push checks and installer stage
recovery tests. Do not run the Wealth Core or backtest suites.

Compare the exact candidate's economic strategy identity and canonical retained
book/plan against the installed runtime, and verify complete runtime identity.
Build the final clean commit offline from the exact installed foundation.
Only a fully qualified candidate may use the reusable guarded local handoff.
Finish with four healthy exact-image applications, advancing leadership,
preserved native holdings/history and a freshly green dashboard. Stop at any
refused gate, preserve evidence and diagnose it without weakening the guard.

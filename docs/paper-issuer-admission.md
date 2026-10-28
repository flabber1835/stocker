# Verified issuer admission for new PAPER positions

The owner authorized implementation, qualification and local PAPER installation
on October 27, 2026. New positions must not create multiple share classes of one
verified issuer. Unresolved issuer identity blocks new purchases. Existing
holdings continue until ordinary strategy exits; there is no forced liquidation,
account reset, historical book rewrite or backtest change.

## Boundary and scope

Implement this as an execution admission policy. The canonical Wealth Core
metadata, ranking population, issuer keys, holdings and historical decisions stay
unchanged. Correcting its current issuer keys would rebind two already-held
securities to one family and raise IssuerFamilyCollision. A canonical strategy
migration is separate work and is not claimed by this release.

The account guard consumes versioned reference evidence, canonical episode
ownership, and execution's complete account reconciliation. Broker information
never feeds Wealth Core or Sentinel's exposure controller. It can leave a
positive canonical target unfilled; that execution shortfall remains visible.
Do not delete a target or declare convergence merely because its BUY is blocked.

The defensive BIL sleeve is outside the equity issuer cap, using its existing
exact bound sleeve security identity. No ticker-root exemption applies.

## Issuer evidence

OpenFIGI identifies instruments and share classes; it does not supply an issuer
key covering distinct classes. Retain current strict mapping/ambiguity handling.
Names, ticker roots and FIGI prefixes never create an issuer relationship.

Use positive SEC ticker/exchange-to-CIK associations as the supported listed
operating-issuer evidence, with explicit original rows, provenance, observation
time and content digest. The policy identifier names this source and its scope;
it does not claim universal parent-company, fund-complex or global issuer coverage.
Unsupported security types and unresolved/contradictory associations remain
unresolved. ADR evidence must identify the underlying operating issuer rather
than an arbitrary depositary program; a corroborated issuer relationship may be
retained explicitly. Do not use generic fund registrant CIKs as economic issuers.

Matching is exact on broker asset/security identity and observed ticker/exchange.
A documented lossless class-separator translation (broker dot, SEC hyphen) is
permitted only when the resulting association is unique. Keep the original
symbol. CIKs are ten-digit decimal identifiers. A conflicting candidate, ticker
reuse, unsupported mapping, missing coverage or invalid provenance blocks entry.

Retain observations before execution; no provider request belongs in the order
submission path. Cache verified associations against stable asset identity and
their evidence version; refresh only missing, expired or changed identities.
Capture current-information observation dates honestly, never apply them as
historical point-in-time evidence or rewrite past strategy results.

Direct SEC requests from this host are currently blocked. Official web-readable
SEC observations may seed a dated, source-attributed representation, preserving
the exact captured observations and their digest. Its digest is explicitly that
of the extracted representation, not an invented original HTTP response hash.
Incomplete extraction is declared and uncovered securities remain unresolved.
Provider failures cannot silently remove securities from the strategy universe
or mark unknown issuer relationships as known. Future bounded refresh failure
retains only still-valid evidence and otherwise blocks affected new entries.
The initial bundled observation expires November 26, 2026 at 05:13:13 UTC.
The bounded refresh helper is an offline acquisition tool; it is not a promise
of unattended SEC access from this blocked host. Replacing the trusted snapshot
requires retaining a genuinely new observation and its digest. Qualification
reports the expiry and unresolved coverage explicitly. No expiry extension may
be inferred from file generation, installation, a retry or a cache read.

## Enrollment and existing holdings

Enroll once under the existing execution writer lock. Bind the immutable policy
record to the exact deployment, broker, account and takeover epoch, policy digest,
authenticated canonical snapshot and complete clean account observation. Require
no UNKNOWN or working broker outcome during enrollment. Preserve all current
controls and account/book lineage.
Use the existing sealed generation-fenced broker with its structurally read-only
`PaperPreparationGrant`, naming the exact bound account and current decision
session. The existing signed `PREPARE_READ` and `SAFETY_READ` permissions cover
these observations; no pre-binding administrative certificate is required.
Reject execution-capable grants, a different account/session, bare adapters and
changed wrapper configuration before the account read. The ordinary preparation
wrapper independently forbids both submit and cancel before transport.

Freeze only genuine pre-existing positively attributed holding episodes, using
security_id plus canonical slot_id/signal_date ownership. Record exact provenance
and enrollment time. Baseline PBR and PBR.A episodes may both continue. Normal
continuing-episode controller re-exposure remains allowed; this cannot authorize
a new class, later same-security re-entry, or a canonical-but-never-executed
episode. Never regenerate the grandfather list on the next plan or after restart.
Future mandatory corporate-action deliveries are not BUY submissions and retain
the existing reconciliation contract; they do not silently create new entry
exceptions. Existing positions may always reduce through the ordinary contract.

## Admission, reservations and recovery

Check BUY eligibility under the writer lock before command creation and again
at final guarded submission. SELL handling and positive broker recovery are
unchanged. The reduction path must not depend on issuer availability.

Reserve a verified issuer for an admitted episode before transport, atomically
with its durable command admission. Retry of that exact episode is idempotent.
Another episode of the same issuer loses in the existing canonical slot/security
commitment order; do not choose a representative by new liquidity heuristics.

The execution adapter commits authenticated plan/source preparation, ended-claim
release and denied-entry shortfalls before the next guarded broker read. These are reusable pre-command
facts, not an issuer reservation or permission to send. The existing session
writer lock and publication pin stay held across that commit. Otherwise their
PAPER invalidation-row lock can block the fresh guard connection's authority
verdict update. Reservations remain atomic with durable command admission;
SEND_PENDING still commits before transport and the final issuer check remains
mandatory. No invalidation trigger or authority write is suppressed.

Count continuing enrolled episodes, approved reservations, attributed positive
positions, filled portions, working/adopted broker orders and possibly effective
PLANNED/IN_FLIGHT BUY commands across plans. UNKNOWN retains its issuer claim.
Supersession, cancellation, a temporary zero observation or ending a canonical
episode alone does not release one. Release requires ended ownership and complete
positive reconciliation showing no position or possibly effective order/command.
An expired/superseded PLANNED command may be disregarded only when positively
proven never submitted; its original journal is retained and it is never replayed.

An unresolved incumbent can overlap any candidate issuer. Block new episode
entries until incumbent evidence resolves; continuing grandfathered episodes and
SELLs remain available. Do not infer non-overlap from two different asset IDs.

Persistent denied episode identity survives later canonical fills, plan
supersession and process restart. Merely becoming a model holding cannot convert
an unexecuted episode into a grandfathered or already-admitted account position.

## Persistence and operator visibility

Use typed, authenticated, versioned execution namespaces in existing
sentinel_processed_sessions. No new behavioral schema, Compose topology, broker
credential, deployment environment knob or canonical state field is required.
Reserve the explicit `protected-buy-funding:v1:issuer-policy:v1:` child domain
inside the existing operational BUY-safety namespace. Its five typed children
are `enrollment:`, `source:`, `plan:`, `claim:` and `shortfall:`. They retain
issuer envelopes and never represent cash funding bases or grant cash authority.
The funding owner continues exact plan-key lookup and refuses any plan ID
starting with the reserved `issuer-policy:` branch before reading or writing its key. Canonical
`sentinel-<fingerprint>` plan IDs cannot alias this reserved child domain.

Keep the existing `PAPER_CURSOR_PREFIXES`, trigger definitions, catalog pins,
immutable installation marker and DDL epoch byte-identical. The parent prefix
already classifies these children as operational/PAPER evidence. A separately
added top-level prefix would change the generated cursor trigger and require an
unnecessary schema migration; it is not used. Qualify this against the exact
predecessor operational contracts and prove issuer appends advance only PAPER
read revisions. No database function replacement or coverage-receipt rebinding
belongs in this installation.
The initial unsuccessful attempt stopped at `NEW` before issuer records or
service replacement; do not copy or transform any data from abandoned top-level
issuer keys. Their unexpected presence refuses enrollment and new entry.
After enrollment, reverting to software without issuer admission requires
fencing BUY transport first; database compatibility does not confer that policy.
The owner-local PAPER mode requires enrollment before new equity BUYs. Once an
account is enrolled, that durable policy stays selected across future normal
PAPER installations too. Invalid enrollment evidence cannot disable the policy;
affected BUYs defer while reductions retain their ordinary authorization path.

Keep immutable enrollment, source snapshots, plan/episode admission evidence and
reservation/release facts. Bind plan evidence to account/epoch, policy, original
canonical ownership, plan/projection fingerprint and source/enrollment digests.
Refuse conflicting retries or reseeding. Include these namespaces explicitly in
installation preservation evidence. Do not manufacture broker commands for claims.
Cursor-prefix range scans use explicit PostgreSQL `C` collation for both bounds
and ordering. Locale-sensitive punctuation ordering must not hide a reservation,
release or abandoned legacy record from an exact namespace scan.

Persist and expose blocked-entry reasons and positive unmet quantities through
the existing execution deferral path. A no-command or clean-reconciliation path
cannot call an unresolved execution target satisfied. Existing dashboard/push
contracts continue, with no induced test notification or repeated error spam.

## Qualification and installation

Document source coverage and real evidence availability. Test same-issuer classes,
different issuers, unknown/ambiguous identity, ordering, same-plan/concurrent
reservations, UNKNOWN/partial/cancelled outcomes, reduction freedom, exact-episode
grandfathering, denied model episodes on later plans, expiry/restart/tamper and
no-fake-convergence. Include removed-guard falsifiers.

Use isolated private unit/integration fixtures and the narrow relevant suites.
The current-profile composition fixtures retain generated, dated issuer
associations for their generated instruments and load them through the real
snapshot parser and trusted digest input. After genuine private signed authority
is active, enroll the initially empty simulated account through the supported
sealed preparation-read operation before enabling automation. Its canonical
model holdings are not grandfathered account positions. Keep issuer checks,
reservations and final submission guards active through fills and callback
deaths. These generated associations are fixture inputs, not evidence of real
SEC coverage or provider availability.
The fixture's notification inception and collection boundary precede both its
synthetic market clock and the real database creation clock. Native fill times
follow the former; durable command creation follows the latter. Keep production
notification-boundary and future-fill guards unchanged.
Do not run a historical replay, alter any running backtest, copy a production
database, or perform a recovery drill. Preserve economic identity; refresh only
the exact reviewed operational runtime source seal and its existing falsifiers.

Deliver through the existing PR and the authorized backed local PAPER installer.
Readiness requires preserved account/book/history, exact-image healthy services,
current source/plan, advancing leader and an honest current dashboard. A missing
issuer mapping is a scoped new-entry block, never fabricated provider success.

# Opening execution latency and current readiness evidence

Decision: 2026-10-19. Production's October 19 cycle began at 13:31 UTC,
reached its first SEND_PENDING checkpoint after the 13:40 increase cutoff,
and recovered cleanly only after that cutoff. Preserve the failed cycle,
its proven-unsent command and the original strategy book. Never replay its
economics late or extend the ten-minute execution window to hide latency.

## Execution verification

Measure the exact deployed read-only verification path and qualify the complete
gateway with production-sized retained inputs before claiming opening readiness.
Reuse only authenticated immutable calculation work under explicitly owned,
bounded scopes. Account observations, current control/kill and leader fencing,
signed authority/revocations, publication identity, execution clock, quote and
cash checks remain fresh at their existing operation boundaries. No successful
authorization result may become a reusable broker permission.

The retained dual-sizing calculation reads its immutable
`dual-plan-sizing-authority:v1:<plan>` row and uses the supplied current plan,
binding, rollout and verified shadow commitments. Live broker/trial cursor rows
are not its inputs. Apply the existing exact broker/trial namespace exclusions
to the `dual-sizing` structural slot as well as `rolling-checkpoint`. Actual
sizing rows, economic and unknown namespaces, relation identity and transaction
epoch remain invalidating. Other slots retain their complete inventory. This
avoids repeating pure sizing when reconciliation writes broker evidence; it
does not reuse account observations or a successful execution authorization.

The full gateway additionally exposed repeated retained-adapter binding work.
With a historical publication/strategy, each fresh read's before/after guards
can call `runtime_admission._retained_checkpoint` through both readiness paths
and the explicit retained-state check. Those paths bypass the existing shadow
and sizing material slots and repeatedly decode, HMAC-check and hash the same
origin and daily checkpoints. Keep that complete canonical proof on the first
call; reuse only its compact detached binding inside the existing owned
structural scope under a new `retained-runtime-checkpoint` material slot.

Key that material with the freshly derived actual current executable context,
including selected strategy, runtime/source identity, observation and starting
cash. The stored compact binding contains only fields consumed by retained
publication/state comparisons; do not repeatedly copy historical input payloads.
Preserve the existing absent-origin behavior. Apply the same exact broker/trial
namespace exclusions as the two existing economic slots, while origin, daily,
admission, economic and unknown rows remain invalidating. Keep relation identity,
transaction epoch, original publication pin and live writer-lock requirements.
Unscoped calls execute the complete original proof. Every caller still compares
its current publication or supplied state/strategy/session with that binding;
no readiness verdict, signed broker permission, clock, control, revocation or
account observation is cached. Qualify real checkpoint/admission tamper and
context changes as falsifiers before accepting any speed improvement.

A read-only private measurement, with no broker calls, of the exact frozen
`563e2c88` runtime confirmed this repeated work. With 0.5 CPU and 768 MiB,
three `_retained_checkpoint` calls took 4.379 seconds unscoped, 3.307 seconds
under the writer/publication/structural scope, and 3.004 seconds through a fresh
connection in that same scope. Every call repeated two origin reads, two daily
reads and one current-context calculation. The daily checkpoint was absent;
origin reads alone consumed 3.511, 2.486 and 2.220 seconds respectively. All
table mutation counters matched before/after and transaction writes were zero.
This isolates a repeat-work cost; it does not attribute every second of a full
callback or qualify an optimized successor.

Further selected optimizations and measured qualification results will be
recorded here before implementation and before deployment respectively. A
passing late-order refusal test alone does not establish that valid orders
finish in time.

### Account identity within one classification pass

The production-sized gateway exposed repeated account-identification reads in
the executor's synchronous candidate classification. Each increase is classified
before settlement and again against the final observation before sending. Keep
those two passes and all per-candidate command authorization. Within one pass,
read the broker's account identity once after the first eligible candidate, then
use that returned identity for the remaining candidates classified against the
same observation and command snapshot. This is identity evidence, not a cached
authorization verdict. Read the durable binding and run canonical authorization
separately for every candidate. Skip the read when every candidate is restricted
or has no delta.

Keep the first identification inside the existing candidate error boundary.
Only retain a successful return: an ordinary failed read still refuses that
candidate and leaves the next candidate able to retry; an authority refusal
still aborts the operation. A new classification pass, including the pass after
settlement, performs its own read. Every actual broker call retains its existing
fresh before/after checks, and every mutation retains the fresh funding, quote,
control, certificate, lease and execution-clock guards. No account cash or
position observation is shared by this change.

### Compact structural input for the dual broker guard

Warm guarded reads still restored the complete verified strategy state and
hashed its feed graph to construct a sizing-cache key. Add a private compact
projection of the existing `rolling-checkpoint` material. The structural scope
retains its ordinary authenticated canonical bytes; a separate projection is
created only from those private bytes and is bound to that exact cache-record
object. Keep the same fresh publication-pin, writer-lock, database, context and
row-inventory checks before reuse. Replacing the original record invalidates its
projection. Each returned projection is detached. Never project from a mutable
state returned to an earlier caller.

The rolling guard projection contains only the checkpoint-authenticated state
commitment, session, publication/snapshot and record/attestation bindings, plus
the small state fields used to compare the plan's cursor, data version, strategy
and controller decision. Its thin state has no `state_hash` property and carries
no readiness or authorization verdict. The private guard-status reader still
derives the current executable context, validates the current publication and
snapshot with `_current`, and requires prospective attestation on every call.
The private dual-intent reader also repeats current segment transport approval
and the existing handover checks on every call.

A private sizing entry point obtains that guard projection itself; it accepts
neither a caller-supplied state digest nor a claimed proof. It uses the private
state commitment for the existing deterministic sizing key. A cache miss still
runs the original full verified shadow intent and canonical sizing derivation.
The public sizing API continues hashing any supplied mutable state. Select the
compact path only for dual EXECUTE inside the existing active structural scope;
all other paths retain the full verifiers. Existing plan-authority comparisons
consume the small state fields and the sizing verifier's authenticated digest.
Readiness, actual time/session, control, lease, signed authority, account binding,
rollout, broker observations, funding, quotes and pre-submit permission checks
remain fresh. No kernel, strategy calculation, persisted book or source-history
semantics change.

Falsifiers must cover changed economic rows/context/publication, lost pin/writer
ownership, detached-result mutation, a swapped original cache record, altered
state/plan commitments, a newly refused segment/handover, stale readiness and
caller-supplied mutable-state tampering through the unchanged public API.

### Pure source and package-metadata calculations

The actual `0129f3a2` image's read-only five-call profile confirms repeated pure
AST conversion within strategy identity, and repeated package-metadata parsing
within environment identity. Select two bounded computational optimizations.
Neither retains an environment, strategy identity, source contribution,
readiness result or authorization verdict.

`semantic_source_basis.masked_ast` may retain only its immutable digest or
nonmatching `None` result in a 32-entry cache. The key contains the exact freshly
read source bytes/string, module, baseline flag, recipe text and header, and
both presence and exact function/text of the selected hook. Keep the existing
AST normalization and Python 3.8/3.12 compatibility representation unchanged.
Unusual inputs/configurations that cannot safely form this immutable key use
the original uncached calculation and retain its exceptions. Exceptions are
never cached. Every economic source still reads its actual module bytes and
hashes those bytes on every invocation; every contribution still rereads,
authenticates and parses the pinned basis file on every invocation. A changed
basis, source, recipe/header or hook must remain immediately observable.

Within one `identity.environment()` invocation, obtain one fresh direct-pin
version snapshot and derive both the package record and pin drift from it.
The next invocation resolves and reads versions again. Public standalone pin
drift remains a fresh operation. Package discovery and full distribution
enumeration remain fresh on every call. For standard-library distribution
metadata access only, retain at most 128 immutable parsed `(Name, Version)`
tuples keyed by the complete freshly read metadata text. Read the existing
METADATA/PKG-INFO/legacy fallback afresh on every access, preserve the standard
parser's header semantics, and use the original access path for custom
distribution metadata/version overrides. Preserve exception/missing-package
behavior, duplicate-name ordering and version concatenation. Do not cache
distribution objects, paths, enumeration, file contents or installed versions.
Source-tree, environment, lock and artifact reads retain their existing fresh
boundaries. These are reviewed executable changes with authority effect NONE;
extend the exact opening successor profile to the two changed modules.

Require equivalence against the unchanged calculations, warm pure-work reuse,
same-size source/metadata edits, changed configuration and basis refusal,
fresh file reads/enumeration, and mutation falsifiers before accepting timing
measurements. The gateway still has to meet both unchanged latency limits.

## Feed readiness

Retain the existing 26-hour cached-verdict lifetime and the read-only dashboard.
An ordinary unchanged-session shadow-service poll already authenticates its
current publication and computes canonical readiness. Return that measured
report and its exact publication fingerprint from the internal verifier, then
persist a bound readiness snapshot only after the read-only verification
transaction has ended. Reuse the standard readiness binding format.

This renews measured evidence on weekends without extending an old PASS,
rescanning inputs solely for display, or writing from a panel reader. Failure,
publication mismatch or a missing required source session must not manufacture
new positive evidence. The update changes no strategy state, command, plan,
execution authority or failed-cycle history.

## Retained executable admission

Append one exact opening-latency successor profile with authority effect NONE.
Pin the changed verification, readiness and execution quote modules, executor
candidate classification, private dual guard projection/sizing consumers,
pure source/package-metadata calculation modules, admission wiring, and the
preceding idle-leader checker's explicit successor
delegation. Preserve every
historical profile byte. Accepted predecessor hashes come only from those
authenticated descriptors and individually pinned complete historical source
manifests, including the verified main revision used for this repair.

The idle-leader checker may accept its changed implementation only through the
new descriptor's independently pinned normalized checker digest and exact new
admission bytes. Admission still authenticates the complete original and current
source closures. Every required checker must exist, unknown predecessors and
neighboring source edits refuse, and missing or altered retained descriptors
cannot be repaired by supplying a new descriptor digest. These records permit
the existing book to run under the reviewed executable; they grant no execution
authority and never rewrite strategy provenance or financial history.

## Qualification and deployment

Use an isolated feature checkout, resource-limited test processes and private
qualification storage. Do not stop, restart, signal, modify, migrate, prune or
mount the running historical backtest or its storage. Production installation
uses the supported protected-main certified image and signed activation flow.
Preserve existing account binding, financial state and incident evidence.

The committed opening-latency diagnostic accepts only an explicitly selected
private rehearsal database, its expected database name and physical cluster
identifier, and the distinct production cluster identifier. It refuses ordinary
production database names, matching production identity, provider credentials,
and imports outside the exact image's `/app/sentinel` runtime. Read-only mode
forces PostgreSQL read-only transactions, takes the real nonblocking behavioral
writer lock and publication pin, and runs the public verified shadow status,
dual intent and retained sizing verifiers under one structural verification
scope. It retains stage durations, cProfile invocation counts and cumulative
costs, source/image identities, snapshot size and the unchanged database write
counters. It issues no broker request, grant, certificate or durable mutation.
Partial or refused stages produce failure evidence, never a latency PASS.

The separate simulated gateway qualification must use a fresh private execution
namespace and the same production-sized retained source, actual production
callbacks, resolver and public paper gateways. Only signed-authority test
fixtures and the in-memory broker/provider are substituted and named in its
report. No native credentials or native network transport are admitted. Measure
real elapsed time with the deployed one-CPU/two-GiB runtime and scheduler profile.
Record preflight recovery and pre-open preparation separately: those normally
finish before the overnight market-open wait. Starting at entry to the cold
execution callback, require the first simulated order within 120 seconds and
the full intended basket within 300 seconds, both inside the unchanged
540-second fresh-execution budget. Include every execution-time guard and
reconciliation stage; no verification scope may survive a previous callback.
Missing legs or a terminal cycle with no orders fail qualification. This proves
the exercised software path and margin under the measured resource load; it
cannot certify future opening-auction liquidity or provider latency.

The one synthetic window belongs only to execution boundaries:
`automation.schedule`, `paper.execution`, `paper.validation`,
`execution.alpaca`, `execution.guarded` and `execution.opening_prices`.
Bind their calendar aliases to one proxy. The feed package's import boundary
also supplies that proxy for the adapter and guard's local imports; its
`session_window` returns the fixture only for those exact immediate caller
modules and the named session, delegating every other request to the original
calendar. Do not replace the original calendar module or its functions.
Shadow activation/decision timing, feed history and `paper.targets` pre-open
share-unit witness cutoffs keep their original calendar. Qualify that retained
shadow authority still authenticates under this proxy before a full gateway
attempt. Historical Friday windows and other session windows must be identical.

Candidate source changes use `runtime_admission.current_context` and the normal
compatible retained-runtime admission with the authenticated predecessor source
manifest. The diagnostic never substitutes a retained runtime identity. Its
separate `admit` mode requires an additional explicit private-mutation flag and
an `opening_latency_` database name; normal disabled/killed control, historical
closure and private backup guards still apply. It checks that origin and daily
book records remain identical. Subsequent read-only profiles derive the reviewed
process settings from that actual image and require its existing admission.

The gateway simulator keeps the sealed production Alpaca adapter, canonical
fresh broker guard, private database control/lease and all shadow/sizing/readiness
checks. The earlier attended native driver replaced that guard and therefore
did not measure its repeated verification cost. The new diagnostic substitutes
only an explicitly unsigned authority fixture, a local HTTP provider and one
named session-window fixture. PostgreSQL and broker observations retain real
timestamps, and first/complete-order timings use monotonic elapsed time without
cProfile. A fresh private command/cycle namespace and real backup/incarnation
proofs are prerequisites; the diagnostic cannot initialize or bypass them.

Each callback uses the canonical `AutomationService._invoke` process supervisor,
including its real `<PHASE>_CALLBACK` registration, configured callback deadline,
independent parent heartbeat, cancellation and child cleanup. The callback runs
in a forked child so CPU-bound parsing cannot starve the parent's heartbeat.
The fixture wrapper returns only its callback result, local provider state and
invocation counts through that existing JSON IPC; restore those fixture values
in the parent before the next callback. Heartbeat connections and statements
are bounded below the lease duration. After the supervisor joins its heartbeat,
register idle state. The scheduled-open wait runs without a database transaction
and renews its idle lease from the foreground loop with ordinary, non-callback
renewal. Neither lease nor callback limits are widened.

Diagnostics must survive refused callbacks. Emit bounded, flushed child metrics
for completed pure-method calls and a callback `finally` record containing
phase, elapsed/process CPU, invocation totals, local order/request counts and
the monotonic first-order metric. Include retained-checkpoint binding/decoding,
snapshot verification/readiness, closure loading and sizing derivation; wrappers
delegate unchanged arguments, results and exceptions. Keep fixed aggregate
names and sample repeated call logs with an explicit cap. A supervisor kill can
prevent `finally` from running, so completed-call records must already be on
stdout. Do not serialize verification objects, source state, credentials or
permission results into diagnostic metrics. These observers grant no authority
and cannot promote a refused or incomplete callback into qualification.

The diagnostic parent ends its read transaction after each cycle transition and
before entering a supervised callback, including terminal recovery. A long
callback must not leave an idle parent transaction that reaches the diagnostic's
existing 120-second idle limit. Keep that limit unchanged. Final diagnostic
disable/kill runs through a fresh connection with the same private-target and
physical-identity guards, so a timed-out parent connection cannot leave the
simulator enabled or erase the original failure. This changes only rehearsal
orchestration; production supervision and database settings are unchanged.

## October 19 incident evidence and local qualification

The deployed revision was `1e1db91b878d3073549a1e46337893882c3935b2`,
runtime digest
`sha256:c40baeb81bbd9f2d8897fa758f5a47aa58beb7d7ce91ba0c9246beab79c58307`.
The cycle entered EXECUTING at 13:31 UTC. Its first durable command entered
SEND_PENDING at 13:40:17, after the 13:40 increase cutoff. The final quote and
affordability check refused before transport; reconciliation subsequently
proved the account clean and terminalized the cycle as SUPERSEDED for maximum
execution lateness. The command remains PLANNED, with zero fills and no broker
order ID. Native GET-only observations found no orders or positions. Journal
event timestamps use transaction-start time; they do not independently locate
the expensive work within the transaction.

Separately, the feed was current by source session, but its last cached readiness
report had exceeded the unchanged 26-hour lifetime. The same-session producer
had measured readiness without persisting that new measurement. This caused a
feed dashboard failure independently of the missed execution cycle.

The earlier attended qualification exercised real broker transport but replaced
the canonical fresh broker guard in its driver and had no opening latency SLA.
Its success therefore did not establish that the production guarded opening
path could finish in time. The new diagnostic explicitly retains that guard.

The private rehearsal copy contains 2,198,840 immutable snapshot bars. Its
physical cluster identity differs from production. The source copy preserves
the existing command and cycles; a separate private database archives copied
execution evidence before creating its empty simulator command/cycle namespace.
The actual supported retained admission accepts the original book source
manifest from `90a960547b58bb245c998ae3f70d0baed1fe95d0` without replacing
the book or substituting a runtime identity.

An unprofiled read-only baseline using the exact deployed image measured
76.141 seconds for its first verified shadow status and 2.914 seconds for its
first retained sizing derivation. A warmed fresh guard measured 0.731 seconds
for status, 0.380 seconds for intent, and 0.357 seconds for the sizing cache hit.
This benchmark issued no broker requests or database writes. It establishes
verifier costs, not complete gateway qualification.

The frozen `563e2c88` full gateway attempt 9 subsequently failed qualification:
preflight recovery took 54.642 seconds, preparation 103.773 seconds and the
scheduled wait 201.522 seconds, but EXECUTE exceeded the canonical 900-second
callback deadline. The supervisor returned `CallbackDeadlineExceeded`; final
private database inspection found zero commands and fills and disabled/killed
control. No first simulated POST metric returned through IPC. Preserve this
failure; neither its preparation success nor its partial execution is a gateway
PASS. It motivated measurement and the additional retained-binding reuse above.

Local regression results and complete gateway timings are recorded below once
all required runs complete. The unsigned simulator is not production execution
authority or proof of future native fills.

For the flat simulator account, derive needed instruments from the canonical
plan-delta reader plus opening intents. Populate only those fixtures, always
using retained marks and tickers. For ALPACA_OPENFIGI, stock broker IDs must
match authenticated source IDs. The defensive `SENTINEL:BIL` identity is
deliberately outside that stock mapping; its broker metadata may instead come
from an explicit GET-only native asset metadata artifact. For SHARADAR, which
does not publish broker asset IDs, every needed ID requires that explicit
metadata. Metadata must resolve through the unchanged source resolver and may
never override an authenticated stock ID. Record the source provider and each
identity origin in the report. A zero, nonheld defensive leg does not require
an asset lookup; any missing needed identity, ticker or retained mark refuses.

The following targeted regressions passed with no production or backtest writes.
All test containers had networking disabled and bounded CPU, memory and PID
limits. No Wealth Core suite or full repository suite was invoked locally.

```bash
# 109 passed in 2060.92 seconds; one CPU, 1536 MiB.
python -m pytest \
  tests/sentinel/test_open_time_verification.py \
  tests/sentinel/test_rolling_runtime.py \
  tests/sentinel/test_rolling_admission_readers.py \
  tests/sentinel/test_shadow_health_projection.py \
  tests/sentinel/test_rolling_retention_runtime.py \
  tests/sentinel/test_opening_latency_qualification.py \
  -q --tb=short -p no:cacheprovider

# 203 passed in 253.09 seconds; 0.5 CPU, 768 MiB.
python -m pytest \
  tests/sentinel/test_opening_latency_upgrade.py \
  tests/sentinel/test_idle_leader_upgrade.py \
  tests/sentinel/test_retained_source_compatibility.py \
  tests/sentinel/test_clock_sampling_upgrade.py \
  tests/sentinel/test_native_read_upgrade.py \
  -q --tb=short -p no:cacheprovider \
  --junitxml=/evidence/profile-upgrade-563e2c88-run2.xml

# 84 passed in 541.45 seconds; 0.5 CPU, 768 MiB.
python -m pytest \
  tests/sentinel/test_regular_quote_submission.py \
  tests/sentinel/test_quote_starvation.py \
  tests/sentinel/test_opening_submit_freshness_boundary.py \
  tests/sentinel/test_guarded_execution_broker.py \
  tests/sentinel/test_autonomy_execution_remediation.py \
  tests/sentinel/test_rolling_paper_inputs.py::test_structural_reuse_rechecks_row_versions_and_inputs \
  tests/sentinel/test_rolling_paper_inputs.py::test_structural_reuse_requires_live_writer_and_unchanged_verification \
  tests/sentinel/test_rolling_paper_inputs.py::test_structural_reuse_is_absent_outside_guard \
  tests/sentinel/test_rolling_paper_inputs.py::test_fresh_dual_guard_reuses_only_its_verified_state_digest \
  tests/sentinel/test_rolling_paper_inputs.py::test_structural_reuse_preserves_real_shadow_and_sizing_refusals \
  tests/sentinel/test_rolling_paper_inputs.py::test_fresh_broker_guard_rechecks_snapshot_receipt_after_read \
  -v --tb=short -p no:cacheprovider --durations=10 \
  --junitxml=/evidence/financial-guards-563e2c88.xml
```

The first batch's shell launcher timed out at 1800 seconds while its existing
container continued normally. Reattaching to that same container captured the
109-pass summary; an independent Docker wait returned exit code zero. The run
was neither restarted nor counted as passing based on partial output. The three
functional modules in that image match the committed candidate bytes. The
203-test batch separately uses the `563e2c88` retained-admission implementation.

## Native quote availability is a separate release gate

GET-only checks at 15:10:54–15:10:56 UTC used the deployed adapter's exact
sorted-symbol query and `feed=iex`. All 15 intended assets were active/tradable;
all 14 source-bound stock IDs and the separately captured BIL ID matched native
metadata. Sixteen requests completed in 2.053 seconds with no provider errors.
All 15 quotes were present. Stock quote ages were 0.071–57.255 seconds, while
BIL's latest quote was 451.019 seconds old and therefore failed the existing
60-second submission freshness rule.

A bounded, complete IEX BIL quote-history request for 13:30–13:40 UTC returned
18 quotes, all between 13:30:00.003404 and 13:30:15.900437. There were no further
updates in that window. The last quote could satisfy the 60-second rule only
through 13:31:15.900437, about 16 seconds after the configured execution start.
Historical availability does not prove real-time delivery, but this response
does demonstrate an independent obstacle to completing the intended native BIL
leg with that feed. A latest SIP quote request using the same credentials was
refused with HTTP 403.

Preserve the 60-second rule and the ten-minute increase cutoff. A full-basket
simulator PASS proves the software path under its explicitly fresh local quote
fixture; it cannot establish native full-basket readiness when the available
feed does not deliver usable quotes. The release must state this distinction
and retain execution fencing until native data access is verified.

## Unpublished SIP candidate — superseded by the no-subscription constraint

The operator subsequently clarified that no SIP subscription is purchased and
requested investigation of a [free-data execution redesign](free-data-execution-proposal.md).
The SIP-only candidate described below remains historical diagnostic work and
is not selected for deployment. The installed IEX policy is unchanged. Native
checks at 17:32:24 UTC again found valid ACTIVE/unblocked paper authentication
and the explicit SIP subscription refusal. Do not purchase SIP, activate the
unpublished candidate. The subsequently selected free-data contract and approved
DAY lifetime are documented in the linked design; price-band selection and
ordinary release qualification remain outstanding.

The earlier candidate assumed existing SIP access and made SIP the single source
for the execution adapter's latest-quote GET, with an explicit `feed=sip` query
and a new `ALPACA_SIP_RAW_REGULAR_QUOTES_V1` evidence source. The reviewed
runtime/source identity binds this policy; there is no environment feed selector
or automatic fallback. The historical Sharadar/Alpaca input corpus, opening-bar
source, and immutable strategy book are unchanged. Preserve explicit decoding
and typed validation of the old IEX quote source for retained evidence, while
new quote parsing emits only the SIP source.

Keep raw bid/ask prices, instrument identities, positive quote sizes, session
boundaries, the 60-second freshness limit, fresh affordability checks and the
ten-minute increase cutoff. A denied SIP request must refuse; it must never
become permission to use delayed or stale data. Paper account, asset, order and
stream credentials remain bound to the existing paper account. If separate
SIP credentials are needed, document and qualify their data-only routing before
adding that wiring; they must never replace the paper broker credentials.

GET-only checks of the exact known production, Windows and two Linux release
profiles found one unique Alpaca keypair. That pair still returned SIP HTTP 403
at 15:27:24 UTC. No credential values or fingerprints were recorded. The operator
subsequently confirmed that the existing `.env` credentials are the intended
credentials and authorized their use. Native real-time SIP access still needs a
successful API check before activation; software simulation proceeds independently.
Earlier successful paper/IEX reads or historical SIP requests do not establish
latest-quote entitlement. Alpaca's [market-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)
explicitly distinguishes historical SIP queries older than 15 minutes from
subscription-gated latest endpoints.

A fresh check at 16:09:53 UTC confirmed that the current project `.env` keypair
matches production. The paper account was ACTIVE, unblocked and matched its
durable binding; BIL IEX returned usable same-session quote sides and sizes at
17.57 seconds of age. The same pair's real-time SIP request returned HTTP 403
with Alpaca's subscription refusal. Credentials were loaded only in memory;
no secret values or fingerprints were recorded. This distinguishes valid
authentication from the still-unavailable feed entitlement.

SIP regressions passed: 48 tests in 35.79 seconds, with networking disabled,
0.5 CPU and 768 MiB. The cohort used the existing test image with exact read-only
source/test overlays:

```bash
python -m pytest \
  tests/sentinel/test_unattended_operating_contract.py \
  tests/v5/test_opening.py::test_alpaca_reads_raw_sip_regular_quotes \
  tests/sentinel/test_paper_service_rehearsal.py::test_rehearsal_quotes_use_actual_endpoint_and_canonical_parser \
  tests/sentinel/test_regular_quote_submission.py \
  tests/sentinel/test_opening_submit_freshness_boundary.py \
  tests/sentinel/test_quote_starvation.py \
  -q --tb=short -p no:cacheprovider --durations=10 \
  --junitxml=/evidence/sip-quotes-20261019.xml
```

Three baseline falsifier cases passed. Removing the typed quote-source guard
caused both SIP and legacy IEX forgery cases to fail; forcing IEX caused the
request policy case to fail. Mutants existed only in private compiled function
copies. The sealed profile's narrow current-byte check separately passed; full
expanded retained admission and the final-runtime gateway remain required.

## Additional retained-binding regression

The compact retained-binding successor passed 59 tests in 74.02 seconds with
networking disabled, 0.5 CPU, 768 MiB and exact read-only source/test overlays:

```bash
python -m pytest \
  tests/sentinel/test_retained_binding_reuse.py \
  tests/sentinel/test_retained_admission_chain.py \
  tests/sentinel/test_open_time_verification.py::test_only_economic_proofs_ignore_exact_broker_records \
  tests/sentinel/test_open_time_verification.py::test_economic_inventory_falsifier_detects_broker_invalidation \
  -q --tb=short -p no:cacheprovider --durations=10 \
  --junitxml=/evidence/retained-binding-20261019-final.xml
```

Two baseline cases separately passed. Removing the new slot's exact broker
namespace exclusion caused the historical/PAPER-write test to fail with 30
origin reads instead of two. Replacing the fresh runtime-context key with a
constant caused the existing context-change refusal test to fail. Mutants
existed only as private compiled function copies. Preserve the earlier failed
fixture run: it entered the real mutation backup guard without configuring an
archive. The corrected read-only verifier fixture takes the actual SQL advisory
writer lock directly; the production mutation backup guard is unchanged.

The preceding exact source/profile (`a7122319...`) covered all 205 cases in the
five-module admission selection. The first run had 204 passes, no assertion
failures and one setup error because its read-only container did not expose the
fixture's `/tmp/stocker_pg_clusters` directory. The exact affected parameter
then passed in 202.25 seconds with only that private directory made writable;
no source or descriptor changed between runs. Both runs used 0.5 CPU, 768 MiB
and no network. Preserve the first run's error alongside the targeted retry.

```bash
python -B -m pytest \
  tests/sentinel/test_opening_latency_upgrade.py \
  tests/sentinel/test_idle_leader_upgrade.py \
  tests/sentinel/test_retained_source_compatibility.py \
  tests/sentinel/test_clock_sampling_upgrade.py \
  tests/sentinel/test_native_read_upgrade.py \
  -q --tb=short -p no:cacheprovider \
  --basetemp=/tmp/opening-latency-profile/pytest \
  --junitxml=/evidence/profile-retained-binding-admission.xml

python -B -m pytest \
  'tests/sentinel/test_clock_sampling_upgrade.py::test_actual_formed_book_survives_clock_repair_without_reformation_or_reacquisition[clock_sampling_preceding-ready0]' \
  -q --tb=short -p no:cacheprovider \
  --basetemp=/tmp/opening-latency-profile/pytest \
  --junitxml=/evidence/profile-retained-binding-admission-pg-retry.xml
```

## Candidate classification regression

The account-identity classification change passed 113 tests in 137.72 seconds
with networking disabled, 0.5 CPU, 768 MiB and exact read-only executor/test
overlays on the existing test image:

```bash
python -m pytest \
  tests/sentinel/test_candidate_account_identity.py \
  tests/sentinel/test_two_phase.py \
  tests/sentinel/test_projection_and_executor.py \
  tests/sentinel/test_issue_180_executor_universe.py \
  tests/sentinel/test_quote_starvation.py \
  tests/sentinel/test_regular_quote_submission.py \
  -q --tb=short -p no:cacheprovider --durations=10 \
  --junitxml=/evidence/candidate-identity-20261019.xml
```

Four private baseline cases passed. Removing identity reuse caused the
15-leg regression to make 30 identification reads instead of two. Reusing the
durable binding caused its change-detection regression to fail. Swallowing
`BrokerAuthorityRefused` caused both classification-pass refusal tests to fail.
These final falsifiers use live fixture globals; preserve the earlier failed
copied-globals experiment without counting it as guard evidence. No mutant was
written to tracked source.

## Preserved `efcc47a6` gateway failure

The exact committed `efcc47a6` runtime, local image
`sha256:aac5515d2ddf48014c3abe483f20aed63088501fc7ce2231f694b1bfae46a0d1`,
sent the first simulated POST at 300.725868 seconds. Its EXECUTE callback
returned normally in 534.612393 seconds with all 15 simulated POSTs. Its child
body consumed 371.455184 seconds of process CPU. Both the 120-second first-order
and 300-second complete-basket gates had already failed.

The structural slots each loaded only once: retained binding had 720 calls,
rolling checkpoint 240, and sizing 240. Warm work remained substantial:
verified shadow status totaled 145.898315 seconds, current executable context
87.082894 seconds across 720 calls, and executable identity 85.345803 seconds
across 1201 calls. These nested totals overlap and must not be added. HTTP
fixture counts included 74 account reads and 45 asset reads. The cold snapshot
scan took 34.646036 seconds and mapped bars 25.946903 seconds. This measured
failure motivated compact guard input and per-pass account identity work; it
does not qualify either later change.

Terminal recovery returned after another 182.0454 seconds, then the diagnostic
parent's expired idle transaction refused the final query and its original
cleanup. Preserve that OperationalError and the timing failure. Fresh,
identity-guarded private cleanup and the revised diagnostic orchestration are
required; no production or historical backtest operation is part of that repair.

Fresh, physically checked cleanup subsequently confirmed disabled/killed control
in that private namespace. Its 15 commands were FILLED and had broker order IDs,
but the original run never reached its exact-basket comparison and remains a
failed qualification. Five immutable origin/shadow/formation cursor payloads
matched the copied base exactly; daily checkpoints were absent in both. An
earlier all-non-PAPER inventory comparison also included the newly created
runtime admission and database incarnation. Preserve that conservative mismatch
and the narrower immutable-book clarification rather than claiming the original
aggregate matched.

The revised diagnostic's 55 targeted tests passed in 17.69 seconds with network
disabled, 0.5 CPU and 512 MiB:

```bash
python -m pytest tests/sentinel/test_opening_latency_qualification.py \
  -q --tb=short -p no:cacheprovider \
  --junitxml=/evidence/qualification-tools-55.xml
```

Private compiled-function falsifiers separately caused the transaction-boundary
and fresh-cleanup tests to fail when their respective guards were removed.

## Final frozen source and retained-admission coverage

The compact-guard candidate is commit
`0129f3a2d6eacb520878333800c9d3c3ce53014b`, local diagnostic image
`sha256:0222b37916d8c857f9180f500523e668e240d7b91fdcca927cbb345496b8e211`,
with exact retained profile
`0e6dd7349dcf3000f59ca6034995f1b6f320a4f84484427bdc3f6c5b9f8cebcb`.
The image copies only committed Sentinel bytes over the unchanged deployed
package image. Supported private admission of the original book passed in
31.110935 seconds. This local image grants no production execution authority.

The final five-module profile cohort passed all 213 collected cases in
564.08 seconds with zero failures, errors or skips. The existing formed-book
restore case passed. All 372 recorded runtime/profile/test file hashes were
unchanged before/after. The run used network disabled, 0.5 CPU, 768 MiB, current
read-only source mounts and writable private PostgreSQL/TMPDIR mounts that
preserved the image's `/tmp/req` lock witness:

```bash
python -m pytest \
  tests/sentinel/test_opening_latency_upgrade.py \
  tests/sentinel/test_idle_leader_upgrade.py \
  tests/sentinel/test_retained_source_compatibility.py \
  tests/sentinel/test_clock_sampling_upgrade.py \
  tests/sentinel/test_native_read_upgrade.py \
  -q --tb=short -p no:cacheprovider --durations=10 \
  --junitxml=/evidence/profile-final.xml
```

The compact projection selection covered all 53 cases with passing results.
Its original expanded run finished with 50 passes, three test-helper failures,
zero errors and zero skips in 928.06 seconds. The Windows client wrapper timed
out at 900 seconds; an already attached daemon-log follower retained actual
completion and JUnit from the same unchanged container. The three failures were
copied-globals mutant helpers calling the real sizing loader with a synthetic
plan. A test-only correction then passed all three exact falsifiers plus their
three cold commitment baselines in 48.00 seconds. Runtime bytes never changed.
Preserve both runs; do not describe this as one clean 53-test run.

The real guarded-read fixture, complete open-time module and both retained
origin/sizing tamper parameters passed in the original expanded run. The tests
use networking disabled, 0.5 CPU and 768 MiB:

```bash
python -B -m pytest \
  tests/sentinel/test_compact_guard_projection.py \
  tests/sentinel/test_dual_reconciliation.py \
  tests/sentinel/test_open_time_verification.py \
  tests/sentinel/test_rolling_paper_inputs.py::test_structural_reuse_preserves_real_shadow_and_sizing_refusals \
  -q --tb=short -p no:cacheprovider --basetemp=/tmp/compact-projection/pytest \
  --junitxml=/evidence/compact-projection-expanded.xml

python -B -m pytest \
  tests/sentinel/test_compact_guard_projection.py::test_private_cold_sizing_refuses_changed_commitments \
  tests/sentinel/test_compact_guard_projection.py::test_commitment_guard_falsifier_detects_removed_comparison \
  -q --tb=short -p no:cacheprovider --basetemp=/tmp/compact-projection/pytest \
  --junitxml=/evidence/compact-projection-falsifier-retry.xml
```

The admitted actual-image private microbenchmark passed in 151.639746 seconds
at 0.5 CPU and 768 MiB. Its cold full canonical status took 137.367897 seconds;
the compact projection took 1.213651 seconds. Three subsequent compact calls
through fresh connections took 1.066247, 0.698306 and 0.594114 seconds. Each warm
call performed zero canonical loads, projection rebuilds, complete state hashes
or full rolling graph restores. Current readiness ran once and runtime identity
twice per call; all compact commitments matched the canonical full baseline.
Forced read-only transactions recorded zero writes, before/after table mutation
counters matched, and no provider/broker calls occurred. All scopes and
connections ended before starting the separate cold gateway qualification. This
diagnostic proves pure-work reuse, not native execution readiness or basket SLA.

The unchanged actual-image gateway for this candidate completed its normal
exact-basket and terminal checks, then explicitly refused qualification: the
first simulated order took 169.722668 seconds against the 120-second limit;
the exact basket plus terminal reconciliation took 496.473063 seconds against
the 300-second limit. EXECUTE took 380.315856 seconds and terminal RECOVER took
116.086933 seconds. All 15 commands were FILLED and had order IDs. All five
immutable shadow/origin/formation witness rows matched the retained base;
daily checkpoints remained absent. Fresh private cleanup verified disabled
control and an engaged kill switch. Preserve this failed qualification even
though its financial and cleanup assertions passed.

The trace recorded 183 fresh broker-grant validations, 921 rehearsal-identity
calculations and 1,472 runtime-strategy identity calculations during EXECUTE.
These nested timings overlap. Profile the actual identity/source calculations
before selecting another change; do not replace a live permission check with a
cached verdict or infer a passing latency result from a microbenchmark.

The pure AST calculation change passed 48 focused cases in 2.89 seconds,
including nine existing source/configuration/basis compatibility cases and
private omitted-key/no-reuse falsifiers. The identity calculation change passed
76 cases in 40.65 seconds with no failures, errors or skips in the canonical
container layout. Independent review then found that malformed surrogate
headers can yield mutable parser objects. Both concrete old-source witnesses
failed as expected. Such results now bypass the cache and use original
descriptor access, without coercion. The final source passed all 79 cases in
39.34 seconds, including a private immutability-guard falsifier. Preserve the
intermediate 78-pass/one-failure run too: its sole failure was the private test
compiler trying to read `__globals__` from an LRU wrapper, corrected test-only
with `inspect.unwrap`. The earlier run is preserved separately: 69 passes and five
failures exposed an incorrect empty-metadata test assumption, a concurrent
source edit caught by the stability check, and three artifact-import checks
using the wrong test mount layout. The test-only assumption and layout were
corrected; runtime bytes were frozen throughout the clean rerun. Six expected
stdlib deprecation warnings came from explicit missing-header reference cases.
The passing runs used networking disabled, 0.5 CPU, 768 MiB and read-only source
mounts, with no PostgreSQL or broker access:

```bash
python -B -m pytest tests/sentinel/test_semantic_source_calculation.py \
  tests/sentinel/test_retained_source_compatibility.py::test_forward_policy_changes_economic_identity_and_never_masks_neighbor_mutation \
  tests/sentinel/test_retained_source_compatibility.py::test_altered_admission_hook_is_not_ignored \
  tests/sentinel/test_retained_source_compatibility.py::test_source_identity_recipe_header_cannot_hide_executable_changes \
  tests/sentinel/test_retained_source_compatibility.py::test_baseline_file_is_pinned \
  -q --tb=short -p no:cacheprovider --durations=10 \
  --junitxml=/evidence/result.xml

python -B -m pytest tests/sentinel/test_identity_metadata_calculation.py \
  tests/sentinel/test_dependency_pins.py tests/sentinel/test_runtime_is_the_artifact.py \
  -q --tb=short -p no:cacheprovider --durations=10 \
  --basetemp=/tmp/identity-metadata/pytest \
  --junitxml=/evidence/identity-metadata-final-clean.xml
```

These pure-work tests do not qualify gateway latency, native SIP access or
deployment authority.

The exact source-calculation candidate is
`ce3083025b07c3447ac6319cefabadfa8f20d667`, local diagnostic image
`sha256:5777af7a01883a1eb4069a56c4208c55b38a61a6372450dace53108bc41c297c`,
with profile `7c182e320f3d3be01af273fbb51e1bb9ce61edff2ce55b50fb4ac0c157846b38`.
The narrow successor cohort independently collected and passed all 63 cases in
386.10 seconds with no failures, errors or skips; all 370 recorded file hashes
were unchanged. It included the actual formed-book admission/restore case
(175.55 seconds plus 27.22 seconds setup) and all 21 historical witnesses. The
run used the same network-disabled, 0.5 CPU, 768 MiB test envelope:

```bash
python -B -m pytest tests/sentinel/test_opening_latency_upgrade.py \
  tests/sentinel/test_retained_source_compatibility.py \
  tests/sentinel/test_clock_sampling_upgrade.py::test_actual_formed_book_survives_clock_repair_without_reformation_or_reacquisition \
  -q --tb=short -p no:cacheprovider --durations=10 \
  --junitxml=/evidence/successor-profile.xml
```

Supported admission in fresh private namespace 12 passed in 33.763734 seconds.
Its separate validator-only diagnostic then refused with `StaleLeaderRefused`
after 36.802703 seconds under the actual callback supervisor (47.464138 seconds
total), before either clone comparison or warm validator measurement. Preserve
this failure: the original type-only diagnostic report did not retain enough
detail to prove which heartbeat condition failed. Supported cycle/plan setup
had consumed 10.661435 seconds before the supervisor started, creating a
possible race with the unchanged 12-second lease. A subsequent diagnostic must
record stage/heartbeat timing and perform a normal unexpired-lease renewal
before starting the supervisor; expired leadership must still refuse. Fresh
cleanup passed. Control was disabled/killed, the diagnostic cycle remained
recorded, and commands, fills and observations remained zero. This diagnostic
does not establish gateway readiness.

Fresh private namespace 13 admitted the same exact candidate in 19.940486
seconds. Its validator-only diagnostic completed in 144.154929 seconds under
the unchanged actual supervisor (133.977259-second callback); all 41 observed
heartbeats passed, with an ordinary successful pre-invoke renewal. Recorded
lease-owned setup took less than 0.05 seconds, weakening the earlier setup-race
hypothesis. Namespace 12's unrecorded failure condition remains unknown.

At 0.5 CPU and 2 GiB, cold full status took 116.489073 seconds; the unprofiled
warm complete database-only broker-grant validator took 1.203027 seconds wall
and 0.352145 seconds CPU. Wall-clock and CPU-clock profiles took 1.385094 and
5.215119 seconds respectively; the latter has substantial profiler overhead.
The warm trace contains 92 uncategorized SQL calls consuming 0.737375 seconds,
repeated manifest/source reads and pure SQL normalization. No warm full-state
restore bottleneck remained. The existing canonical adapter saved only
0.509677 seconds wall versus full serialization in one separately timed clone
comparison; equal state commitments were checked outside clone timing. No
gateway clone change was selected on that evidence.

Journal/book inventories matched, validation writes and provider calls were
zero, and fresh cleanup verified disabled/killed control, IDLE registration and
zero commands/fills/observations. All diagnostic processes and scopes ended.
The report is explicitly DIAGNOSTIC_ONLY, not native order or gateway timing
qualification. The subsequent free-data order-policy investigation does not
inherit a passing release claim from these measurements.

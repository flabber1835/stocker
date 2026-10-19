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

Further selected optimizations and measured qualification results will be
recorded here before implementation and before deployment respectively. A
passing late-order refusal test alone does not establish that valid orders
finish in time.

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
Pin the changed verification, readiness and execution quote modules, admission wiring, and the
preceding idle-leader checker's explicit successor delegation. Preserve every
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
203-test batch separately uses the final retained-admission implementation.

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

## Selected SIP execution quote policy

The operator selected existing SIP access. Make SIP the single canonical source
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
at 15:27:24 UTC. No credential values or fingerprints were recorded. A location
for the existing SIP-enabled profile is therefore still required before native
SIP qualification and activation. Software simulation can proceed independently
and must state this remaining gate.

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

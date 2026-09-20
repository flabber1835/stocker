# Single-request status memory review

Reviewed implementation: `d5c35410f6be7e93a0fdc66183e56de0009be351`.
Verified main: `e255a78aaf4f89d25fc634864aafd2656c6cd176` (owner merged #415).
Includes #417 `c661821cc383836c74746d27faa9fcc14a609b2f` unchanged. Main integration
only added its retained integration evidence and reconciled append-only ledger
text. Delivery is a new PR against main; no existing PR history was rewritten.

## Defect and boundary

The prior [full-status evidence](../full_status/README.md) measured about 1.92 GiB
per public shadow-status reader against the 512 MiB panel limit. This is a P2
availability/resource defect; it is not evidence of an incorrect strategy return.

The implementation removes repeated observer construction and JSON round trips,
releases the verified seed before loading the checkpoint session, streams all
feed-series entries in batches of 32, and incrementally validates/hashes canonical
JSON. Complete genesis/state/record commitments, source identities, economic
validation, row/session identity, publication pins and checkpoint bindings remain.
No verifier result persists between requests. Optimized resume is bound to one
repeatable-read, read-only PostgreSQL transaction; the observer is consumed and
cannot be reused by advancement. Mutation/recovery retains a reusable observer.

The scalar pool shares only immutable standard JSON values, with two bounded
4096-entry caches and 64-character token limits. A lifecycle falsifier caught
psycopg retaining dynamically registered classes globally. Fixed loader classes
now own no request pools: instances own and release them. Both text and binary
JSONB reads are tested, including unchanged connection adapters.

Design decisions were recorded in [the design document](../../../docs/status-memory-bound.md)
before implementation. No provider capability, accepted economic value, golden
fixture, memory limit or refusal threshold was changed. The retained original
SessionState serializer comes verbatim from main `99410e5a`; it independently
checks complete serialized dictionaries, hashes and detached ownership on first
and held-position states. Source identity naturally changes with production
source; existing certificates need the documented reviewed continuation procedure.
Different fixture hashes across source revisions are not repinned economic goldens.

Reviewed implementation locations at the commit above:

| Boundary | Source |
|---|---|
| Incremental canonical serialization and detached feed | `sentinel/core/session.py:58`, `:319` |
| Decoder lifecycle and complete streamed rows | `sentinel/shadow_observation.py:892`, `:963` |
| Single-snapshot verification and early seed release | `sentinel/shadow_observation.py:1300`, `:1728` |
| One verified origin/daily restore | `sentinel/rolling_checkpoint.py:98`, `sentinel/rolling_daily_checkpoint.py:102` |
| Status caller routing | `sentinel/rolling_runtime.py:25` and `classify` |

## Reproduction

Host: Windows Docker Desktop; immutable `sentinel-test:ci` image
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
Python 3.12 and isolated PostgreSQL 17.11. No network to NAS or brokers.
The fixture uses 5000 securities, 300 sessions and 1.5 million synthetic SEP rows.
It has minimal synthetic actions/references and explicitly synthetic clocks,
publication receipts and runtime identity. It establishes allocation/refusal
behavior, not provider completeness, historical returns or deployment authority.

From this source checkout (substitute an absolute writable scratch path):

```sh
python audit/economic_399/status_memory/run_fixture.py --evidence <scratch>
# In another terminal, after fixture_ready appears:
python audit/economic_399/status_memory/run_reader.py --evidence <scratch> --repeats 2
python audit/economic_399/status_memory/run_reader.py --evidence <scratch> --surface http
python audit/economic_399/status_memory/run_reader.py --evidence <scratch> --mutant-retain-seed
# Create <scratch>/advance, wait for advanced_fixture_ready, repeat readers.
# Create <scratch>/stop after measurements to cleanly stop/remove the fixture.
```

Each reader is a fresh container with 512 MiB memory, 512 MiB memory+swap (no swap),
two CPUs and only the offline fixture's network namespace. The fixture builder's
8 GiB limit is separate; its peak must never be reported as a reader peak or as
proof that production initialization fits its 2 GiB budget. Readers retain process
VmHWM, cgroup peak/events, exit status and Docker OOM state. The HTTP run executes
the actual `/panel.json` route and requires its shadow-verification row to be OK;
missing synthetic operational evidence may legitimately make overall status fail.
The resource mutant forces the reusable observer path and must fail the same cap.

Diagnostic-bound-context runs in the archive are **not acceptance**: they profile
intermediate source against an old fixture and still refuse at the later source
identity gate. Final acceptance uses the unchanged complete source-identity checks.

## Enforced-cap results

| Complete request | Process peak (KiB) | Cgroup peak (bytes) | Time (s) | Result |
|---|---:|---:|---:|---|
| Origin public status, first call | 401888 | 380280832 across both calls | 98.695 | PASS |
| Same process, second public status | 401888 | same | 95.751 | PASS |
| Origin `/panel.json` | 423884 | 397017088 | 92.853 | HTTP 200, shadow `ok` |
| Advanced public status, first call | 419848 | 390377472 across both calls | 89.866 | PASS |
| Same process, second advanced status | 419848 | same | 79.547 | PASS |
| Advanced `/panel.json`, 20 positions | 437184 | 410624000 | 91.089 | HTTP 200, shadow `ok` |
| Bypass optimized status path | n/a | cap 536870912 | ~28 to process exit | OOMKilled=true, exit 137 |

The first-origin status process peak is **392.47 MiB**, versus the retained
~1.92 GiB baseline; full HTTP is **413.95 MiB**. Both positive containers exit 0,
with zero cgroup `max`, `oom` and `oom_kill` events and Docker OOMKilled=false.
The second request does not raise the process watermark. RSS and cgroup charge
account shared/file-backed pages differently; neither figure substitutes for the
other. The actual cap is 536870912 bytes, with swap prohibited.

The origin state hash equals the initialization result
`b6ad3fb504424fa74dc6f59c2460e46c034fba5ba45d253f5a8ef7b4f9bfc97e`;
both calls retain authority
`f62a6ccd47c1419b3e61722b0e93c31fe11fc16a833c1c3790d914ff24f4d2ad`,
NAV `100000`, session count and zero commands/fills. HTTP overall is `fail`
because this resource fixture deliberately lacks operational evidence; the
shadow row is independently verified. The initial HTTP probe used uppercase
`OK` instead of the API's lowercase `ok`; its assertion failure is retained.
The corrected probe does not change production code or its response.

Publication took 393.480 s and initialization 411.299 s. The setup process reached
2961756 KiB (2.82 GiB); this is **not** a reader measurement and leaves production
initialization's separate 2 GiB qualification open. Capped reader measurements
overlapped in independent containers against one offline database; their wall
times are observations under that load, not an accepted latency bound.

The real next-session publication/transition took 1007.224 s and committed
20 held positions. Advanced status peaks at **410.01 MiB** on both calls, with
unchanged state `bf49cb9b3466d1aa0abaf4adb6eabaed9e7e3be23d0c8c2f9fcd5b84bffafb61`,
authority `c11ea5fd74c497cf0e55fdeaa553a225ea52c3746b239f0cbd87586916d4b488`,
NAV and database counts. Both advanced containers exit 0 without OOM or cgroup
limit events. Advanced HTTP peaks at **426.94 MiB**. Its first reader attempt
correctly refused a stale synthetic source clock; `run_reader.py` now moves all
three fixture clocks together, without weakening the source-finality gate.

The independent [Decimal accounting probe](economic_oracle.py) reads only stored
quantity/entry/mark text and calls no strategy arithmetic helpers. Entry notional
is `97916.280`; the frozen 10 bps cost is `97.916280`. Expected cash is
`1985.803720`, versus retained `1985.80372000001`. Copied market inputs are flat;
float-reconstructed marks add only `8.80E-12`. Expected NAV is
`99902.08372000000880`, versus retained `99902.08372000002`, a `1.120E-11` difference.
This explains the economic delta as entry costs plus numerical roundoff. It is
an accounting check, not an independent oracle for security selection or a
historical backtest. The initial probe's slot/security-key mistake and overly
strict float-mark equality failure are retained. No stored value was changed.

## Targeted validation

`raw-logs.zip` preserves 50 raw logs/fixture metadata/ownership artifacts;
`raw-log-sha256.json` binds each member. `measurements.json` extracts the final
reader metrics and Docker exit/OOM records. `source-sha256.json` binds the reviewed
Git blobs; `artifact-sha256.json` binds this evidence package and its design/ledger
documents. Earlier #417 evidence and concurrency code remain byte-for-byte intact.
All task-owned containers were stopped/removed after measurements.

```sh
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_status_memory.py tests/sentinel/test_production_state.py tests/sentinel/test_canonical_session_kernel.py tests/sentinel/test_issue_252_253_session_envelope.py
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_shadow_observation.py tests/sentinel/test_rolling_runtime.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_rolling_recovery.py tests/sentinel/test_rolling_initialization.py tests/sentinel/test_panel_concurrency.py tests/sentinel/test_panel.py
python audit/economic_399/status_memory/mutations.py
python tools/validate_test_responsibility.py --base origin/main --output <scratch>/ownership.json
```

The mutation script runs only inside a disposable `/tmp/repo` copy with `/source`
mounted read-only; the [command record](commands.md) records the offline Docker launcher.
Ten controls cover full-payload equality, row session, early seed release,
consumed refusal, status routing, streamed completeness, transaction identity,
read-only mode, excess suffix refusal before allocation and decoder lifetime.
Every control requires a fresh passing baseline and an assertion failure after
the selected guard is broken. Intermediate failed tests and scaffolding errors
are retained, not hidden or counted as passes. Campaign counts overlap.

Final-source results: **77 passed in 59.61 s** for the first command (before the
additional excess-suffix test, separately passing in its mutation baseline);
**277 passed in 700.65 s** for the second, with one existing Starlette/httpx
deprecation warning. All ten final controls are killed: the first nine in
`status-memory-release-mutations.log`, decoder lifetime in
`status-memory-lifecycle-mutant.log`. The earlier decoder mutation in the first
log failed on adapter routing rather than lifetime and is not substituted for
the corrected lifecycle assertion. Ownership: **489 modules, zero unowned, PASS**.
Eleven implementation/test/probe Python files parse and are pyflakes-clean; the two
modified existing test modules also passed syntax checks. Fourteen source hashes
match committed Git blobs; the fixture's five changed production files match.

## Remaining work and NAS handoff

Resource evidence is scoped to the synthetic universe, first-origin/advanced
checkpoint and measured HTTP entrypoint. Real retained identifier/action history,
rename/rebase and entitlement volume, larger universes, database backend memory,
material-consuming initialization/certification and acceptable latency remain
separate gates. Provider C1/F6, F19 and C3 and authoritative historical economic
deltas are unchanged. Stage 1 and economic certification remain incomplete.

Before NAS qualification: merge owner-reviewed fixes after required CI; retain
the exact commit/image/dependency identities; follow reviewed source continuation;
obtain a populated, verified disposable restore with complete dated references,
actions, checkpoints and authority receipts. Do not infer those from prices alone.
Exercise both origin and held-position checkpoints and restored/recovered books.
Keep brokers disconnected and all production resource limits unchanged.

The [prior handoff](../full_status/README.md#remaining-local-work-and-nas-handoff)
contains exact read-only Docker inspection, panel/health curl and route-contention
commands. Capture continuous cgroup memory peak/events, restarts and actual CPU
enforcement for repeated requests, not only a one-shot `docker stats`. Require
peak below the effective 512 MiB panel cap, no OOM/restart, no unexplained growth,
unchanged state/NAV/authority and database rows, prompt 503 UNKNOWN/no-store/
Retry-After for contenders, and independent health. Corrupt the isolated restore
only: last streamed data corruption must refuse, and subsequent valid requests
must recover admission. Verify the PostgreSQL service under its own 1 GiB cap.
A reviewed latency budget remains a prerequisite; the 180-second capture timeout
in the prior handoff is not an accepted SLO. Any missing input or failed criterion
keeps that qualification gate open.

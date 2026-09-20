# Canonical serialization cost and isolated resource review

Verified main: `e255a78aaf4f89d25fc634864aafd2656c6cd176`.
Dependency: #418, including #417; original evidence head
`846de2cd8eb3aef23052e42781739083e109421b`, followed by CI-only test fix
`ccf643ad22f9e19667f3742a7ae37df8162da6cb` (integrated without rewriting history).
Measured production implementation: `9bececa241052c43851f5da586499a6ae3a8039f`.
Main advanced during measurement to `8bf86ed8ca1e9fa2a6cbb9ac1588c8bcda8712bb`
(owner-merged #416). It was integrated in a separate checkout without changing
the measured source. Reviewed integrated source/tests:
`ffbf82b127784c145d697078ad1e8c03b70a0c46`; the four production files changed by
this cost review remain byte-identical to the measured implementation. The new
main's paper-reporting changes have separate integration coverage below.
The isolated serialization optimization was `cb8de1c466b7c1efb7ad8f3f5159a5b0ce7cd7b7`.
No NAS or broker account was accessed. Economic certification remains open.

## What changed and why

The 100-security profile attributes 3.92 of 6.12 public-status seconds and
22.06 of 42.39 daily-transition seconds to Python JSON iteration. The session
module now batches at most 256 small scalar array values through Python's
standard strict encoder. Dictionaries retain sorted keys, ASCII escaping and
compact separators; nonfinite values and cycles still refuse. Container
subclasses and numeric-key mappings retain the standard encoder's behavior.
Session validation/hashing and observation hashing share this helper. There is
no persistent verification cache and no omitted state, input or ownership check.

With profiling still enabled, public status is 3.73 seconds, daily transition
26.68 seconds, and advanced status is 3.45 seconds (previously 5.52). These
are call-attribution comparisons, not deployment latency or scale acceptance.
The 100-security advanced NAV is identical before/after: **99903.33772**, with
20 positions. State hashes change because the source identity correctly changes.
Independent standard-library JSON hashes and the retained pre-optimization
session serializer prove byte equality for the same state and identity.

The design decision preceded code in [the cost design](../../../docs/status-runtime-cost.md).
No fixture was repinned, no xfail added and no provider capability enabled.

## PostgreSQL failure found by isolation

The first full scale run after serialization optimization **failed**:
PostgreSQL's 1 GiB cgroup recorded an OOM kill during the first shadow-record
INSERT. The runtime exited 1; this was not a strategy result. Separately exercising
the write exposed a second OOM in the old whole-JSONB genesis equality parameter.
The database server log identifies that SELECT and the signal-9 backend death.
Docker reported OOMKilled=true even though the surviving PostgreSQL supervisor
later exited 0. Exit code alone is insufficient evidence.

`sentinel/observation_storage.py` now assembles at most 128 series per text parse
and combines JSONB pieces in a balanced tree inside a transaction-local temporary
table. Only one complete final row enters durable storage; conflicts never
overwrite retained evidence. Genesis and append rechecks read one coherent
snapshot through an exact-decimal cursor decoder and compare every field and
JSON type. This preserves the distinction between `true` and `1`, and between
`1.0` and `1.00000000000000001`. No hash-only shortcut is accepted. The helper
is included in the economic source identity.

Real PostgreSQL tests compare against the database's independent JSONB equality
oracle, reject corruption below float precision, preserve odd/final batches,
enforce immutable retries, and prove rollback/temporary-table cleanup. A separate
5,000-series storage diagnostic completes in **58.00 seconds**, writer peak
**1,139,096 KiB**, with no OOM in either service. This is storage evidence only;
the complete production run is separately recorded in `measurements.json`.
The first trial used ordinary float comparison and was rejected during review;
its diagnostic result is not the final exact-value acceptance.

## Measurement scope

`run_stages.py` creates one offline PostgreSQL container and separate fresh
producer, initialization, daily-advancement, repeated-status and full-HTTP
containers. All clients share only the database's isolated network namespace;
there are no host ports or external network. Source is mounted read-only.
Synthetic input generation lives only in producer processes. The initialization
and daily processes execute the actual canonical runtime admission/continuation.
The public status checks preserve state, NAV, authority and command/fill/session
counts. HTTP requires the shadow row to be `ok`; overall panel `fail` is expected
because this fixture lacks unrelated operational deployment evidence.

Fixture boundaries are explicit: deterministic test source downloads, a frozen
source-final clock, a test receipt key and a synthetic reviewed-runtime identity.
The inherited producer fixture lowers the tiny-universe seed-row floor to one;
fresh runtime/status processes do **not** inherit that patch and use the production
4,000-row floor at 5,000-security scale. The small-universe run validates the
measurement mechanics, not production breadth. These seams cannot authorize
deployment or provider cash/fill completeness. Existing absent-backup test policy
and test producer identity are likewise fixture authority, not deployed evidence.

Effective controls: runtime/producer **4 GiB, 2 CPUs**; PostgreSQL **1 GiB,
1.5 CPUs, 1 GiB shared memory**; panel **512 MiB, 0.5 CPU**. Every container has
swap capped at its memory limit. The 4 GiB runtime ceiling already exists in
Compose; the older 2 GiB documentation was corrected, not the limit increased.
The local engine reports 16 CPUs and 7,956,783,104 bytes RAM. The targeted
regression container ran concurrently during part of the scale campaign;
wall times are observations under that host load, not an isolated-host SLO.

Image: `sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`
(`sentinel-test:ci`), Python 3.12, PostgreSQL **17.11**. Production Compose pins
PostgreSQL **16.14**. Its cached immutable image was additionally exercised
offline: `postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b`.
All **30** focused SQL/decoder cases pass (22.93 s); the 5,000-series storage
diagnostic passes in **63.38 s**, writer **1,139,252 KiB**. Neither service OOMs.
PostgreSQL reaches its 1 GiB cgroup ceiling with 650 reclaim/limit events and
zero OOM events. This is successful bounded storage evidence, not demonstrated
spare capacity. The complete broad pipeline still uses PG17; the PG16 deployment
configuration and populated NAS restore remain unqualified.
The NAS may use the documented CPU-free graph when quota is unsupported.
Its observed CPU behavior must not be labelled a 0.5-CPU guarantee.

The initial probe was not accepted: copying the entire source tree inside each
capped container polluted cgroup file-cache peaks, and the newly separated
producer lacked its fixture's reviewed runtime identity. The final probe mounts
source read-only and carries the original synthetic genesis identity through
daily publication. It does not replace source/content/continuation guards.
The first profiler filename also shadowed Python's `profile` module; that launcher
error is retained separately from production results. Earlier evidence packages
are unchanged.

## Complete 5,000-security measurements

Every stage completes with Docker exit 0 and OOMKilled=false. Application
cgroups report zero limit/OOM events. Durations below are stage work except
status/HTTP, which show individual public calls. Both repeated calls share one
process and preserve state, authority, NAV and database row counts.

| Stage | Seconds | Process peak KiB | Configured cap |
| --- | ---: | ---: | --- |
| Initial publication | 367.15 | 1,399,808 | 4 GiB |
| Fresh runtime initialization | 426.91 | 2,093,012 | 4 GiB |
| Origin status, twice | 153.15 / 158.38 | 396,456 / 398,308 | 512 MiB |
| Origin complete HTTP | 170.92 | 414,616 | 512 MiB |
| Next-session publication | 341.37 | 1,398,792 | 4 GiB |
| Actual daily transition | 623.63 | 2,088,160 | 4 GiB |
| Advanced status, twice | 139.90 / 139.65 | 411,100 / 411,368 | 512 MiB |
| Advanced complete HTTP | 143.77 | 428,352 | 512 MiB |

The database's final cgroup peak is **1,074,302,976 bytes**, slightly above its
configured 1,073,741,824-byte ceiling, with **21,202 max/reclaim events** and
zero OOM events. Retained cgroup/Docker metrics, rather than exit code alone,
define the result. Database pressure and capacity headroom remain open.
The two status calls increase their process watermark by 1,852 KiB at origin
and 268 KiB when advanced; two samples are not a long-duration leak qualification.

The transition retains **20 positions**, **97916.280** entry notional and
**97.916280** existing 10-bps costs. Independent Decimal accounting gives NAV
**99902.08372000000880** versus retained **99902.08372000002**, a difference of
**1.120E-11** dollars; cash differs by **1E-11** dollars. This agrees economically
with the unchanged #418 fixture. Publication plus transition totals **965.00 s**.
The earlier combined setup used different process/database/CPU controls, so no
like-for-like full-scale speedup or accepted latency SLO is claimed.

Final production regression: **397 passed**; focused storage/identity **161
passed** (overlapping); expanded decoder lifetime **4 passed**; **11** meaningful
guard-removal controls detected after passing baselines. Current-main integration:
**163 passed** plus all eight 100-security smoke stages, with unchanged advanced
NAV **99903.33772**. Exact invocations and timings are in [commands.md](commands.md).
The listed changed modules are lint-clean; `decision.py` retains one pre-existing
lint warning, documented separately. Ownership covers 491 modules, zero unowned.

## Local inputs and historical replay

The retained inventory is the complete tracked-repository result of:

```sh
git ls-files '*.parquet' '*.csv' '*.arrow' '*.duckdb' '*.sqlite' '*manifest*.json'
```

It lists 59 paths: derived reference/reproduction/audit CSVs, `listing.csv`,
and two audit metadata JSON files whose directory matches the manifest glob.
It does not describe other branches. The user subsequently identified GitHub's
backtester branch, and the retained PIT artifact was located and downloaded.
Golden output files remain immutable and cannot substitute for the inputs.

GitHub `research/backtester` was verified at
`e088bfd26c695309e259cfc44ab1e8982d6f858d`. Its base pointer names dataset
`7ceaaf4f88a3cd038df8fed328a52cf138251fad36ab32cf4a7af8c26c2266b2`, schema `/1`,
artifact **9832556817** from run **33588053707**. The 1,499,464,242-byte archive
was downloaded through the already authenticated GitHub CLI and its published
SHA-256 `4d0aa14b65c308f232e0a6d9896f797a49c109f6b423f2877964030729c293d7`
verified. `pit_inventory.py` independently streams all 27 data members, verifies
their hashes/bytes/row counts, the manifest/pointer and aggregate dataset hash,
and strict observation ordering. **31,820,893 observations, 16,957 securities,
5,176 sessions, 253,076 actions and 10,652 terminal rows** verify in 110.42 s.
The artifact is retained locally outside the PR; only provenance/results enter
this evidence package. This closes the "input location unknown" gap.

The real workload reaches **8,408 observations in one session** and **2,474,682
observation rows in a 300-session window**. The 5,000-security synthetic resource
pass therefore does not qualify the largest historical input. These counts now
provide a concrete minimum stress target; retained identifier/action history
must also be included in the next acceptance campaign.

**Replay admission remains OPEN, not because the data does not exist.** The
current backtester loader requires schema `/2`; its workflow rebuilds SEC-V2
metadata and explicitly refuses the retired base hash as the final dataset.
The required `backtester/data/historical-metadata-v2.json` is absent from the
named metadata branch at verified head
`9536ee216f0d8ef2299530a02e0fa1f41154fce1`. The runbook and historical generation
descriptor name another dataset (`f9fb2208...`, 18,948 securities), retained on
the recovery-v4 branch; it must not be silently substituted. The historical
launcher also pins four production blobs that differ from current production.
These are concrete dataset/harness integration gaps, not economic results.
The retained base records 10,650 incomplete terminal terms and 9,302,460 unknown
security-type observations; its construction PASS does not make those facts
complete or positively eligible. No schema/source guard was relaxed and no old
multiple is represented as the current strategy's performance.

Next procedure: resolve and authenticate the accepted metadata/dataset version,
review the current-production replay adapter, preserve both dataset identities
and all golden outputs, and compare chronological production/research paths.
The existing archive can support diagnostic workload measurements immediately;
economic acceptance requires the compatible admitted corpus and input envelopes.

Required export: sealed dated raw/signal/adjusted price domains and benchmarks;
complete dated identifier/rename and corporate-action history; entitlement,
cash and terminal terms; publication receipts/content hashes; origin and advanced
checkpoints; source/image/dependency and continuation identities. Include actual
row counts, reference bundle bytes, action multiplicities and maximum symbol-chain
depth so retained-history resource stress has a defensible target. Synthetic
minimal actions in this probe do not qualify larger retained reference histories.

Replay procedure: verify all input hashes and identities first; initialize once;
feed sessions chronologically through publication, canonical runtime, execution
simulation, restart and reconciliation. Use overlapping 300-session *input*
windows while carrying cash, holdings, pending orders, action entitlements and
controller state across chunk boundaries. Retain daily economic deltas against
the unchanged reference, explaining fees, raw/adjusted price domains, corporate
actions, sizing, terminal treatment and precision separately. Verify restart and
chunk-boundary equality. Do not restart capital per chunk or promote synthetic
provider responses to cash/fill finality. Missing authority or an unexplained
delta fails that gate; this resource run is not a 20-year return backtest.

## NAS handoff (not executed)

Prerequisites: owner-merged changes with required exact-head CI; reviewed immutable
runtime image/dependencies and source continuation; a populated disposable
restore with the authoritative inputs above; accepted operational latency and
capacity budgets; separate backup target; broker access disabled. Keep all
effective memory limits. Resolve the supported graph rather than bypassing its
backup and host-capability checks:

```sh
bash scripts/sentinel-compose.sh --run ps -q sentinel-panel > panel.id
bash scripts/sentinel-compose.sh --run ps -q sentinel-postgres > postgres.id
panel_id=$(cat panel.id)
postgres_id=$(cat postgres.id)
test -n "$panel_id" && test -n "$postgres_id"
docker inspect --format '{{.Image}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.HostConfig.NanoCpus}} {{.State.OOMKilled}} {{.RestartCount}}' "$panel_id" "$postgres_id"
curl --max-time 600 -sS -D status.headers -o status.json -w '%{http_code} %{time_total}\n' http://127.0.0.1:8004/panel.json
curl --max-time 10 -sS -D health.headers -o health.json http://127.0.0.1:8004/health
```

The 600-second client timeout is only a capture ceiling, not a pass threshold.
Capture cgroup v2 `memory.peak`, `memory.events`, `memory.current`, `cpu.stat`
or cgroup v1 `memory.max_usage_in_bytes`, `memory.failcnt`, OOM control and CPU
accounting before, throughout and after each request. Preserve Docker inspect,
full logs, repeated-request latency, state/NAV/authority hashes and database
row counts. Repeat at origin, held-position, restored and largest retained-history
states; exercise all route owner/contender pairs and post-error recovery.

Pass requires unchanged economic/authority outputs and database counts, no OOM
or restart, application peaks within caps and justified non-reclaimable working-set
headroom for every service. PostgreSQL file cache may reach its cgroup ceiling;
retain `memory.stat` and reclaim/limit events to distinguish that from resident
working-set pressure, and assess the resulting latency against the accepted budget.
Require
no unexplained repeated-request growth, responsive independent health, immediate
503 UNKNOWN/no-store/Retry-After for contenders, and the **reviewed** latency
budget met. Separate fresh-process cold initialization/daily resource measurements
must exclude input generation and include the PostgreSQL backend. Corrupt only
the disposable restore: changed final data, missing receipts, stale source and
wrong continuation identity must refuse. Any missing input or failed criterion
keeps the gate open. Provider C1/F6/F19/C3 remain independent unresolved gates.

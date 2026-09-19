# Complete status resource review

Verified base: `flabber1835/stocker:main`
`29cdd7727ba2adea27672830c538d76a2218943e` (owner-merged #412 and #413).
The isolated branch `codex/full-status-resource-review` integrates pending
#415 `558673b1b434760673ee1de52c25c4e1e1f707c7` in integration commit
`0eb704349e2c3f4932f877e9c0a6f9fcdd50cbb4`. Its PR records the final reviewed
commit; the source manifest binds the reviewed Git blobs. Existing PR branches
and golden artifacts were not changed. The
[design](../../../docs/full-status-resource-review.md) preceded implementation.

## Findings and dispositions

| Finding | Disposition | Evidence and scope |
|---|---|---|
| P2: simultaneous full HTTP builds multiply retained state | Locally fixed | `sentinel/panel/app.py:39` shares one nonblocking admission slot across `/`, `/panel.json`, `/operational-health`; `docker-compose.sentinel.yml:182` explicitly selects one worker. Contenders receive 503 UNKNOWN, no-store and Retry-After 5; HTML retries automatically. Actual HTTP overlap and exception recovery are tested. |
| P2: one complete status request exceeds the panel budget | **OPEN implementation/resource defect** | `sentinel/panel/sources.py:1702` invokes full shadow status. `sentinel/rolling_runtime.py:25` enters checkpoint reconstruction (`rolling_daily_checkpoint.py:102`) and canonical observer verification. Each measured reader reaches approximately 1.92 GiB against the configured 512 MiB panel budget. Serialization does not fix this. |
| P2: cumulative verification latency | **OPEN local resource work** | Approximately 131 seconds per reader with two concurrent readers sharing two CPUs; about 99 seconds in closure verification and 31 seconds in current-input verification. SQL statement timeouts do not bound cumulative Python work. Target latency remains unqualified. |
| Realistic reference/action history and advanced checkpoint capacity | Data-dependent, still open | This fixture has 5,000 current identities and only the small provider fixture's action history. It does not model twenty years of renames, rebases, entitlements or a populated multi-day position book. |

Canonical observer normalization (`sentinel/shadow_observation.py:219`), genesis
verification (`:1208`) and history reconstruction (`:1562`) repeatedly construct
large state objects. Phase timing localizes the dominant cost to closure, but
does not attribute every allocation to a particular line. A subsequent fix must
preserve canonical identity, mutation isolation, restart validation and economic
inputs. Neither cached authority nor a raised memory limit is accepted here as
a substitute for that work.

## Measurement and limitations

Offline disposable PostgreSQL, 5,000 synthetic securities over 300 sessions:
**1,500,000 stored rows**. Real acquisition/publication, canonical warmup and
first-origin initialization precede two fresh subprocess calls to
`shadow_runtime.verified_shadow_status`. Wrappers time the real functions without
replacing their implementations. This is complete public shadow status, not the
entire HTTP panel build, a multi-day replay or authentic provider evidence.

Container limits: **8 GiB, two CPUs, network disabled**. Image:
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`
(`sentinel-test:ci`). Source is mounted read-only and copied into `/tmp/repo`.
Synthetic source clocks, receipt key, reviewed runtime identity and absent backup
policy marker are explicit test scaffolding, not new provider capabilities.

| Phase | Reader 95 seconds | Reader 96 seconds |
|---|---:|---:|
| Closure/checkpoint/observer verification | 99.5706 | 99.3795 |
| Current input assessment | 31.0462 | 31.3456 |
| Snapshot context, nested inside current input | 19.8280 | 20.0087 |
| Complete public status | 131.2066 | 131.3263 |
| Reader VmHWM (KiB, not seconds) | 2,013,424 | 2,012,992 |

Publication took 344.7800 seconds and initialization 364.3775 seconds, separately
from reader timings. Parent VmHWM was 2,966,684 KiB. Readers started at only
56,548/56,664 KiB. Use Linux `/proc/self/status` **VmHWM** for reader peaks:
`resource.ru_maxrss` carried the parent's earlier 2,966,684 KiB watermark into
these children and is retained separately, not reported as reader memory.
The initial 100-security smoke (30,000 rows, status 2.9070 seconds) predates this
counter correction; its RSS number is not an isolated reader measurement.

Both scale readers exit zero. Each asserts unchanged state hash and processed
session count, with zero commands and fills. Inspection of retained output shows
the same authority hash and NAV for both:

- State: `46f599ac7462d99c330732c24dc0985f7f4e26cdef5cc40679ac6cfa3a7f1155`
- Authority: `f0dd08a715796e6d608d8e881c9ea0688cf0171e761350565871a314a30fbb48`
- NAV: `100000`, the initialized first-day book, **not a historical return**.

No cgroup OOM or container peak is claimed. These readers ran concurrently in
the 8 GiB test container, not the deployed panel's 512 MiB / 0.5 CPU envelope.
Their peaks independently exceed that budget; the timings are neither
single-reader baselines nor qualified NAS latency.

## Exact validation commands

Run from this repository root with Python 3.12 and the named local test image:

```sh
python audit/economic_399/full_status/run_local.py --universe 100 --readers 1
python audit/economic_399/full_status/run_local.py --universe 5000 --readers 2
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_panel_concurrency.py tests/sentinel/test_panel.py tests/sentinel/test_operator_monitoring.py
python audit/economic_399/full_status/run_local.py mutations
python -m pyflakes sentinel/panel/app.py tests/sentinel/test_panel_concurrency.py audit/economic_399/full_status/probe.py audit/economic_399/full_status/run_local.py audit/economic_399/full_status/mutations.py
python tools/validate_test_responsibility.py --base origin/main --output <scratch>/full-status-ownership.json
docker run --rm --network none --entrypoint python sentinel-test:ci -c "import os; from uvicorn import Config; os.environ['WEB_CONCURRENCY']='8'; config=Config('sentinel.panel.app:app',workers=1); assert config.workers==1; print('Explicit workers=1 overrides WEB_CONCURRENCY=8')"
git diff --check
```

Before the production fix, the new concurrency module alone produced **10
failures / 3 passes** in 18.89 seconds. Final targeted regression: **160 passed**
in 32.30 seconds, one existing Starlette/httpx deprecation warning. All **four
mutants killed**, each after a fresh passing baseline: two build slots, an
unprotected HTML route, missing exception cleanup, and missing explicit worker
selection. Mutations occur only in the disposable copy. Five Python files parse;
pyflakes is clean. Ownership: **487 modules, zero unowned, PASS**. The installed
Uvicorn check confirms explicit workers=1 overrides WEB_CONCURRENCY=8.

HTTP tests use real routing/concurrent clients with an event-controlled source
fixture. They prove request admission and recovery, not the resource cost of a
real database-backed HTTP response. The scale probe separately measures real
database-backed public shadow status. Source identity/quantity/NAV golden values
were not repinned and no xfail or capability override was added to production.

Raw logs, including pre-fix failures and the earlier smoke, are retained
byte-for-byte in `raw-logs.zip`; `raw-log-sha256.json` binds each member.
`source-sha256.json` binds reviewed Git source blobs. `artifact-sha256.json`
binds the evidence files without recursively hashing itself.

## Remaining local work and NAS handoff

**Do not qualify or deploy this as a completed resource fix.** First resolve the
single-request checkpoint/state allocation and establish a bounded verification
budget locally, preserving canonical hashes and rejection falsifiers. Repeat
full status and complete HTTP measurements under the unchanged panel limits,
including advanced held-position checkpoints and simultaneous external refreshes.
The admission fix is independently reviewable while this work remains open.

Missing authoritative inputs: a sealed retained publication with complete
dated identifiers, rename/rebase/action and entitlement history; actual populated
origin/daily checkpoints and session suffixes; reviewed image/source/dependency
identity and continuation receipts. Twenty-year PIT prices alone do not replace
these inputs. On a disposable local restored copy, verify all retained hashes,
run first-origin and advanced-checkpoint status repeatedly, retain state/NAV and
authority hashes, commands/fills and session counts, then collect VmHWM, cgroup
memory and wall time. Refuse absent/inconsistent evidence; do not enable flags
or interpret empty responses as completeness.

After local closure and owner-approved integration of dependent PRs, a NAS
operator must use the deployment document's exact-image procedure, a qualified
populated restore and no broker-facing test requests. Record the reviewed commit,
image digest, corpus/checkpoint identities and effective resource controls. On
the NAS host, these read-only commands capture the running panel and a response
(execute only during that separately authorized qualification):

```sh
panel_id=$(docker compose -f docker-compose.sentinel.yml ps -q sentinel-panel)
docker inspect --format '{{.Image}} {{json .Config.Cmd}} {{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.State.OOMKilled}} {{.RestartCount}}' "$panel_id"
docker stats --no-stream "$panel_id"
curl --max-time 180 -sS -D status.headers -o status.json -w '%{http_code} %{time_total}\n' http://127.0.0.1:8004/panel.json
curl --max-time 10 -sS -D health.headers -o health.json http://127.0.0.1:8004/health
```

The 180-second client timeout is a capture ceiling, not an accepted latency SLO.
Retain continuous cgroup peak/OOM-event monitoring for the whole qualification;
`docker stats --no-stream` alone cannot establish peak memory. Exercise all nine
owner/contender route pairs with the first build observably in progress. Require
one active build, prompt contender 503/no-store/Retry-After, independent health,
and successful next request after both normal completion and source failure.
Do not inject failures into the live database; use the isolated restored copy.
Require no OOM, restart, unexpected database mutation or authority mismatch and
peak memory below the effective 512 MiB cap. A reviewed operational latency
budget and its measured pass/fail evidence remain prerequisites, not invented
acceptance thresholds. The NAS's actual CPU enforcement must be recorded.

Provider C1/F6 cash completeness/finality, native F19 fill authority and C3
predecessor-incarnation evidence remain open. Historical economic deltas require
authoritative inputs and separate day-by-day replay. Stage 1 and economic
certification remain **incomplete**. No NAS or real broker was accessed.

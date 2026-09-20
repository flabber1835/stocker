# Report-only caller follow-through

Additive review of PR #415 after `b36fb1a63b56868bb1aa301b13df6d6ced6226a7`.
Authoritative main was fetched as `e3dfb033d25ed68e5e1f6d2386285afabc62e801`.
The PR records the reviewed follow-up commit. The parent evidence package and
its manifests describe **b36fb1a6**, not this later revision; their raw ZIP is
unchanged. This directory's source manifest binds the follow-up files.

## Findings and caller coverage

**P2, locally fixed:** nine production checks still materialized and discarded
the entire equity warmup after the first compact-runtime fix. Keep the common
content/reference/action verification and readiness thresholds; request compact
counts at these callers. No new cached authority or provider capability exists.

| Caller | Location | Required preserved behavior |
|---|---|---|
| Operational assessment | `sentinel/feed/rolling_go_inputs.py:81` via `feed/readers.py:63` | Return failed readiness clauses; integrity still raises. |
| Strict readiness | `sentinel/feed/rolling_go_inputs.py:129` | Refuse failed clauses under the caller's read-only pin. |
| Execution readiness | `sentinel/execution/feed_inputs.py:34` | Same current publication and clock; no broker call. |
| Already-current acquisition | `sentinel/feed/rolling_go_inputs.py:155` | Reuse exact binding without strategy state. |
| Newly published acquisition | `sentinel/feed/rolling_go_inputs.py:165` | Checked binding and target still match. |
| Inner operational validation | `sentinel/feed/operational_snapshot.py:76` | Full sealed closure, lease ownership, backup proof, DATA_ONLY receipt. |
| Runtime admission | `sentinel/rolling_runtime.py:113` | Target, writer lock, pin and idempotent committed-candidate identity. |
| Historical pre-transition admission | `sentinel/rolling_recovery.py:40` | Authenticated dated availability and selected historical frontier. |
| Historical post-commit receipt | `sentinel/rolling_recovery.py:49` | Same candidate/receipt on retry; reconstruction-only authority. |

`validate_reconstruction` keeps material-returning behavior by default; the two
reviewed callers explicitly request compact output. The actual daily/recovery
transition still loads canonical continuity inputs. Materialization remains in
initialization, warmup certification, parity, and health certification that derive
the warmup identity. No economic fixture or algorithm was changed.

The pre-fix campaign reproduced **six failing production entrypoints** in
17.45 seconds. First publication initially failed at the inner validation, before
reaching the outer coordinator check. The intermediate regression then had
**84 passed / 1 failed**, 364.87 seconds, revealing that remaining inner call.
Its failing mutation positive baseline is also retained; it is not counted as
a killed mutant. Both inner and outer routes now have separate falsifiers.

## Validation

Run from the repository root with Python 3.12 and `sentinel-test:ci`, immutable
image `sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`.
Each driver run uses an offline disposable PostgreSQL 17.11 container, read-only
source mount, a temporary source copy, 4 GiB and two CPUs. Synthetic publication
and deployment-identity fixtures are test scaffolding, never provider acceptance.

```sh
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_report_consumers.py -k 'never_materialize or never_materializes'
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_report_consumers.py tests/sentinel/test_rolling_status_inputs.py tests/sentinel/test_rolling_go_inputs.py tests/sentinel/test_rolling_runtime.py tests/sentinel/test_rolling_paper_inputs.py tests/sentinel/test_rolling_admission_readers.py tests/sentinel/test_operational_snapshot.py
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_recovery_report_inputs.py tests/sentinel/test_rolling_recovery.py tests/sentinel/test_rolling_go_inputs.py
python audit/economic_399/rolling_status/run_local.py consumer-mutants
python audit/economic_399/rolling_status/run_local.py consumer-mutants recovery_admission recovery_receipt
python audit/economic_399/rolling_status/run_local.py go-mutants
python audit/economic_399/rolling_status/report_consumers/static_check.py
python tools/validate_test_responsibility.py --base origin/main --output <scratch>/rolling-consumers-final-ownership.json
git diff --check
```

Final connected campaign: **112 passed in 412.02 seconds**. Recovery campaign:
**33 passed in 244.18 seconds**. The connected campaign preceded the final optional reconstruction
argument; the later recovery campaign reruns the shared GO-input tests on that
final source. Campaign counts overlap.

Seven ordinary caller mutants are killed, each after a positive baseline. The
two historical caller mutants are also killed, recorded separately.
The final driver includes all nine; running it without selectors repeats all.
All **11 existing readiness mutants** are killed. The five existing negative
material-domain tests now explicitly call material-returning `validate`; their
assertions and shared readiness thresholds are unchanged. New tests exercise
the compact production callers with real published data, stale clocks and late
positive-price corruption. Recovery tests preserve genesis, NAV/state identity,
non-prospective scope and absence of commands/fills; the existing continuous
versus interrupted production run supplies the independent economic comparison.

Eleven changed/new Python files parse; pyflakes has **no new findings**, comparing
with the b36fb1a6 files. Existing calendar re-export and pytest fixture import
warnings are retained. Test ownership passes (**485 modules**), with
zero unowned modules. All raw logs, including intermediate failures, are stored
byte-for-byte in `raw-logs.zip` with member SHA256 values. Source and artifact
manifests are checked against committed Git blobs before publication.

## Remaining work and qualification

The earlier scale result (761 MiB to 128 MiB) measured the common input reader;
it is **not a new measurement of these complete callers**. Full scans still cost
about 29 seconds in that synthetic fixture. Remaining local review includes
complete checkpoint/state and reference/action loads, realistic concurrent panel
requests, and full-call latency. Material-consuming certification paths remain
subject to their actual service resource budgets.

Current main already includes bounded backup selection and manifest reads:
`backup_runtime_authority.py:137` reads 257 selection bytes, and `:193` reads
8 MiB plus overflow before parsing. Prior ledger claims that their implementation
is absent are historical, superseded by the later follow-ups. Capacity and
complete-caller deployed latency still require qualification. Maintenance #413
and heartbeat #414 are separate pending fixes; this PR does not integrate them.

For NAS handoff, follow the [parent procedure](../README.md#remaining-gates-and-nas-handoff)
only on an owner-approved isolated restore with no broker credentials/network.
Use the accepted final image/source identity; run the campaigns above and retain
their output, source hashes and every intended mutant failure. Require unchanged
economic state and zero command/fill writes for status/idempotent checks. Include
fresh historical recovery, interruption after candidate commit and restart;
require the same candidate and reconstruction-only scope, never live GO. Run
actual panel/status, acquisition and recovery processes with authoritative full-
universe references/actions and record each service's peak container memory and
wall time. Pass only below its configured budget and approved deadline, with
no OOM, stale acceptance or unexplained economic differences. No NAS run occurred.

Provider C1/F6/F19/C3, authoritative historical input/replay, filesystem/host
failure and NAS deployment evidence remain separate gates. No 20-year multiple
or certification is established. Stage 1 remains open.

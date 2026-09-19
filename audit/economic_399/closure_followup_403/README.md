# Step 1 follow-up after merged PR 403

Verified base: `4dd5af636ed48d6c17d8a75af4209cbc23a17e48`.
Delivery is PR-only; this package does not certify economic results or NAS use.

Two remaining implementation findings are addressed: durable Web Push recipient
succession/response fencing (A6, P2), and streaming deployment deadlines (A24,
P2). Designs were recorded before implementation in the certification ledger
and operator-monitoring contract. No strategy code, golden, capability flag,
broker account or NAS was changed/accessed.

The local campaigns use the existing offline test image, a read-only checkout,
an empty environment file and disposable PostgreSQL 17.11. They do not establish
PostgreSQL 16/NAS qualification. Source hashes identify the reviewed final files;
the delivered commit is recorded in the associated PR.

| Validation | Result |
|---|---|
| Deployment runner and recovery regression | 42 passed |
| Initial notification/schema/attempt regression | 118 passed |
| Additional migration/concurrency acceptance | 27 passed |
| Expanded relevant regression | 239 passed in 64.49 s |
| Final lock-order correction and stale-attempt acceptance | 29 passed in 18.28 s |
| New falsifiers | Eight killed, each after a passing baseline |
| Static/ownership | Eight changed Python files parse; no introduced pyflakes diagnostics; 472 owned test modules, PASS |

Counts overlap. The 239-case run preceded the final policy-to-outbox lock-order
correction; the 29-case run covers that change. Mutation failures in the logs
are expected only after their unmodified acceptance passes. The existing
outbox attempt mutant is rerun alongside the final result/serialization guards.

Failed attempts are retained: initial schema measurement refused the newly
declared catalog until its measured digest was recorded; the first device-
conflict mutant patched a handler symbol already captured by FastAPI and did
not reach the request path. The corrected mutant patches the transaction helper
the actual route calls and fails on an attempted merge of independent devices.

Reproduce with `python audit/economic_399/closure_followup_403/run_local.py
regression`, or replace `regression` with `final-notifications` or a mutation
name from `commands.json`. `--image` selects the accepted target test image.
The wrapper prints the exact Docker argv. `results.zip` preserves raw logs;
`SHA256SUMS.json` authenticates both files and archive members.

Step 1 remains OPEN for rolling admission/readers, recurring backup maintenance,
resource-bound work and the provider/accounting gates. The full PIT replay is
still data-dependent. The ledger includes the concrete NAS handoff and its
failure criteria; no deployed or economic-certification claim is made here.

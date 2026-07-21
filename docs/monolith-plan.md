# Modular-Monolith Conversion Plan

Status: **BLUEPRINT — approved direction, not yet scheduled.** This document is
the design-of-record for the consolidation both external audits converged on
(2026-07): "the largest improvement would come from consolidating the live
pipeline into one transactional application with durable jobs, immutable run
configuration and explicit stage state." Per the repo's process rule, this doc
precedes implementation; update it as decisions firm up.

## Why (drivers, from the audits + our own experience)

- ~20 services whose real contract is the shared Postgres schema, not their
  HTTP APIs — network/deployment complexity of microservices with the schema
  coupling of a monolith.
- The scheduler re-implements a workflow engine (retries, stale-run reclaim,
  restart markers, date anchors, config pinning) because chain steps live in
  separate processes; in one process the chain is a function call sequence and
  most of that machinery evaporates.
- Giant `main.py` files (pipeline ~179KB, executor ~132KB) mixing API, DB,
  orchestration, and domain logic — change-risk hotspots.
- Every service is a top-level package named `app` → order-dependent tests
  (mitigated today by scripts/run-tests.sh process-per-suite; fixed for real
  by unique package names, which only make sense during this restructuring).
- Cross-stage JSON/HTTP serialization and ~12 separate DB pools that
  in-process calls and one pool make unnecessary.

## Target shape (three deployables + infrastructure)

```text
stocker-trading/          ONE process, the whole daily chain in-process:
  ingestion/              ← av-ingestor
  factors/  ranking/      ← pipeline (factor+rank stages)
  vetting/                ← llm-vetter (drawdown_only deterministic core)
  portfolio/              ← portfolio-builder
  delta/                  ← pipeline delta stage
  risk/                   ← risk-service   (module, NOT a network hop — see invariants)
  execution/              ← trade-executor (module; sole broker-credential holder)
  reconciliation/         ← alpaca-sync
  supervisor/             ← scheduler, reduced to: cron trigger + durable job table

stocker-web/              api + dashboard (dashboard becomes static assets served
                          by the api; the /api/* proxy duplication disappears)

stocker-backtest/         bt-data + bt-engine + bt-scheduler (unchanged isolation:
                          own compose file, own bt-postgres, file-bridge only)

infra: postgres, redis (REVIEW: with one process, most Redis uses — locks,
       events — become unnecessary; keep only what survives), ollama (optional).
```

## Safety invariants that MUST survive the merge (non-negotiable)

The current safety model is enforced partly by process boundaries. In the
monolith it must be enforced by module boundaries + tests:

1. **Risk gate remains the sole approval path.** `execution/` may submit an
   order only with a persisted `risk_decisions` row from `risk/`. Enforce with
   an interface that requires the check-id, plus a test asserting no other
   call path constructs orders.
2. **`execution/` is the only module holding broker credentials** (module-level
   encapsulation replaces container-level).
3. **The LLM never reaches order paths.** Same as today; now assert it with
   import-graph tests (vetting/evaluator modules must not import execution).
4. **Kill switch, PAPER_ONLY/LIVE gates, human-approval flow: unchanged.**
5. **Backtest isolation unchanged** (separate deployable, separate DB,
   file bridge only).

Traded away deliberately: per-service crash isolation (the pipeline-OOM
lesson). Mitigation: keep `mem_limit` on the trading app, run heavy factor
work in a worker subprocess (already partially true via to_thread), and accept
that a crash restarts the whole chain — the durable job table makes that a
resume, not a loss.

## Phases (each independently shippable, tests green throughout)

**Phase 0 — prerequisites (DONE, 2026-07):** canonical `strategy_engine` in
shared/ (one rank/select implementation); shared falling-knife verdict; shared
market-date helpers; process-per-suite test runner + collection guards;
chain-level config pinning; transactional config apply; vectorized ranking.

**Phase 1 — internal decomposition (no topology change):** split the giant
`main.py`s into `api.py / application.py / <stage>.py / repository.py` per
service (audit #10's layout); move engine/client creation out of import time
into app factories (audit #2) — this is what makes the modules importable as
libraries later. Incrementally: exception taxonomy at the seams being touched
(audit #9).

**Phase 2 — packaging:** unique package names (`stocker_pipeline`,
`stocker_executor`, …) or one `stocker/` package with subpackages; single
pyproject; delete the per-service conftest sys.path machinery and the
process-per-suite workaround (audit #7 fixed for real). Big mechanical diff —
do it as ONE commit with the full sweep green before and after.

**Phase 3 — durable jobs + merged chain:** `jobs` table claimed with
`SELECT … FOR UPDATE SKIP LOCKED` (queued→claimed→running→terminal, owner +
heartbeat + lease); chain steps become direct function calls writing the same
run tables (audit #3); scheduler state (chain status, pins, counters) moves
from module globals to the DB (audit #4); strategy config snapshot stored per
chain with an ID every stage references (audit #5 — supersedes hash pinning,
which remains as the transition mechanism). Most of the scheduler's
recovery machinery (RESTART_ABORTED markers, stale-run reclaim, crash-loop
breaker) is deleted, not migrated — the job table subsumes it.

**Phase 4 — topology:** collapse compose to the three deployables; dashboard
static assets into stocker-web; one DB pool per deployable (pool audit note in
docker-compose.yml becomes moot); review Redis usage and drop what in-process
state replaced.

## Explicitly deferred / rejected

- **Workflow engine (Temporal/Prefect/Airflow):** rejected for the live chain
  — post-merge orchestration is a cron trigger + a job table; an engine would
  encode today's service boundaries right before we dissolve them. Optionally
  revisit Prefect for the backtest worker only, after Phase 4.
- **Vol-target/covariance risk model changes:** out of scope here; the
  hold-safe/buy-closed failure mode (migration 0044) is already live.
- **DB schema changes beyond the jobs table:** none planned; run tables stay.

## Sequencing note

Phase 1 can start anytime in idle weeks. Phases 2–4 want a quiet market
period and the wind tunnel operational first (so regressions in the merged
chain can be caught by comparing sim output before/after). The Sharadar
corpus purchase and first sweeps come BEFORE this conversion.

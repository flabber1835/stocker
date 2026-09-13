# Full-system historical PIT replay

Owner authorization: 2026-09-11. Continue the market laboratory over the broad
historical universe and instrument the complete production lifecycle. Deliver
on `codex/full-system-pit-replay` through a pull request.

## Current authority

The application under test is the checked-out pull-request tree. It must select
the production compact champion through `sentinel.strategy.production_strategy`.
Runtime source is never reconstructed, patched, or relabelled by the replay.
The manifest binds the exact Git revision, the complete `sentinel/` and
`shared/` Python source map, the production strategy identity, and the replay
harness bytes.

The historical comparison authority remains the independent PR #352 run:

| Authority | Frozen value |
| --- | --- |
| Reference result commit | `2a1bd486241ae524eac395490b135cc79715e497` |
| Champion source commit | `f6ad7b543fbd20ffe363127d1120f4472caa9360` |
| Champion source SHA256 | `3fcf274dc5dba5b01ff3c637b62922f27c5dfe2e3b28e7f3a416e1bfeba09663` |
| Canonical dataset SHA256 | `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993` |
| Corpus package digest | `f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c` |
| Frozen warmup start | 2006-01-03 |
| Frozen measurement | 2006-07-31 through 2026-07-31 |
| Frozen coverage | 5,176 observations; 5,032 measured sessions |
| Frozen ending multiple | 56.265349336558316 |
| Frozen CAGR | 22.323600023175572% |

The reference is read only by the comparator. It cannot supply decisions,
orders, holdings, ranks, state, action terms, or readiness to the application.
The package and reconstructed classifications retain their existing provenance
limitations.

## Verdicts are deliberately separate

The old harness treated the first reference mismatch as a process failure. That
made the requested pair of outputs impossible: it could retain a first
divergence or compute corrected full-history performance, but never both.

The replacement has two independent verdicts:

1. `corrected_production_replay` requires the complete schedule, production
   readiness, production loaders, durable state, execution/reconciliation,
   restart/restore, corpus reconciliation, and evidence coverage. Any failure
   here stops immediately.
2. `frozen_reference_comparison` records the first exact or declared-numeric
   mismatch against PR #352. A mismatch does not change production state and
   does not stop the corrected run. The comparator stops consuming reference
   state after the first mismatch so a partially updated oracle cannot create a
   cascade of misleading secondary differences.

A completed corrected run reports its own ending multiple and CAGR even when
the frozen comparison diverges. It may claim historical equivalence only when
the comparison has no divergence. Neither verdict authorizes deployment.

## Production owns warmup and stopping

The replay supplies only external provider responses, broker responses, market
time, failure schedules, and evidence storage. Production owns:

- history sufficiency and session-effective metadata;
- feature warmup and strategy/controller state construction;
- ticker eligibility and source normalization;
- publication and readiness;
- whether a session can advance, wait, or refuse;
- execution, reconciliation, recovery, and durable command identity.

There is no short-tail SQL loader, session-count readiness exemption, synthetic
controller bootstrap, strategy threshold override, or staged source patch. A
production refusal is retained verbatim.

The frozen package starts on 2006-01-03. Current compact-champion production
warmup requires 252 exact XNYS sessions with dated SPY, metadata, and terminal
evidence strictly before the first strategy transition. The package has no
pre-2006 observations (and only 144 sessions before the 2006-07-31 measurement
start), so it cannot preserve the frozen schedule or reconstruct its
pre-measurement book through production. The replay must refuse this before the
expensive physical run unless a new immutable package adds the missing
pre-2006 authority. Backdating current metadata or weakening the 252-session
contract is not an allowed repair.

The pinned XNYS calendar resolves that required prefix to 2005-01-03 through
2005-12-30. An extended package keeps the first strategy transition and
measurement window unchanged, sets its manifest `window.warmup_start` to
2005-01-03 or earlier, and contains a contiguous `observations-YYYY.csv.gz`
member for every covered year. Its cash/benchmark histories and the metadata,
action, and terminal authorities cover the same prefix. Publication requires a
new immutable dataset hash and OCI package digest; neither may be inferred from
the existing package. The compiler accepts an earlier declared package start,
but the production preflight still derives and checks every required session
from the pinned calendar before any replay can pass.

## Information and time

The provider owns an immutable economic history and a versioned delivery
schedule. The application owns a separate PostgreSQL corpus containing only
received data. The comparator owns the frozen reference. Each observation
records effective time, publication time, and receipt time independently.

Initial application data must include the complete production warmup before the
first strategy transition. Warmup is feature-only; it may not manufacture a
historical portfolio. The application then advances every scheduled session in
chronological order from a fresh book. Later provider versions may revise old
rows, but prior decisions retain their immutable input snapshots.

Split-driven historical rescaling is reconstructed causally. Unsupported source
inversions, missing authority, and ambiguous identity are named failures.
Price, metadata, action, and disclosure conventions cannot be changed to improve
agreement. Appending a future delivery must not alter earlier observations or
evidence.

## Daily order

1. At the opening boundary, advance market and broker truth. Execute the prior
   close's durable plan, then observe fills and reconcile. The new close remains
   hidden.
2. Release scheduled Sharadar observations after the close.
3. Run production ingestion, correction, publication, and readiness through the
   real paginated Tables and Exporter transport.
4. Pin the publication and load inputs through the production loader.
5. Advance the production strategy exactly once, persist state, and construct
   the next-session plan.
6. Record the corrected state/performance and, until the first mismatch, compare
   the same session with the frozen reference.
7. Record operational health and committed progress. Exercise scheduled
   PostgreSQL restart and final physical backup/restore.

Readiness and validation are never injected. Invalid data cannot quietly
consume a strategy session.

## Held-event economic attribution

Every production Wealth Core transition retains each terminal result before
bounded session evidence is persisted. For every event that encountered a held
episode, the replay records:

- session, security identity, terminal kind, method, source, and availability
  phase;
- applied/blocked outcome and reason;
- old-share basis, split or exchange multiplier, delivered whole/fractional
  shares, and shares at settlement when present;
- cash per old share, cash consideration, cash in lieu, and total proceeds;
- carry and settlement notionals and their delta when present;
- the complete source result payload and its digest.

The final attribution is grouped by security and settlement method and proves
that its row count and digest match the observed transition stream. This is the
historical witness for combined-event cash basis and terminal opening causality.
It complements, rather than replaces, the direct falsifier tests.

## Instrumentation and evidence

Every event has a monotonic sequence, simulated UTC time, session, phase,
content-addressed payload, and append-only hash-chain link. Large payloads are
retained by digest. Missing instrumentation, unexpected exceptions, timeouts,
stale output directories, and unverifiable objects fail the run.

Retain provider requests/responses; publication and row-change identities;
strategy/controller transitions; plans, broker requests/responses, fills, cash,
positions, and reconciliation; first reference divergence; held-event
attribution; environment identity; restart/restore; and resource measurements.
Secrets are excluded by explicit capture fields.

Broker NAV is reconciled as execution evidence. It is not strategy return
authority. Corrected scalar NAV is computed from production shadow NAV,
production exposure decisions, and published defensive-asset returns, with the
same declared transition costs as the frozen comparison.

## Acceptance

A full corrected-system pass requires:

- direct execution of the checked-out production strategy and exact source
  manifest verification;
- enough authoritative history to satisfy production warmup without overrides;
- all scheduled sessions after that warmup;
- no production readiness, ingestion, execution, reconciliation, restart,
  restore, or evidence failure;
- complete final corpus reconciliation;
- complete held-event attribution;
- a retained first frozen-reference divergence or an explicit no-divergence
  result; and
- corrected ending multiple and CAGR over the declared measurement window.

Partial or refused output states its completed coverage and failed gate. A green
workflow alone is not deployment or account authorization.

## Prior prototype runs

The prototype staged an old base plus a 7,421-line V5 patch and supplied its own
first-40-session loader/readiness behavior. Those mechanisms are retired.

- Run `34552507591` stopped before session one because an exchange timestamp was
  not normalized to UTC. Artifact `10181725176` retained the failure.
- Run `34554734499` reached seed ingestion and failed the 98% volume-presence
  gate at 6,097/6,386 rows. Preserving numeric zero was a valid transport fix,
  but the subsequent run proved it did not explain the missing 289 values.
- Run `34556057392` failed the same production seed gate after zero/missing were
  separated. It established no market session, historical performance, or
  full-system pass.

The current implementation must not reinterpret those failures as historical
evidence. Its first action is an inexpensive source/warmup preflight; the full
physical replay starts only when that authority passes.

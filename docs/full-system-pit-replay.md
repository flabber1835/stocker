# Full-system historical PIT replay

Owner authorization: 2026-09-11. Continue the market laboratory with the full
broad historical universe, starting with the 2006 warmup and advancing daily
through July 2026. Instrument the complete application lifecycle. Deliver on
`codex/full-system-pit-replay`, based on verified main
`4bba6875b07288cf6ebc6a149b926075b1e41c60`, through a PR.

## Acceptance target

The reference is `compact_simplified_no_ramp`, certified by PR #352, run
`34544522249`, attempt 1, result commit
`2a1bd486241ae524eac395490b135cc79715e497`.

| Authority | Frozen value |
| --- | --- |
| Champion source commit | `f6ad7b543fbd20ffe363127d1120f4472caa9360` |
| Champion source SHA256 | `3fcf274dc5dba5b01ff3c637b62922f27c5dfe2e3b28e7f3a416e1bfeba09663` |
| Canonical dataset SHA256 | `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993` |
| Corpus package digest | `f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c` |
| Warmup start | 2006-01-03 |
| Measurement | 2006-07-31 through 2026-07-31 |
| Coverage | 5,176 observations; 5,032 measured sessions |
| Ending multiple | 56.265349336558316 |
| Reported CAGR | 22.32%; exact comparison uses the certified result |

The immutable reference is read only by the comparator. It cannot supply
decisions, orders, holdings, daily ranks or corrected strategy state to the
application. Reconstructed classification, terminal terms, carried marks and
the historical Treasury proxy retain their existing provenance disclosures.
The result establishes equivalence under the declared delivery schedule.

## Authority discovery

At the verified base the production selector is Simplified LD-RC v3, with
REC7, a -8% divergence threshold, 25 slots and 4% entries. The selected research
champion has REC8, a -8.5% threshold, 20 slots, 5% opening dollar intents,
Median-5 ranking, security-specific issuer grouping, dynamic peer breadth and
a compact native controller with its recovery ramp removed. PR #342 was
closed unmerged and does not supply a current-main champion integration.

The full historical acceptance gate must establish actual strategy identity
and semantic equivalence before allocating a twenty-year run. A label, an
environment variable or a reused research result cannot authorize a different
engine. The existing canonical book remains the single production book.
Any required champion port needs explicit source provenance, daily differential
evidence and its own durable-state schema. This research task confers no
deployment, account or merge authority.

The lab stages a disposable application source tree from the verified base.
It applies the retained V5/Median-5 implementation delta from PR #342 at
`c91e0f9625ed40a273936d000d915b382b46da08` (original base
`96f705c3b699ec283dbac7e93b973dba9769f038`), then the explicit champion
integration. The latter selects the canonical V5 book and the frozen compact
native/recovery transitions. It introduces a research-only runtime identity;
every source file and transformation is retained. Production files on this PR's
main-facing tree remain unchanged. The staged runtime must pass differential
and serialization gates before it can supply historical acceptance evidence.

## Information and time

The provider owns an immutable economic history and a versioned delivery
schedule. The application owns a separate PostgreSQL corpus containing only
received data. The comparator owns the reference history. Each observation
records effective time, publication time and receipt time independently.

Initial application data ends at the warmup boundary. Warmup is processed in
chronological order with dated metadata; the certified pre-measurement book,
pending intents and controller history must be reproduced by actual transitions.
The strategy cannot read the provider database or the final reference corpus.
Later provider versions may revise older rows. Earlier decisions retain their
original immutable input snapshots and cannot be recalculated in place.

The first schedule uses the real retained economic data. Reconstructed vendor
availability is explicit and frozen before running performance comparisons.
Split-driven historical rescaling is reconstructed causally. Unsupported raw
source inversions, missing authority and ambiguous identity produce named
preflight failures. Price, metadata and action disclosure conventions cannot be
changed to improve CAGR agreement. Appending future delivery events must leave
all earlier public observations and application evidence unchanged.

## Daily order

1. At the opening boundary, advance independent market and broker truth.
   Execute the previous close's durable intent under the actual execution
   contract, then observe fills and reconcile. The new close is still hidden.
2. Release the scheduled Sharadar observations after the session close.
3. Run default production ingestion, reconciliation, self-healing, publication
   and readiness through paginated Tables and Exporter ZIP/CSV transport.
4. Pin the resulting publication and capture the exact strategy-visible inputs.
   Compare the entire required canonical state against the independent oracle.
5. Advance the selected canonical strategy exactly once, persist its state,
   construct the next-session execution plan and retain its commitment.
6. Compare daily ranks, admissions, holdings, weights, cash, receivables,
   controller decisions and scalar NAV with the frozen reference.
7. Record operational health, backup authority, resource use and the committed
   progress/checkpoint receipt. Continue from durable application state.

Production data failures retain the documented permissions for pending orders,
new decisions and read-only recovery. Readiness and validation results are never
injected. Invalid data cannot quietly consume a trading session.

## Existing components

Reuse `research/sharadar_replay` for transport contracts and independent corpus
checks; `tests/internal_state` for the real application lifecycle and physical
PostgreSQL; and `tests/support/alpaca_simulator.py` for broker semantics.
Production imports no research harness. The simulator exposes no real brokerage
credentials. Provider and broker truth survive application restart and restore.

Physical WAL archival uses `scripts/sentinel-archive-wal.sh`, verified base
backups, checksummed WAL and the real runtime backup guard. Market time and the
physical PostgreSQL service clock remain distinct. Recovery checkpoints include
populated strategy, command and corpus state. Timeline changes retain the
production takeover fence. Fault scenarios have explicit recovery deadlines.

## Instrumentation and evidence

Every event has a monotonically increasing sequence, simulated UTC time,
session, phase, input commitment, before/after state commitments, outcomes,
invariant results and an append-only hash-chain link. Large input/state payloads
are content addressed. Hash-only evidence is insufficient unless the referenced
payload is retained and independently verifiable. Event names and required
boundaries are code-owned; missing instrumentation fails acceptance.

Retain provider requests/responses, completeness and revision identities;
database publication, row changes and blockers; all strategy/controller state;
plans, order requests/responses and fills; cash, positions and reconciliation;
environment preflight; backup/restore/restart events; process errors; and resource
measurements. Secrets are excluded by explicit field selection at capture.

An event is complete only after all required independent invariants pass.
The first failure records expected/actual values and their source references.
An unexpected exception, timeout, skipped boundary, missing artifact or stale
run directory is a failed run. Resume verifies the source/config/schedule,
last durable checkpoint and complete evidence prefix. Retrying an event must
preserve command identity and cannot erase its first failure.

Per-session comparison is required even when final headline metrics agree.
Discrete decisions and identities compare exactly. Numerical tolerances are
inherited from the reference and declared per field; they cannot widen during
the experiment. Final canonical corpus fields must reconcile independently.
Broker account NAV is reconciled separately for execution, rounding, fees and
capital flows. It cannot substitute for the certified scalar strategy NAV.

## Execution and resource budget

Run narrow local contract/falsifier tests, then the composed PostgreSQL smoke
replay in GitHub Actions. Validate full-source conversion and benchmark the
first historical segment before the full run. Publish measured throughput and
an ETA. Use bounded-memory streaming and content-addressed incremental evidence;
do not rebuild or copy the full twenty-year corpus on every day. Long jobs retain
checkpoints and progress suitable for continuation on GitHub.

The twenty-year run requires all prerequisites to pass and an explicit launch
manifest binding its exact sources. Research and system verdicts are separate
from workflow publication success. Partial output always records the failed
gate and actual completed coverage. A full-system PASS requires all 5,176
observations, every required boundary and the complete reference comparison.

## Initial implementation and launch

The first implementation runs default seed and daily ingestion against the
Tables and Exporter service backed by a private SQLite index. A separate process
hosts the Alpaca wire simulator. Application data, durable plans, execution and
reconciliation use a real disposable PostgreSQL cluster. The source-pinned
champion controller and canonical book passed 52 targeted local tests, including
12,000 native/recovery transitions, serialization, causal provider delivery,
pagination, retained-evidence tampering and actual adapter fills. Physical
PostgreSQL validation runs in GitHub Actions.

The first forty closes use a research bootstrap SQL loader because the package
starts in January 2006 and cannot supply a pre-2006 SPY tail. This loader permits
only the available, published prefix, and the ordinary loader takes over at
close 41. The canonical controller continues to report unavailable evidence
according to its own rules. No comparison tolerance or expected reference value
is changed to accommodate that difference: an observed discrepancy stops the
run and is retained for investigation. No securities may be held before the
formation window exists.

`research/full_system_pit/LAUNCH.json` records the requested full schedule. The
first launch stops at the first ingestion, readiness, economics, persistence,
execution or reference discrepancy. It has not established historical
equivalence. The independent comparison includes observations, opening and
closing equity, cash, held identities, allocation, controller reasons and scalar
NAV. The final gates require complete canonical bar reconciliation, populated
physical backup/restore, retained takeover fencing, and per-day instrumentation
coverage. Broker NAV is recorded separately.

Regular database restarts verify durable application state. Full state
checkpoints are retained every 63 sessions; intervening published inputs and
economic states are retained for reconstruction. Cross-job continuation and
additional adversarial delivery schedules remain follow-up work; a CI timeout
must remain incomplete and cannot receive a full-system PASS.

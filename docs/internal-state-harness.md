# Integrated internal-state lifecycle harness

Issue: [#348](https://github.com/flabber1835/stocker/issues/348).
Implementation base: `86580bdd19232b443ba80f3aefb2ea53dbc61318`.

## Contract

The first acceptance milestone composes real Sharadar ingestion/publication,
canonical Wealth Core and Sentinel state, production plan construction, Alpaca
wire execution/reconciliation, environment preflight and physical PostgreSQL
backup/restore in one disposable lifecycle. The current production paper
strategy selector supplies the configuration and source identity, including
Concordance witness and Simplified LD-RC state. Existing economics, configuration,
golden fixtures, account capabilities and production authority remain authoritative.

The implementation lives in `tests/internal_state/` with a CLI under `tools/`.
Production never imports the harness. The existing Sharadar provider/oracle,
Alpaca simulator and production WAL archive command are reused. The existing
component suites and physical backup probes remain acceptance requirements.

## Ownership and composition

| State | Owner | Observed production seam |
| --- | --- | --- |
| Effective environment | Host configuration | `scripts.sentinel_env.load` and `validate` |
| Provider truth and delivered observations | Sharadar replay provider | Default `ingest.daily`, publication pin and readiness |
| Strategy state and recent-leadership witness | Canonical Wealth Core/Sentinel | `load_published_session`, `advance_and_persist`, `catch_up` |
| Current economic intent | Production decision/execution | `build_execution_plan`, plan adoption, `execute_session` |
| Broker truth | Existing Alpaca wire simulator | Existing adapter HTTP provider, reconciliation and cash ingestion |
| Durable application state | Isolated PostgreSQL cluster | Real SQL transactions, fresh connections and process termination |
| Backup media | Test-owned filesystem and physical PostgreSQL | Production archive command, backup runtime guard, `pg_basebackup`, `pg_verifybackup`, WAL recovery |

One explicit market clock controls provider observations and broker sessions.
The broker lives in a separate process and survives application death and
database restore. A broker identity resolver maps the simulator's symbols to the
same permanent IDs published by Sharadar. Each adapter has its own HTTP transport.
A private inherited pipe serializes access to the broker process; no simulator
listener or real provider endpoint is opened.

The small provider bootstrap uses the replay harness's explicitly non-certifying
seed seam. Daily ingestion retains the default production source callable and
its actual validation. Fresh strategy features use production prospective
warm-up; historical witness observations are never manufactured. Decisions
consume the dated publication actually available at that step. Captured inputs
remain immutable across subsequent corrections.

The application assembly uses canonical state, decision and execution APIs.
Deployment-level paper/GO entry points retain their certification/authority
refusals and their existing dedicated suites. A synthetic fixture confers no NAS,
historical-data or broker-capability certification. Existing unsupported broker
recovery states have explicitly named halt expectations.

## Independent invariants

Check invariants after every successful action and every expected refusal:

- Slots, episodes, reservations and pending entries agree; occupied shares are
  positive and rolling feed series stay inside the 127-session restart window.
- Shadow cash and shares reconcile to ledger deltas; broker cash and positions
  reconcile to the simulator's independent fill/capital history. Broker numeric
  values use exact Decimal arithmetic. Synthetic shadow float accounting uses
  absolute tolerance `1e-7`; state hashes and logical JSON compare exactly.
- Each session advances exactly once. Controller, witness, cooldown and pending
  state survive restart; prior state is immutable.
- Commands retain identity and immutable economics; filled amounts and owned
  economic effects are idempotent across repeated observations.
- Publication versions and provenance are coherent. An interrupted or invalid
  generation cannot authorize a decision from a mixed reader view.
- Failed env, backup and current-authority checks fence the appropriate durable
  or broker effects. Read-only recovery retains its documented availability.
- Broker faults and external capital leave canonical strategy state unchanged
  when strategy inputs are identical.
- After correct evidence becomes available, each scenario either reaches its
  declared recovery state within its attempt budget or retains its exact
  contractually required blocking state.

Independent assertions read facts and explicit event history. Differential
replay uses a second invocation of the canonical kernel with captured inputs;
it establishes restart/input equivalence, not an independent strategy algorithm.
Every major new invariant has an explicit falsifying mutation.

## Physical recovery and clocks

Each lifecycle owns a unique temporary PostgreSQL data directory, port and media
root. Physical commands use the same installed PostgreSQL binaries. The production
archive command creates real checksummed WAL objects. Only backup path constants
are redirected to those owned directories; backup policy and SQL remain real.
The strict runtime backup flag is enabled before production lifecycle actions.

Initial provisioning creates a verified restore horizon. Subsequent checkpoints
contain populated trading state. Restore verifies the physical base, replays WAL
to the declared point, promotes the isolated cluster and verifies application
semantics through fresh SQL connections. Broker history retains later events.
Timeline changes require a fresh complete backup horizon before further mutation.
The production private-media permission and timeline scripts run as companion
gates on their real Docker compositions.

Market-clock changes are explicit actions. PostgreSQL archiver health uses its
real service clock; readiness waits are bounded observations of an external
process. Replay expectations never depend on an absolute wall-clock timestamp,
port, temporary pathname, PostgreSQL system identifier or random broker UUID.

## Scenarios, generation and replay

The initial catalogue covers a populated happy lifecycle, duplicate execution,
response loss after broker acceptance, death before acknowledgement persistence,
partial-fill/cancel races, cash changes, malformed startup, interrupted data
publication and correction, media loss after preparation, same-size WAL
corruption, stale populated backup restore, corrupted state commitments, competing
writers and interrupted multi-session catch-up.

Generated action sequences use a local fixed-seed RNG, causal preconditions and
boundary-biased faults. A schema-versioned trace records the initial fixture,
profile, seed and ordered actions. Every failure retains the original trace,
first failed invariant, action index, expected/actual facts, broker/provider
transcripts, sanitized snapshots, runtime/source identity and replay command.
Bounded deterministic reduction preserves the same invariant and rejects invalid
causal candidates. Reduction errors never replace or hide the original failure.
Confirmed defects become permanent catalogue scenarios.

## Acceptance gates

The integrated CI workflow runs on PR heads and synthetic merge trees. Its report
binds Git SHA/tree, actual source digests, strategy configuration, schema,
dependency locks, interpreter/PostgreSQL versions, complete test identities and
scenario coverage. Missing prerequisites, setup errors, required skips, empty
collection, missing catalogue members, unexpected failures and expired budgets
fail acceptance. A stale output directory cannot supply a prior PASS.

PR campaigns start with 14 named scenarios in both broker profiles and 16 seeds
(44 traces). Each seed has an
explicit bounded action list. A manual full campaign starts at 128 seeds and is
sharded; its budget is declared before execution. Progress identifies the current
scenario/action and completed counts. CI retains original and reduced failures.

Full acceptance includes the integrated lifecycle suite; the existing Alpaca
runner and mutation gate; all Sharadar replay scenarios and evidence verification;
backup fault tests and all three physical scripts; host env/mutation tests; and
the existing Sentinel safety matrix, operator tests and supported repository test
suites. Existing documented historical golden exclusions remain individually
identified in evidence; no golden value is re-pinned by this work. Component
success alone does not satisfy the integrated lifecycle milestone.

## Commands and current verification status

Install the existing locked runtime and test dependencies and provide local
PostgreSQL server, base-backup and verification binaries. The lab owns its database
and backup directories; it does not accept a production DSN.

```sh
PYTHONPATH=shared python -m pytest tests/internal_state -q
PYTHONPATH=shared python tools/internal_state_harness.py --output artifacts/state
PYTHONPATH=shared python tools/internal_state_harness.py --seeds 128 --output artifacts/state-large
PYTHONPATH=shared python tools/internal_state_harness.py --replay FAILURE/trace.json --minimize --output artifacts/replay
PYTHONPATH=shared python tools/internal_state_full_suite.py
```

CI applies four deterministic shards to both the exact PR head and synthetic
merge. The full-suite evidence plugin records every selected, deselected, passed,
failed and skipped node. Unexpected skips, incomplete accounting, empty collection
and nonzero pytest exits fail the gate. The three existing historical Wealth Core
exclusions are enumerated in `tools/internal_state_full_suite.py`.

The local environment can exercise the kernel, plan assembly, real application
SIGKILL, private broker process, replay reduction and oracle falsifiers. It lacks
PostgreSQL binaries. Physical restore and the integrated campaigns therefore
remain unverified until CI runs; their presence in the catalogue is not a PASS.

The multi-session catch-up case specifically checks a suspected contract gap on
the implementation base: catch-up commits an intermediate cursor/state while the
old plan remains current, but restart validation requires that cursor to equal
the prior plan's decision session. The scenario must prove validated continuation
and equality with uninterrupted replay. A commitment refusal fails that scenario;
it is not treated as successful recovery. This harness changes no production
commitment guard, strategy authority or observability-table ownership.

The first full local run also found two stale test assumptions: an emergency
wrapper fixture required the container-only `/work/repo` layout, and one image
test expected the retired second runtime. Those tests now use an isolated copied
script fixture and the current single-runtime contract. Production code and
strategy economics are unchanged.

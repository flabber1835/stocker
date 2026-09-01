# Production trader and certification separation

**Decision status:** accepted; legacy platform removal in progress.

The production trader contains one deterministic session transition and the
operational code needed to run it safely. Full historical replay is a separate
certification concern. Certification imports the production transition; it
does not implement another historical portfolio.

## Target boundary

Production owns:

- feature-only warm-up;
- one canonical `advance_session(prior, published, ...)` transition;
- missed-session catch-up of the persisted, path-dependent production state;
- one current execution plan after catch-up; and
- controller, reconciliation, execution, recovery, and broker safety.

Production coherence is deliberately scoped to an explicit operational causal
closure, not to every retained historical row.  Its session boundary is the
earliest of (a) the source-owned preferred Wealth Core history margin, (b) the
persisted catch-up cursor, and (c) one predecessor session needed to establish
the split/action boundary.  The preferred margin is currently 252 XNYS
sessions, which exceeds the engine-owned 127-close minimum.  Controller,
breadth, and portfolio history older than that boundary is consumed only from
the content-addressed durable production state.

The closure is economic as well as temporal.  Unpublished price-only evidence
strictly before the boundary is historical-only when its security is absent
from all live state and execution dependencies.  By contrast, an unpublished
split, dividend, terminal, or identity fact for a current-universe security,
path-dependent state anchor, target, command, or expected holding remains
production-blocking regardless of its date.  Current universe snapshots,
current-window price/sensor rows, missed-session inputs, the published frontier,
and every execution/reconciliation identity are always blocking.  Candidate
rows remain invisible under the publication predicate in either class.

Certification owns:

- the immutable point-in-time corpus and its publication identity;
- repeated historical calls to the exact production `advance_session`;
- transition, restart, and one-session equivalence checks;
- state and decision hash verification;
- performance, benchmark, CAGR, and drawdown measurement; and
- experiments and golden scenarios that have no production authority.

Certification coherence remains corpus-wide.  A historical-only quarantine
that production may safely route around is still unresolved evidence and makes
full retained-history certification refuse until a covering retry publishes or
supersedes it.

The production image contains no HTTP backtest service, historical portfolio
database, benchmark calculator, experiment mode, replay-progress state, or
historical replay persistence. Certification output cannot authorize broker
access or mutate the production book.

## Preserved evidence boundary

The pre-separation strict-PIT work remains preserved at
`research/backtester@7f12174273dfa071a25614d2c4a1be8ebfdfbc3a`. Its
certified corpora, results, fixtures, and replay environment remain evidence;
they are not rewritten to fit this architecture.

Production authority accepts historical expected-hash evidence only when its
producer digest and complete canonical-loader bundle exactly match the bytes at
that preserved revision. The authority-evidence producer and offline
certificate issuer each carry and enforce that immutable digest manifest. Both
trust boundaries also require the finalized external manifest commit, test
image source revision, and baseline-engine source revision to equal the
preserved revision. A syntactically valid digest or a loader bundle consistent
with its own claimed contents is not an anchor and must fail closed.

The separation starts from `main` commit
`670b3fcc09f8c76e37f925b63783826ce8a1fdcc`. Historical evidence must always
record both its corpus identity and the production source revision whose
transition it imported.

## Separation gates

1. Preserve the strict-PIT evidence named above.
2. Extract `sentinel.core.kernel.advance_session` without changing its input,
   output, event order, state envelope, or economics.
3. Route production persistence, forward-chain certification, and differential
   certification through that function.
4. Prove exact one-session, historical-chain, and serialize/restart equivalence.
5. Move certification runners, metrics, benchmarks, fixtures, experiments,
   and replay infrastructure behind a separate package and image boundary.
   This gate is deferred until the standalone certification system is built.
6. Delete `services/backtester`, `services/bt-engine`, `services/bt-data`, and
   `docker-compose.backtest.yml` from the trader. The immutable
   `research/backtester` pin is the recovery source while gate 5 is deferred.
   `main` does not provide full historical replay during that interval.
7. Define an economic source manifest that includes the canonical kernel and
   its shared state model, excludes certification-only files, and re-certify
   that identity before production is deployed.

Each gate is reviewable and fail-closed. The preserved strict-PIT commit is the
accepted evidence boundary for deleting the legacy services before gate 5.
There is no production state migration in this separation: the
trader has not been deployed, so its first persisted envelope is created with
the corrected source identity.

## Invariants

- Warm-up updates feature history only. It creates no positions, peaks, holding
  ages, reviews, cooldowns, ledger events, or controller history.
- Catch-up advances every missed exchange session against the real persisted
  state, commits state and cursor atomically, and emits only the newest current
  plan.
- Production and certification import one transition implementation.
- Historical replay has no broker import, execution authority, or production
  persistence capability.
- Certification-only source changes do not change the final production economic
  identity after gate 7.

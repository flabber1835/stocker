# Current-window production inputs with retained ownership

## Decision

Promote the stateful snapshot approach tested in research PR #460. The selected
production identity explicitly names `CURRENT_WINDOW_V1`; other research and
historical identities retain their existing semantics. Sharadar remains the
source, Wealth Core remains broker-independent, and the same canonical book,
controller and execution membrane retain ownership of their existing duties.

Each decision uses the current 300-session published window for candidate
features. Previous decisions, holdings, cash, pending instructions, episode
peaks, ages, review flags, cooldowns and controller memory are retained. A newer
source observation may correct old candidate prices or metadata without requiring
portfolio reconstruction. Numerical feature accumulators are replaceable input
state; five-session ranking memory is retained strategy state.

The selected mode now uses [bounded book formation](current-window-formation.md):
299 feature-only sessions followed by 126 historical ownership/controller
transitions, then the current decision. Each decision still sees only its own
300-session slice. This supersedes PR #461's cash-only startup; capital remains
$50,000 and there is no capital search. An existing
operational book with a different strategy/source identity is never silently
adopted. The NAS has no admitted operational book; failed preparation records
remain intact.

## Acquisition and source quality

Keep complete bounded acquisition, stable-generation verification, immutable
publication, unique native identities, exact market-session and benchmark axes,
normalization and population/domain checks. The new operational coverage policy
records missing expected security rows instead of requiring every listing to
print on every session. A missing candidate lacks the 127 consecutive closes
needed for entry. Recovery follows automatically when the current snapshot has
enough valid observations. No ticker-specific missing-row exception is needed.

The minimum observed share is 99% of expected common-equity listings on each
session. This distinguishes isolated omissions from a partial export, alongside
the existing minimum-population and price-domain checks. Coverage reports retain
the missing counts and bounded identity samples; no prices are synthesized.

Empty sessions, material population loss, conflicting identities, unresolved
price domains and unsupported action economics still refuse. Publication success
does not imply that all holdings can be valued or that execution is authorized.
Legacy full-history verification retains its strict coverage contract.

## Daily transition and price bases

Recompute candidate signal facts directly from the current window, using the
prototype's canonical momentum, recent-return, volatility and liquidity formulas.
Keep only the current facts required by the pure transition in its input archive;
do not embed every provider row a second time. Refresh the bounded price histories
needed by held/pending securities and the controller's retained witness. Preserve
absolute market indices so controller memories and prices remain aligned.

The owned signal-price basis remains anchored to retained state. A held or pending
identity must have a valid current-publication bridge to its retained anchor;
missing or revised economic anchor evidence refuses before mutation. Applied
split/dividend and identity facts for live dependencies remain protected. Past
unheld prices, volumes, reference-only actions and metadata need not equal the
previous snapshot. Uniform source rebases must preserve owned drawdown and shares.
Missing current held marks remain missing: canonical valuation blocks admissions,
never fabricates cash, transfers identity or writes off the position.
If a missing price also belongs to the controller's retained leadership basket,
the existing unresolved-return guard refuses the entire transition, leaving the
last committed state intact. This change does not relax that controller contract
or guarantee uninterrupted trading through missing ownership/sensor evidence.

Every current-window input is bound to the selected policy, source snapshot,
decision session and prior state. Existing writer locks, publication pins,
checkpoint authentication, atomic session/input/cursor commits and lost-reply
recovery remain mandatory. Restart loads the committed book and does not replay
its history. Missed-session recovery retains its separate dated-source contract.

## Acceptance

The affected Stage 1 requirements and subsequent independent economic/recovery
acceptance are recorded in [current-window-stage-one.md](current-window-stage-one.md).

Run the observed FJDI/FJDIU condition through actual source capture, publication,
first decision, daily continuation and restart using real PostgreSQL and local
provider fixtures. Include unrelated corrected history, disappearing/reappearing
candidates, held gaps, splits/rebases, duplicate identities, session/benchmark
outages, population loss, corrupt input bindings and lost commit acknowledgement.
Compare canonical state and orders with a controlled clean input, and deliberately
break the new isolation and binding checks to verify their falsifiers. Production
code must not import research code. No NAS, account or deployment approval is
implied by these local tests.

Local acceptance on 2026-09-30 passed all 12 new PostgreSQL integration cases,
including the observed anomaly and a renamed equivalent, source-policy replacement
before GO, split/rebase continuity, lost commit acknowledgement, and fresh-book
paper-plan preparation with a simulated broker. The policy/economic/GO test group
passed 230 cases; automation/authority compatibility passed 196; publication and
paper-input regressions passed 64. Eight deliberate guard mutations were detected.
These are functional results from local fixtures, not a full NAS replay or a claim
that the new source identity has already completed GitHub certification.

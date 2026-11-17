# From hindsight actions to observable signals

## Decision and scope, before implementation

The owner requested signal research starting from the ideal hindsight decisions
and asking how the retained dataset can approximate them. Continue research PR
#597 on `codex/fractional-exposure-oracle`, clean head
`6b360241b900458a4232a883b189d2127e0233f9`. Fetched authoritative main is
`69b4a78a25610bf4aaee27eb4956a0611d26d124`, an ancestor. Delivery is local Git and
the connected GitHub PR; no merge or production installation.

Reuse the authenticated 4,035-close fractional Core snapshot through 2022-08-09,
binding `b21a537f35de5a8aeee2303a97949dde5fe0a925516cd065fc133d4b823942ad`, and
the completed closest-decision 25–30% target oracle in
`.codex-tmp/sentinel-target-cagr-20261116/run-004`. The primary hindsight anchor
is that existing target, not a newly selected favorable oracle. No Core book or
session is advanced. The stopped replay, source, data and checkpoints remain
read-only. This study does not fit or promote another trading controller.

The prior target changes 22 decisions, predominantly brief full-to-zero exits;
it does not alter the recovery-wait decisions. Do not assume that improving
recovery is therefore the principal way to approximate this particular target.
Describe what its changed actions actually capture first.

## 1. Anatomy of the ideal

Reconcile every changed episode, including the following rejoin overnight, into
intraday opportunity, overnight opportunity and transaction cost. The first
overnight after the decision belongs to the old position and cannot be avoided
by a next-open order. Split the scalar accountant into weighted gap and intraday
factors, retaining an explicit residual for its unchanged-allocation convention.
The pieces must sum to the target's audited incremental log wealth.

Report directions, duration, concentration by period, original Sentinel state,
healthy/impaired evidence, and causal feature values at the actual decision
close. Full-history percentiles are descriptive only. Do not train a classifier
on a slice of this full-period optimized path: its labels incorporate future
evaluation outcomes and reflect a global minimal-change constraint.

## 2. Recover observations, without regenerating Core

Inventory checkpoint files under the protected fractional replay's four retained
run directories. A checkpoint is eligible only when its content-addressed file
hash, canonical serialized state hash, cursor, and daily state commitment match
the authenticated common tape. Also check its committed daily prefix against
the common tape's exact bytes. Mismatched historical runs are excluded and
counted, never silently combined.

Extract only persisted time-local observations and append-only trailing histories:

- Exact checkpoint-close observation: damaged/green breadth, drawdown, returns,
  damage acceleration, SPY regime, stops, leadership returns and held-stock
  breadth statistics.
- Six stored damaged-breadth values mapped to their preceding session closes.
- Forty-one stored leadership NAV values mapped to their original session
  closes; overlap must agree. Compare the parallel stored Core NAV history to
  the authenticated daily tape as an independent time-alignment check.
- Stop counts in the explicitly retained twenty-session controller window.

A future checkpoint may preserve a past observation; its terminal observation
cannot be assigned backward. No forward filling, interpolating, zero imputation,
or retroactive use of its then-current holdings. Retain the original observation
date and the later preservation checkpoint separately. Fail on conflicting
overlaps. Missing values remain missing. Do not deserialize/restore the replay,
run a Core transition, or reconstruct another holdings book.

Saved histories may recover additional daily leadership signals. Raw green
breadth and cross-sectional holding features may remain sparse. Measure actual
coverage before deciding what can be evaluated; missing historical coverage is
not a statement that production lacks the signal.

## 3. Dense bounded hindsight opportunities

The 22 sparse target changes are too few, especially its two entries, to be a
general training dataset. Separately construct local hindsight opportunity labels
for holding each allowed action (0/55/100) for 1, 5 or 20 sessions, then rejoining
Sentinel at the next open. Include the rejoin overnight and both modeled costs.
Each label ends at close t+h+1 for a decision at t; its full outcome must lie
inside a model's training boundary. These are local opportunity diagnostics,
not a globally optimal path or another 25% CAGR claim.

Two fixed prediction questions are evaluated at each horizon:

1. When Sentinel wants 100%, would a temporary exit to zero improve relative
   ending wealth by at least 1% after costs?
2. When Sentinel wants zero, would a temporary entry to 100% do so?

Keep the 55% action in the hindsight surface and report which level is locally
best. Prediction/economic diagnostics use the fixed full-switch action above,
not a favorable action chosen afterward. Report overlap and clustered episodes;
overlapping opportunity gains cannot be summed into an achievable CAGR.

## 4. Causal approximation probes

Use fixed, interpretable probes rather than another controller search: regularized
logistic regression (C=1) and a depth-two classification tree with minimum leaf
25. No hyperparameter selection, neural network or search over controller rules.
Train on earlier data and freeze for the same five outer blocks starting in
2013/2015/2017/2019/2021. Purge every label whose rejoin outcome crosses the
training cutoff. Input scaling uses training observations only. Minimum fitting
support: 200 observations and 20 of each class; otherwise report unavailable.

Feature tiers are predeclared:

- Existing causal Core/SPY price, risk, cash, position-count and controller flags.
- Additional current/past gap-versus-intraday behavior, downside variation,
  momentum/volatility changes, Core/SPY relative behavior and recorded native
  controller memory. No account/execution data, ticker/date identifiers or
  future observations enter the feature vector.
- Recovered leadership 5/20/40-session returns relative to Core/SPY; absolute
  witness NAV is not a model input.
- Recovered damaged breadth and one-session change, plus leadership, where all
  required observations exist. Green breadth and holding dispersion remain
  descriptive if their coverage cannot support the fixed minimum sample size.

Coverage decision made before fitting any probes: the authenticated extraction
recovered leadership on all 4,035 dates, damaged breadth on 2,040, and exact
checkpoint-current observations on 391. Requiring a five-session damage change
would largely restrict this tier to checkpoint closes. Use one-session damage
change to evaluate the retained adjacent daily observations; keep the recorded
five-session change and green breadth in descriptive profiles. No missing value
is filled. This is an availability decision, not a choice based on outcomes.

Compare each added tier against the original tier on exactly the same eligible
training/test dates, so a sparse sample cannot masquerade as signal improvement.
Availability itself is not a predictive feature. Report eligible and excluded
counts, positive-event base rate, AUC, average precision, and precision/recall
at a threshold set from the training score's 90th percentile. Also report the
actual mean fixed-action economic gain/loss on flagged events, false alarms and
how often the signal captures the sparse oracle events. These event gains are
overlapping conditional diagnostics, not portfolio returns.

Report per-block stability and full-history descriptive feature profiles. The
history has been repeatedly inspected, so even later-block performance is not
untouched research evidence. A feature association or an isolated positive fold
does not certify a useful strategy. The result must distinguish measured signal
information, insufficient data, and hypotheses needing additional observations.

## Validation and delivery

Tests/fault injections cover checkpoint identity and prefix authentication,
history-date alignment, conflicting overlaps, preservation of missing data,
feature prefix causality and exclusion of account state, gap ownership, rejoin
costs, all three actions, purged outcome endpoints and training-only transforms.
Independently reconstruct local label economics from raw ledgers on sampled and
boundary cases; reconcile the existing target's full attribution in Decimal.

Use the existing pinned Python 3.12 research image, single BLAS thread, half a
CPU, 1 GiB, no network, read-only source/input/archive mounts and separate new
output. A runtime guard prohibits the canonical Core transition. Retain source
hashes, checkpoint coverage, dated features, ideal-event profiles, local labels,
frozen model probes, metrics and an offline report. No production source changes.

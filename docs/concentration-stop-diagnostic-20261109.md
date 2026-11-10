# Concentrated-position exit diagnostic

The owner authorized a quick numerical screen before implementing a Core variant.
Production Core, Sentinel, existing books, parameters and backtests remain intact.
This is an episode exit/opportunity-cost diagnostic, not a new strategy book,
portfolio simulation, CAGR/drawdown result or deployment proposal.

## Frozen experiment

Use original completed P00, 2,156 closes from 2018-01-02 to 2026-07-31.
Daily bytes: 170330724; SHA256
`9f1c682846167a1deafe4496aa4d2e6b803f5650d9f2265b34c691bae56067b2`.
Checkpoint SHA256:
`6942c696c752ee35d8a215a6ad138c71a69d9d8dd1337dcaa01519c3e141ea56`.
Its completed admission root is
`65637d23029e0817822c169e7d424e00cd75a01703cb22a6aeb1b3f69b390f83`.

Keep original causal episodes, entries, quantities, prices, NAV and future Core
decisions fixed. Activate the added rule once a recorded episode reaches 10%
of original Core NAV, twice the existing 5% entry allocation. Never use broker
weights, funded-account outcomes, Sentinel exposure or alternative NAV for this
signal. All other episodes are unchanged by construction.

Six arms: original 30% trailing stop, plus minimum percentage distances
`6%, 10%, 15%, 20%, 25%`. For an activated episode at close t:

```
distance = min(30%, max(minimum_distance, 1.5% / original_Core_NAV_weight))
candidate_value_floor = recorded_peak_position_value * (1 - distance)
stop_value_floor = max(previous_stop_value_floor, candidate_value_floor,
                       recorded_peak_position_value * 70%)
```

The 1.5% reference is derived from 5% entry weight times the existing 30% stop.
A minimum distance can override it: this is not a 1.5% NAV loss cap. For a 25%
position, minimum distances 10/15/20/25% allow 2.5/3.75/5/6.25% NAV to the price
threshold. Ratchet the absolute position-value floor, not percentage-distance
memory; the floor never decreases. Activation remains armed for that episode.
This one-dimensional screen and the fixed 10% activation are not tuned again
after outcomes. A best result is only best in this small, previously observed
history, not an optimum or an unseen validation result.

## Input and price domain

Identity is original slot plus signal session, with security ID and entry date
verified. Source inventory contains 201 observed lineages and 17 that reach 10%.
All 17 are ordinary entries, without material cash mergers, conversions or
duplicate-SID ownership. AGNT has one pure 2:1 split with no cash; SNDK is an
ordinary December 2025 buy and is sold July 8, 2026. No eligible episode may be
silently excluded. A later conflicting input must refuse this fixed scope.

Do not compare RAW close directly with a split-adjusted peak. For these ordinary
lineages define the exact source share-unit multiplier
`U = initial_shares * entry_raw_open / entry_split_adjusted_price`.
Then current value is current shares times RAW close, and peak value is U times
the recorded canonical split-adjusted peak. Validate that their ratio agrees
with recorded own drawdown. This handles AGNT's pure split without inventing a
price rebase. Unsupported quantity changes or material terms refuse.

Evaluate an inclusive threshold at a recorded close and fill only at the next
source session's authenticated RAW open, with that opening's original share
quantity. Never fill at the threshold, at a preceding high or at the same close.
If the new floor is already breached when it activates, the sale is next open.
The original episode may instead close normally at that open; it cannot be
extended beyond its original exit. Missing next-open evidence refuses a claimed
early fill. An endpoint signal without a later open remains unexecuted.

## Endpoint comparison and ranking

For each candidate early exit, hold sale proceeds as zero-interest cash through
the same original episode exit, or the July 31 end mark if still open. Preserve
entitlement to source dividends accrued before or on the sale's ex-date/open;
forfeit only later accruals. Compare net sale proceeds plus eligible dividends
with original terminal stock proceeds/mark plus original dividends. Use the
existing 10bp exit cost; do not charge an extra original exit after early sale.
Common entry costs cancel. This arithmetic does not reinvest dividends or sale
cash into other episodes and does not model freed-slot replacements/re-entry.

Report every episode, first activation, source peak weight, new signal/open,
original endpoint, net terminal difference, dividends and fee difference, and
upside after early exit. Primary screen score: average net difference divided
by original Core NAV at the first 10% activation, among completed episodes.
That common per-episode denominator is fixed across candidates. Show raw dollars,
win/loss counts, median, source-exit date blocks (2018-20, 2021-23, 2024-26), and
leave-largest-beneficiary-out sensitivity. The sum/average normalized score is
not portfolio return. Mark the one open CRS episode separately, and distinguish
positions already held at the measurement anchor. No automatic adoption follows.
Rank all six arms, including the unchanged control; ties favor the larger stop
distance. If every alternative loses value, the original 30% stop is the winner
of this screen rather than a negative candidate being presented as an improvement.

## Execution, verification and delivery

Verified main base: `1e7f4b181fbcb998b3086833ab813c21b1c2ca8e`.
Deliver research-only code through a feature-branch PR. Reuse immutable legacy
transport `0bc38753ac1f85b31eb95f560720e6b037e892c5` and the admitted transport
reader from reconciliation source `553590ca197c55942aadeb690d5436abd49a35d1`.
Do not copy or merge either unmerged strategy research branch into main.

All stop-path calculations and outcome comparisons run in credential-free,
network-disabled GitHub-hosted containers; no canonical strategy imports,
engine transition, broker/database contact or local financial replay. Local work
is DATA/AST inspection, hashing, transport and already-recorded result analysis.
Authenticate original inputs and the exact runtime image before calculation;
keep inputs read-only, outputs private/encrypted, worker/reviewer stops explicit.

Require original 30% stop calibration against recorded original signal/sale dates
and prices, zero incremental control delta, all 17 eligible episodes covered,
source-unit coherence, no earlier-than-next-open fill, no decreasing floor and
correct ex-date entitlement. An independent process recomputes signals, fills,
terminal arithmetic, aggregates and ranking. Test missing opens, future prices,
split units, dividend ex-date sale, removed floor ratchet and altered input.
UNKNOWN/OOM/nonzero or failed review forbids a qualified numerical conclusion.

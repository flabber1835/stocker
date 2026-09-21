# Economic comparison: production, retained reference and SPY

The earlier large shortfall disappears when production receives reconstructed
reference classifications and documented corporate-action inputs. This is
encouraging evidence for the strategy over the tested period, conditional on
those economic assumptions. It does not validate the retained twenty-year
56.265349x result or establish strict point-in-time correctness.

## Matched results

Measurement is July 31, 2006 through December 22, 2008 (875 calendar days).
Books start with $100,000 on January 3 and form naturally. No reset at July 31
or at the continuation checkpoint. Each series uses its own July baseline.

| Series | Multiple | CAGR |
| --- | ---: | ---: |
| Current production strategy, aligned economic inputs | 1.347425x | 13.2551% |
| Retained research reference | 1.316499x | 12.1627% |
| SPY, retained dividend-adjusted factor series | 0.717087x | -12.9612% |

Current controlled NAV: $124,673.7213266215. July baseline:
$92,527.4166348230. Maximum measured drawdown: 20.5082%.

At the original question's September 2, 2008 anchor, the original replay was
0.948097x / -2.5158%. This aligned run is 1.341960x / 15.0981%, versus reference
1.311160x / 13.8275% and SPY 1.039909x / 1.8884%. The original numbers are the
user-supplied earlier snapshot; the other three were independently recomputed.
This experiment changes classification and action assumptions together; it
cannot attribute that entire improvement solely to classification.

## Formation, Core and controller attribution

Independent reading of the retained portfolio confirms January 3 cash
$100,000, first holdings July 6, and July 31 Core NAV $92,527.41663482304.
The new production run matches those dates and values to numerical precision.
Both Core NAV paths match through September 19, 2006. The first material NAV
difference is September 20: current is $2.10 higher, consistent with 105 AVL1
shares receiving $48 versus the reference's $47.98 carried mark. The reference
continues carrying AVL1 through October 2. Settlement/cash/slot timing then
changes subsequent holdings and sizing. This is an accounting-path difference,
not proof of a ranking or strategy defect.

All 605 measured sessions have identical current/reference held allocations
and next-close desired allocations. The scalar account and Wealth Core are
separate: current standalone Core ends at $91,263.11 (0.986336x, -0.5727% CAGR);
reference Core ends at $86,072.70 (0.930240x, -2.9734%). The exposure controller
accounts for the controlled strategies' substantially better result during the
crash. The remaining difference between the two controlled paths is not a
difference in their observed allocation schedule.

Final Core NAV differs by $5,190.41. On the same July dollar baseline, the
controlled paths differ by $2,861.50. The largest endpoint composition gaps are
below; these reconcile asset values, not isolated causal profit contributions.

| Holding | Current shares | Reference shares | Current minus reference value |
| --- | ---: | ---: | ---: |
| SQNM | 296 | 0 | +$5,884.48 |
| LCC | 0 | 628 | -$4,603.24 |
| DAL | 0 | 443 | -$4,540.75 |
| AFAM | 104 | 0 | +$4,527.12 |
| FDRY | 0 | 271 | -$4,514.86 |
| ESINQ | 50 | 0 | +$4,384.00 |

Current cash is $8,464.15 lower. Reference FDRY remains carried at $16.66;
current already recognized its $16.50 merger cash. Complete quantity/value
records are in [composition-differences.json](composition-differences.json).
A marginal P&L attribution of each changed admission or action timing was not
attempted; this was a bounded strategy check, not a new full backtest.

## Confirmed software blocker and next action

The second segment reached December 22, then refused December 23's BRL-to-TEVA
conversion with `MISSING_CONVERSION_SIGNAL_BASIS`. This is reproducible despite
complete economic terms for this scenario and a retained December 22 BRL
raw/signal anchor of 65.8/65.8. Barr has no December 23 quote.

At pinned production revision `624395dd04c48af7de3a8930cfd586ca2cc81245`:

- [adapter.py:937](https://github.com/flabber1835/stocker/blob/624395dd04c48af7de3a8930cfd586ca2cc81245/shared/stock_strategy_shared/wealth_core/adapter.py#L937)
  passes a source scale only from a current predecessor bar, yielding None.
- [terminal.py:402](https://github.com/flabber1835/stocker/blob/624395dd04c48af7de3a8930cfd586ca2cc81245/shared/stock_strategy_shared/wealth_core/terminal.py#L402)
  correctly refuses a conversion without both signal bases.
- [shadow_observation.py:1509](https://github.com/flabber1835/stocker/blob/624395dd04c48af7de3a8930cfd586ca2cc81245/sentinel/shadow_observation.py#L1509)
  correctly refuses to report performance using unresolved Core equity.

The independent economic oracle is 70 x 0.6272 = 43.904 delivered shares:
43 TEVA ADSs, $2,793 contractual cash, and $37.80528 cash for the 0.904-share
fraction valued at the explicitly assumed prior TEVA close of $41.82. A direct
call to the unchanged terminal function with the retained source scale of one
returns exactly those quantities and cash within floating-point tolerance.
[The retained reproduction](probe-brl-result.json) distinguishes the failed
full session from that terminal-only counterfactual. No successful December 23
portfolio or return is claimed. BRL's new supplement was never applied to the
reported path.

Recommended next action: a separate, narrowly tested fix should pass verified
predecessor signal-basis evidence into conversion when its current quote is
absent. Test missing/stale/incompatible basis rejection and exact share/cash
conservation. Preserve the guard; do not insert a fake executable quote or
assume a scale of one generally. Then use a new, explicitly versioned replay
scenario to assess the fix and continue the economic comparison.

## Intentional differences and unresolved questions

The classifier reconstructs the historical reference's policy, including known
canonical classes and its reviewed unknown-security intervals. It is an
assumption-alignment experiment, not independent validation of that policy.
Original price data, production parameters, transaction-cost rules, guards and
source files remain unchanged. No NAS or broker access was used.

The current experiment recognizes documented merger consideration rather than
reproducing all legacy carried-price settlements. DRS, IKN and BUD1 cash is
recognized one session before documented completion under the retained-date
scenario convention; these affect held cash and replacement opportunities.
Other conventions include Falconbridge FX, same-session cash availability,
and unheld GSF price-basis translation. See the
[design and action notes](../../docs/economic-replay-60m.md) and
[supplement records](supplements.json). Do not promote these assumptions into
production settlement evidence. The BRL fractional-share approximation does
not affect any reported return because its session remained blocked.

Unresolved: full-period strategy performance; the causal split between each
classification/action-timing change; sensitivity to early cash recognition;
and reference missing-price assumptions outside the measured prefix. No new
confirmed strategy-selection defect was established by this run. The conversion
integration blocker is a software limitation, not evidence of failed alpha.

## Scope and checks

First segment: 701 sessions, January 3, 2006 through October 14, 2008; a
3,600-second deadline plus final checkpoint serialization. Second segment:
48 additional sessions through December 22, 2008. It was stopped at its saved
checkpoint at 02:43:42 UTC on September 21, about 29m37s into the authorized
additional hour, after confirming that input-only work could not clear the
blocker. The worker's original WAITING_FOR_EVIDENCE status and exit code 1
from the explicit process stop are retained, not relabeled COMPLETE.

- Targeted input tests: `python -B -m pytest -q -p no:cacheprovider research/economic_replay60/test_inputs.py` â€” 5 passed.
- Independent `research.economic_replay60.verify` over both segments â€” PASS:
  all 749 sessions, calendar continuity, own baselines, all multiples/CAGRs,
  SPY source-factor product, restart NAV continuity, unchanged source hashes,
  immutable applied supplements, checkpoint hash, and final portfolio valuation.
  Final Core raw-price/cash/receivable residual: -$0.000000000000223.
- `research.economic_replay60.reference_analysis` independently reads retained
  Git artifacts for formation, initial divergence, Core NAV and final quantities.
- Final `--verify-resume` â€” RESUME_VERIFIED, 749 sessions, without advancing.
- One full December 23 session reproduction plus direct terminal arithmetic
  counterfactual; no full rerun, fixture repin or guard relaxation.

Full checkpoint files remain in the local experiment directory; compact daily
traces, identities, statuses, pointers, blockers, supplements and checks are
retained here. [artifact-manifest.json](artifact-manifest.json) hashes these
machine-readable evidence files. It excludes this human-readable report.

Sources: production revision above; external harness
`9b60e2ab10035df49c51c1432f3a5d6379dd61a2`; retained reference
`2a1bd486241ae524eac395490b135cc79715e497`; original PIT dataset
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.
See [runner instructions](../../research/economic_replay60/README.md).

JSON evidence exports normalize CRLF to LF only; their parsed values are
unchanged. The artifact manifest retains the original export hashes and sizes
where normalization occurred. Original local artifacts were not rewritten.

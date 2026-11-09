# Fixed-entry staged-sizing diagnostic

The owner authorized a quick diagnostic of staged sizing after reviewing the
negative 10/20/30 stop study. The stopped control/VOL075 backtests remain stopped.
This is a separate GitHub-hosted DATA calculation on the already admitted
VOL075 prefix through September 30, 2022, not a new financial book or CAGR test.

## Fixed rule, declared before results

Use 20% of each original executed entry's all-in budget at the original entry
open, add 30% after the first valid owned close at least 10% above the original
entry, and add 50% after the first such close at least 20% above entry. This is
the illustrative 1%/2.5%/5% progression relative to a normal 5% entry, with the
actual original executed budget held fixed. Each gain gate triggers once. Fill
at the next available recorded raw open, even if the price gaps past or back
below the gate. Both additions may fill at the same open when both gates were
crossed. Do not add on the original exit date. Cancel unfilled additions at the
original exit/cutoff. Never execute at a threshold or at the signaling close.

Preserve original entry dates, 30% trailing stops, review/terminal exits and
cutoff marks. Keep all tranches through that original boundary. No averaging
down trigger, profit trimming, parameter sweep or use of future prices to
choose a fill. Use the same 153 supported entries as the previous diagnostic;
explicitly exclude its two stock-delivery lineages and separate open trades.

## Budget and accounting conventions

The budget is the original BUY cash outflow, including its recorded fee. Each
tranche spends its fraction of that budget: notional and buy fee scale together.
Scale ending share value and recorded proportional sell fees by the units
actually purchased at each observed opening price. Include recorded dividends
only for units bought before the ex-date. All observed dividend rights must be
resolved at this prefix; otherwise refuse rather than zero an unpaid right.
Dividend and unused-budget cash earn zero and are not reinvested.

Use fractional economic units for this quick screen, not broker shares. Report
starter/addition budgets too small to buy one whole share. A full canonical
portfolio experiment would be required to test whole-share feasibility, cash
competition, changed subsequent sizing, re-entry and actual CAGR/drawdown.

Report baseline/staged price profits, profits after fees/dividends, original
entry-budget-weighted differences, winner/loser retention, individual examples,
funding-stage counts and budget-session dollars committed versus left unused.
The latter measures capital tied to these original trade windows; it is not
portfolio cash exposure. Dollar sums normalize to the original $50,000 anchor
and are diagnostic sums, not a counterfactual ending NAV or recoverable CAGR.

## Verification and isolation

Reuse the hash-pinned prior journal/price readers and original 30% exit
calibration without modifying them. Reconcile the full-size comparator to
actual BUY/SELL/cash/dividend ledger values for every supported entry. Check
split-neutral units, strict next-open timing, no exit-day adds, dividend ex-date
eligibility, budgets, fees and capital-duration arithmetic with synthetic tests.
Local tests must not replay financial evidence; actual calculations are hosted.

Authenticate the immutable parent before parsing and keep it read-only. Export
only diagnostic files using authenticated encrypted transport. The receipt
must explicitly forbid financial continuation; output contains no Core book or
checkpoint. Existing financial workflows must not be triggered or resumed.

Local synthetic qualification passed 14 tests in 4.55 seconds with the canonical
import fence and workspace basetemp
`C:/GitHub/stocker/.codex-tmp/sizing-diagnostic-tests-1`. The targeted file is
`research/capital_risk/forecast_tests/test_core_entry_sizing_diagnostic.py`.
Changing strict next-open timing to permit a signaling-day fill makes its test
fail. Giving same-day additions ex-dividend entitlement makes its test fail.
The source-bound DATA probe, YAML trigger/group scope, Python AST and staged
whitespace checks precede publication. No real trade replay runs locally.

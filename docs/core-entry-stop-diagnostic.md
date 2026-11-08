# Exploratory 10/20/30 exit diagnostic

The owner requested a quick experiment while the fixed VOL075 and matched
control backtests continue unchanged. This is an exit-only diagnostic on the
existing admitted VOL075 history through September 30, 2022 (1,196 closes), not
a new portfolio, a complete Core variant, a classifier or a CAGR estimate.

## One fixed illustrative rule

Use a 10% trailing distance initially. Widen to 20% when the owned closing peak
is at least 10% above entry, and to 30% when that peak is at least 20% above entry.
These gain gates are illustrative, selected before examining results; there is
no grid search. The actual stop floor never decreases when the width increases.
Check the previous floor at each valid owned close before updating the peak and
floor. Use inclusive crossings. Arm from the first owned close, preserving the
original convention rather than inventing an entry-price or intraday stop.

Use the next available recorded raw opening price after a stop signal. If no
opening is observed before the original terminal exit/cutoff, retain that
recorded terminal/marked boundary and disclose the unfilled signal. A recorded
cash terminal can supersede a pending sell. Never assume execution at the stop
price, at the triggering close, or after the admitted cutoff.

## Scope and interpretation

Keep the actual measured entry dates and original entry notionals fixed. Keep
the original review/cash-terminal exit boundaries when no earlier stop fills.
Exclude stock-delivery lineages explicitly. Derive split-neutral per-entry price
ratios from actual held quantities and raw opening/closing marks, normalized by
the original BUY notional. Corporate cash exits remain their recorded value.
Use price returns only: do not imply dividend, fee, freed-cash, replacement,
re-entry, portfolio exposure or reinvestment accounting. Show open positions
separately. Sum/weight only as a fixed-entry diagnostic, never as recoverable
portfolio profit or CAGR.

Before admitting exploratory results, reproduce the original 30% stop's actual
exit dates for every supported recorded trailing-stop sale and show no earlier
baseline stop on other supported trades. Refuse aggregate conclusions on a
baseline discrepancy. Verify ratcheting, causal execution and cutoff limits.
Retain losses, clipped winners, untouched trades and coverage counts.

All actual replay arithmetic runs in a distinct GitHub-hosted DATA job, with no
canonical strategy/runtime imports, broker, production, PAPER/LIVE, new Core
book or financial checkpoint. The authenticated parent is read-only. The output
contains no financial book and has an explicit diagnostic-only receipt/status,
which the financial artifact-admission path must refuse. Preserve authenticated
encrypted transport. Unit tests use synthetic paths only. The existing full
backtests remain on their own immutable commits and noncancelling job groups.

Local qualification uses synthetic paths only: 14 targeted tests passed in
3.59 seconds via the import-fenced Python runner and workspace basetemp
`C:/GitHub/stocker/.codex-tmp/entry-stop-data-tests-2`. The file is
`research/capital_risk/forecast_tests/test_core_entry_stop_diagnostic.py`.
Removing the floor ratchet makes its regression fail; removing the hosted-only
replay boundary makes its regression fail before any real input can be read.
The fixed source/request/workflow probes and Python syntax are checked before
publication. Actual price-path calculations remain hosted and require the
recorded 30% exit calibration described above.

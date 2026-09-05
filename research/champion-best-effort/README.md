# Champion 20-year best-effort replay — UNCERTIFIED

User decision: proceed with the best-effort 20-year backtest with explicit assumptions and sensitivity checks. This research branch starts at terminal-lifecycle recovery commit 92e4411b1006ff36a38e162ccb7cfbab71e91b83. Champion profile strategy9-e3-research-champion-v1 and its eight frozen control parameters remain unchanged.

Measurement: 2006-07-31 through 2026-07-31, with full-machine warm-up from 2006-01-03. Input: the existing immutable canonical package, checked for integrity and source identity. Package verification is not full PIT certification.

## Scenarios

- baseline: unknown security types remain excluded; incomplete terminal consideration is assumed equal to the last observed prior raw price, adjusted for any same-session split. The claim is recognized on the event session and released to cash the following session.
- terminal_50: same scenario with 50% recovery of incomplete terminal claims.
- terminal_0: same scenario with zero recovery of incomplete terminal claims.
- unknown_inclusion: baseline terminal assumption; unknown security types may enter the price-eligible universe. This is an uncertainty stress test and may admit non-common instruments.

Authenticated exact terminal terms keep their existing valuation path. Missing ordinary leadership closes use a logged zero return; missing held closes use the existing prior-mark valuation and admission block. Execution retains the 10% trailing-volume capacity limit and pending-order deferral. Missing capacity authority and absent historical valuation marks remain explicit errors.

Every scenario retains daily NAV and allocation data, SPY comparison, full-window and trailing-window metrics, generated replay code, exact code and dataset identity, and a compressed assumption-event journal. All results are labeled NOT_CERTIFIED. Terminal haircut sums are nominal exposure totals, not estimates of the total return impact. Sensitivity outcomes are not error bounds. Existing strict certification machinery remains unchanged.

Run the GitHub Actions workflow champion-best-effort-20y.yml on this branch. Four scenarios execute independently and a final job compares completed outputs and reports failed or missing scenarios. Workflow artifacts have a 90-day retention period.

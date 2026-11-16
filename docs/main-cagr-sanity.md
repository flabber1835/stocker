# Fractional Wealth Core historical CAGR sanity run

Owner request, 2026-11-15: run locally and report month-end CAGR, wealth multiple
and maximum drawdown for the selected production strategy and SPY. This is an
economic sanity check, not a parameter search, broker replay or certification.
The verified production revision is
`566a36819d7aec0d9f64cebf281fc9c20c5e086b`. Workflow A uses an isolated feature
worktree, local Git commits/push and the connected GitHub PR channel.

## Production boundary

Import `production_strategy`, canonical `Formation`, current-window
`compile_rows`, `advance_session`, `SessionState` serialization and the production
shadow strategy accountant from the unchanged pinned production tree. The harness
owns file transport, a bounded 300-session input buffer, source commitments,
checkpoints and reporting. It owns no stock-selection or controller rule. A
read-only observer around the original `run_with_hashes` records its already
computed terminal results and counters; arguments and results are unchanged.
Tests compare observed and unobserved transitions. Retain per-episode terminal
audit, original assumptions and counters with every performance report.

The modeled account uses production Core/BIL accounting, its existing costs and
first-funded-open convention. It does not simulate protected-limit PAPER fills,
broker cash delays, deployment machinery or historical Alpaca/OpenFIGI capture.
No production state, database, account, archive or existing experiment changes.

## Owner-selected fractional Core experiment

The owner subsequently requested fractional **Wealth Core**, after explicitly
distinguishing the simulated reference book from Alpaca-reported account fills.
Assume all otherwise eligible securities support fractional purchases. This
assumption does not admit instruments excluded by the strategy's ordinary
classification, liquidity, or price rules. This is a new research economic
profile, not a claim that unchanged main already has fractional Core entries.

Reuse the canonical engine and state envelope in one isolated process. An
explicit research-only context selects `wealth-core-fractional-entry-research-v1`
and applies exact, source-checked transformations at the existing entry seams.
There is no second portfolio implementation. Preserve original source files and
restore all functions/profile values on context exit. Record original and
transformed function hashes and the overlay source in the run binding. The
profile changes the controller/configuration identity and persisted sizing
profile; research snapshots must refuse restoration by ordinary production.

Keep the existing 20-slot dollar reservation, priority, next-session opening
attempt, costs of 10 basis points per traded side, cash reserve, affordability,
invalid-market cancellations, holding rules and controller. Remove the
one-whole-share admission constraint. At the historical raw open calculate
`min(reserved dollars, available cash) / (price * (1 + cost))`, round quantities
down to the Core's existing twelve-decimal share precision, and verify the
booked cost fits both budgets. Preserve fractional entry quantities in the
episode, source lot, fill, ledger and restart. No fractional eligibility lookup,
broker minimum or dollar-order partial fill is synthesized.

Preserve source-backed corporate-action economic terms and refusal behavior,
including cash-in-lieu requirements. A conversion's informational initial-share
reference must retain its fraction rather than clamp it to one. The production
conversion allocator continues to determine actual delivered shares and cash.
Missing new action terms halt the run; eligibility does not imply missing terms.

Measure fractional Core plus the unchanged Sentinel scalar Core/defensive-sleeve
accounting. Export fills and month-end positions with fractional quantities.
This is an ideal historical fractional strategy simulation, not a replay of
Alpaca order transport or actual fills. The test set includes expensive entries,
budget and cash bounds, scaling, invalid opens, costs, splits, full exits,
checkpoint continuation, protection of the original profile and falsifiers.

## Fixed scenario and source

Start fresh with $50,000, 299 feature-only closes (2004-11-19 to 2006-01-27),
126 formation closes (2006-01-30 to 2006-07-28), and measurement from the
2006-07-31 close to 2026-07-31. The first funded open is 2006-08-01. There are
5,032 measurement closes. Formation returns do not count as deposits or measured
performance. Each decision sees its own trailing 300 sessions, never future bars.

Reuse the preserved canonical dataset
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
in recovered transport `c0a62a6bbb8b67f77a1fca34f5e836a36f90bdf67dd83e196ef3d3369a7925f6`
and prepared bundle `8424b034be9ae0caffd1dc0a8e728854e691bd375d87ddb1d8807453026d7fff`.
Verify the archive, member sizes/hashes, manifest commitment and calendar.
Keep the original classifications, four spinoff cash-proxy replacements,
complete terminal schedule and child entitlements. The already sourced Starent,
Xoom, Cornerstone and Vivint corrections may be imported as separately hashed
input overlays into this fresh scenario, after exact original-term matching and
verification of their retained source files. Their prior experiment checkpoint
references remain provenance only; no prior strategy state is adopted.

This is retained Sharadar research evidence with reconstructed classifications,
missing historical provider vintages and disclosed settlement, FX and fractional
cash assumptions. Preserve the original FAIL status for the FCEC/FSNMQ warmup
actions and PTIX/AVTI boundary diagnostics. Do not silently certify or erase them.
Unknown classes stay ineligible except for the frozen reviewed interval overlay.
The defensive sleeve retains the lagged Treasury proxy before BIL inception.
The corpus's original dividend fields retain their ordinary production accrual;
an immutable tape has no later publication corrections to synthesize.

## Measurement and continuation

Normalize strategy and SPY independently to their own July 31, 2006 close.
Multiple is current NAV divided by baseline. CAGR uses actual elapsed calendar
days / 365.2425, and is unavailable on the baseline date. Maximum drawdown is
the greatest peak-to-trough percentage loss over **all daily closes since that
baseline**, including intra-month troughs; display it as a nonnegative loss.
SPY is the retained total-return series. Also retain Core NAV, actual decisions,
holdings, cash, fills, valuation and terminal evidence for diagnosis.

Write daily JSONL, monthly JSONL/CSV and a readable monthly table. Publish a
content-addressed compressed checkpoint with the source/data identities, complete
canonical state, accounting state, peaks/drawdowns and committed output lengths.
The atomic pointer is the commit boundary. Resume validates every binding and
output prefix, preserves any uncommitted suffix separately and restores without
reforming the book. Reconstruct only the input buffer. Checkpoint formation,
month ends, bounded intervals, refusals and clean stops. A refusal never creates
a performance row for the failed session or skips it.

## Local execution and validation

Run one offline task-owned Docker container under WSL, with read-only source and
input mounts, one writable new output directory, no credentials, no production
volumes, no network, a read-only root, dropped capabilities, no-new-privileges,
bounded temporary storage, 2 GiB RAM/no additional swap and one CPU. Record the
actual container limits, exact image and production source hashes before replay.
Text-source verification normalizes CRLF to LF for portable Git checkouts;
binary inputs remain byte-exact. Harness bytes are also bound into each run.
An independent read of daily NAV must reproduce the final monthly metrics.

Targeted tests cover cumulative calendar CAGR, daily drawdown, window compiler
equivalence, exact source/input binding, terminal-overlay matching, audit
noninterference, checkpoint corruption and restart/report continuity. Deliberate
mutations must falsify new invariant guards. No production source or golden
fixture changes are part of this task. Any later input repair gets its own
documented immutable scenario and replays from before the changed event.

The test image receives the research adapter and its existing input translator
only for focused harness tests. Neither enters the production image.

This replay does not simulate `FRACTIONAL_MARKET_DAY_V1`. That execution policy
preserves the canonical book by design. Reported strategy NAV uses that book
and scalar exposure/cost accounting, not fractional broker-order fulfillment,
actual fills, eligibility fallback or account residual-cash performance.
Retained action corrections require at least one byte-authenticated primary
document per correction. Additional previously reviewed URLs without retained
bytes remain explicitly unverified corroboration in the provenance record.

## Running and reading the result

Mount the pinned source at `/source` read-only, the retained archive at
`/data/archive.zip`, prepared bundle at `/data/bundle`, and action research at
`/data/repairs`, all read-only. Mount a new output parent at `/output` writable.
Use Python 3.12 with `PYTHONPATH=/source:/source/shared` and no bytecode writes.
The local Python/dependency image is
`sha256:0b51f28b657f2e634fb8804bf3fb952b07261d40d295acaa6b9a2a9d78e0415a`;
its installed strategy source is not used. Import the mounted pinned source.

```sh
python -B -m research.main_cagr.run \
  --bundle /data/bundle --archive /data/archive.zip \
  --repair /data/repairs/starent-20091218/terminal-repair.json \
  --repair /data/repairs/xoom-20151112/terminal-repair.json \
  --repair /data/repairs/terminated-before-fill-20220722/terminal-repair.json \
  --repair /data/repairs/vivint-20230310/terminal-repair.json \
  --output /output/run-001 --max-transitions 150
```

The pilot stops after formation and August 2006. Reuse exactly the same inputs,
source and output with `--resume`, omitting `--max-transitions` for the remaining
history. Run only one writer. `status.json` distinguishes running, paused,
refused and complete states. A missing final `result.json` means the requested
history has not completed. Inspect `startup-refusal.json` if initialization
fails before the first canonical checkpoint.

Read `monthly.md` or `monthly.csv` for the requested table; `fills.jsonl` and
`positions.jsonl` retain quantities and holdings. All reported monthly metrics
are cumulative since the stated baseline. Validate independently with:

```sh
python -B -m research.main_cagr.verify /output/run-001
```

Use `--partial` for the pilot. The verifier recomputes all daily metrics from
emitted NAVs and checks the monthly exports and terminal-audit session axis.

## Targeted validation

In the pinned Python 3.12 image, using mounted source (so `SENTINEL_IN_IMAGE=0`):

```sh
python -B -m pytest \
  tests/sentinel/test_main_cagr.py \
  tests/sentinel/test_fractional_core_research.py \
  tests/sentinel/test_image_layout.py \
  tests/v5/test_v5.py::test_open_budget_uses_actual_price_cash_and_released_cushion \
  tests/v5/test_v5.py::test_close_admission_has_no_bound_quantity_and_open_reprices \
  -q -p no:cacheprovider
```

Result: **69 passed**. A deliberate upward-rounding replacement of
`affordable_quantity` failed all five independent budget-bound cases. A
replacement that ignored the resume binding failed the changed-binding
falsifier. Both mutations ran in separate disposable processes; source files
were unchanged. `git diff --check` also passed.

The local real-data pilot completed 299 warmup and 126 formation sessions,
then 24 measurement closes through August 31, 2006. Independent daily-NAV,
monthly-export and terminal-audit verification reported PASS (two monthly rows,
including the July 31 baseline). The first twenty formation purchases all had
fractional quantities. A separately loaded formation checkpoint restored the
same canonical state hash under the same research identity.

The August 31 cumulative row is strategy CAGR 3.8488%, multiple 1.00321049,
MaxDD 0.086432%; SPY CAGR 28.9491%, multiple 1.02181383, MaxDD 1.120738%.
These annualized one-month values do not establish a twenty-year result. The
continuation through July 2026 runs locally from that checkpoint and executes
the independent full-history verifier on successful completion.

## Prospective spin-off correction and checkpoint continuation

Owner instruction, 2026-11-15: fix the refused fractional backtest and proceed.
The original scenario completed 2,245 measurement sessions through 2015-06-30
and refused the 2015-07-01 BAX/BXLT distribution. The retained one-for-one
distribution has a reviewed $31.90 child opening price but no cash-in-lieu
price: the earlier whole-share holding did not require one. Fractional parent
ownership now creates a fractional child entitlement.

The [Baxalta information statement](https://www.sec.gov/Archives/edgar/data/1620546/000119312515244456/d59817dex991.htm)
documents aggregation and market sale of fractional entitlements, with net
proceeds distributed later. It does not establish the agent's realized price.
For this research sanity run, explicitly model that remainder at the already
retained child opening price, less the existing 10 basis point sale cost:
`31.90 * (1 - 10 / 10000) = 31.8681` per fractional share. Recognize it on the
distribution session, as with the existing child liquidation convention. This
is a modeled price and timing assumption, not an observed agent payment. Do not
change the one-for-one ratio, parent basis treatment, whole-child liquidation,
other cash-in-lieu terms, ordinary entry cash threshold or production code.

Apply only an explicit, hash-bound repair to that exact original typed event.
Bind the retained primary document and reject a changed event, missing evidence,
nonpositive price, different gross child price, or unsupported repair policy.
There is no general missing-price fallback. Other missing terms still refuse.

Continue in a new output directory. The original run, refusal, checkpoint and
all outputs remain read-only. Authenticate its exact predecessor binding and
checkpoint, canonical state hash and every committed output prefix before
copying those prefixes. A repair may take effect only strictly after that
checkpoint. Preserve the original formation plan, production source, strategy,
fractional overlay, package versions, original data and terminal corrections.
Only the reviewed harness update and prospective spin-off correction may differ.
Record old/new identities and checkpoint lineage; do not relabel old results.

The resumed checkpoint retains exactly the original canonical and accounting
state, including controller state, peaks, cash, holdings and measured count.
Future publications bind a new effective source identity containing the repair;
the original formation identity remains historical truth. Normal restarts of
the new scenario require its full new identity. Mount the corrected research
harness over the pinned original production tree, so later main changes cannot
enter this ongoing experiment. Qualify the refused session and restart before
launching the remainder with the same offline resource limits.

The retained primary bytes for this correction are the
[Baxter distribution announcement](https://investor.baxter.com/investors/events-and-news/news/press-release-details/2015/Baxters-Board-of-Directors-Approves-Separation-of-Baxalta-and-Declares-Special-Dividend-of-Baxalta-Stock/default.aspx),
SHA256 `b0f68c016b2dfbb0b66ad5d0ca7784edf56b4de4c208d51eeb0a8781904503e9`.
The original typed event hash is
`7ccf4676ab3f464d8d7777b92b26f4e4d2569a3ebf1dca31e2f901af68152d25`.
The correction document has SHA256
`e3a632116bb25807482065cb78c937c1178dd4f84ccf7d42514d583f025e2703`.
At the refused boundary the fractional entitlement is 0.501427006632 shares;
the modeled remainder proceeds are $15.9795259900492392.

With the original input arguments above, add
`--spinoff-repair /data/spinoff-repair/spinoff-repair.json`, select a new output,
and use `--recover-from /predecessor --max-transitions 2`. Mount the predecessor
read-only and the new output on a separate writable mount. After validating
those two closes, use the same corrected arguments and output with `--resume`
and no transition limit. The source production tree remains pinned at `566a36819`;
only `/source/research/main_cagr` is overlaid with the reviewed recovery harness.

Focused validation: `python -B -m pytest
tests/sentinel/test_main_cagr_recovery.py tests/sentinel/test_main_cagr.py
tests/sentinel/test_fractional_core_research.py
tests/sentinel/test_in_kind_distributions.py -q -p no:cacheprovider`:
**63 passed**. This includes the ordinary missing-term refusal, exact fractional
cash, unchanged parent quantity, immutable predecessor outputs, exact resumed
state/accounting, and rejection of retrospective repairs and unrelated changes.

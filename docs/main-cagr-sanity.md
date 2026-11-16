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
Removing the prospective-date guard and exact-original-event guard in an
isolated process made all three selected falsifiers fail as expected (past
repair, same-day repair, changed distribution ratio). Source files stayed intact.

The real-data continuation passed 2015-07-01 and 2015-07-02 (2,247 measured
sessions). An independent read verified all daily calculations and 108 monthly
rows, every original committed output prefix, and exact equality of the copied
canonical state, accounting, metrics and counters at 2015-06-30. The one BXLT
liquidation records $47.84762599004924 total proceeds, including
$15.97952599004924 modeled fractional cash, at the retained $31.90 raw open.
The original 2,245-session run remains intact. The full continuation resumes
from that tested July 2 checkpoint in the separate scenario, with independent
full-history arithmetic verification required on completion.

## Missing cash-merger terms and an earlier checkpoint

The continuing run reached 2018-12-07 and refused performance on 2018-12-10.
It held 201.638202117061 SONC shares. The original 2018-12-07 terminal row names
a cash merger but contains no per-share consideration; its company-level deal
value cannot settle the holding. Preserve the valuation refusal. Restore the
2018-11-30 checkpoint into a new scenario and replay the intervening sessions.
Never insert cash directly into a saved state or amend completed output rows.

Retain authenticated primary source documents and use the existing exact-term
suppression/replacement API for three missing cash-merger terms of holdings
present at the refusal:

| Security | Retained terminal date | Correct economic date | Cash per share |
|---|---|---|---:|
| SONC | 2018-12-07 | 2018-12-07 | $43.50 |
| REGI | 2022-06-10 | 2022-06-13 | $61.50 |
| AMED | 2025-08-14 | 2025-08-14 | $101.00 |

Sources: Inspire's [completion](https://stories.inspirebrands.com/inspire-brands-completes-acquisition-of-sonic-corp/)
and [consideration announcement](https://inspirebrands.com/sonic-corp-acquired-inspire-brands-2-3-billion-transaction/),
Chevron's [completion](https://chevroncorp.gcs-web.com/news-releases/news-release-details/chevron-completes-acquisition-renewable-energy-group)
and [consideration announcement](https://www.chevron.com/newsroom/2022/q1/chevron-announces-agreement-to-acquire-renewable-energy-group),
and [Nasdaq's AMED corporate action notice](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2025-439).
Recognize economic merger cash on the completion session using the existing
research convention; these documents do not prove broker cash posting dates.
REGI's original last-trading-day terminal is one session earlier than completion.
Other prices, dates, dividends, selection, sizing and controller rules remain
unchanged. The earlier BXLT modeled cash assumption remains separately visible.

Extend continuation to an explicitly selected content-addressed checkpoint.
Authenticate its filename/hash, original binding, canonical state and committed
output prefixes. Also authenticate the predecessor's latest checkpoint/refusal,
so an older checkpoint cannot masquerade as the latest completed state. Every
suppressed and added terminal event must lie strictly after the selected cursor;
the earliest changed event must be on or before the refused session. Copy only
the selected committed prefixes; leave the complete predecessor and its later
rows intact. Record both checkpoint identities and the rewind boundary.

Prospective terminal repairs are separate from the original four input repairs
and formation identity. Preserve the prior spin-off correction byte-for-byte,
verify retained source hashes and exact replaced terms, and bind all new repair
documents into future input identity. The two explicitly reviewed predecessor
bindings are the only supported migration origins. Test the old recovery as
well as this path, retrospective changes, altered prior assumptions, corrupt
historical checkpoints, and the original missing-cash refusal. Qualify the
replayed December 7 settlement and December 10 valuation before restarting the
full continuation. Development remains based on verified main `69b4a78a`, while
the replay continues importing the original `566a36819` production snapshot.

The byte-retained REGI source is
[Nasdaq ECA2022-136](https://nasdaqtrader.com/TraderNews.aspx?id=ECA2022-136),
which confirms both the pre-open June 13 completion and $61.50 consideration.
The three correction documents have SHA256:

- SONC: `55e27430f962af82f0b7543bb4f7530b8b5a3a801ac627b5e603b12d185b29d9`
- REGI: `dbda75d27752689e65394a24ad59cfb28f2e3396013dd86ef7602b289056936f`
- AMED: `38712f173798992ddeedadfd6144aa75935ec456ce47510a0edb9b5942203cbd`

Continue with the previous original-input and spin-off arguments, adding the
three `--prospective-terminal-repair` paths, `--recover-from /predecessor` and
`--recover-checkpoint checkpoint-90d1bd6f29243ae140402ed7c5e4d3f539b8c54e7efffe74bc77de9b0d364f48.json.gz`.
That checkpoint is the authenticated November 30 boundary with 3,108 measured
sessions. Select a fresh output and `--max-transitions 6` to qualify through
December 11, including both the merger and the formerly refused December 10.

The focused four-file pytest command above now reports **75 passed**. Isolated
removal of prospective-date and unchanged-experiment guards makes all five
selected falsifiers fail: past/same-day spin-off changes, retrospective terminal
suppression/addition, and mutation of the prior spin-off assumption. The
fractional-sizing, transport, accounting, input and existing spin-off repair
modules remain byte-identical to the previous scenario.

The real-data qualification passed all six replayed sessions through 2018-12-11
(3,114 measured sessions and 149 completed monthly rows). Independent checks
verified Sentinel, SPY and Core daily arithmetic; exact initial canonical state,
accounting, counters and output prefixes; unchanged pre-event financial outputs
on December 3, 4 and 6; and preservation of all 3,112 predecessor sessions.
The single December 7 SONC settlement exchanges 201.638202117061 shares at
$43.50, recording $8,771.261792092155 in the canonical float research ledger
(exact decimal product $8,771.26179209215350). SONC leaves the book and the
formerly refused December 10 valuation resolves. The new scenario binding is
`163f3a826449fe4b6e72a481814643f3875d4ce230bc36c03397447b70134651`.
The separately mounted full continuation resumes from this tested December 11
checkpoint. Its twenty-year outcome remains pending; the source run and all
earlier scenario outputs are retained.

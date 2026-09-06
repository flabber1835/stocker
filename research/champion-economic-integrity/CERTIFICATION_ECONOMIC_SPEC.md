# Research Champion: economic specification and certification hold

Date: 2026-09-06. Status: **HOLD — intended economic contract contains unresolved conflicts and demonstrated implementation defects.**

This document records established rules and explicitly identifies unresolved rules. It does not approve a replacement economic model or a new certified CAGR. Classification **F** blocks final certification; **E** identifies a defect requiring a correctness repair and evidence.

## Authority and precedence

The user requires preservation of the frozen strategy and correctness-based attribution. Return direction supplies no evidence of correctness. The original accepted research implementation, the named freeze document, inherited production rules, and subsequent certification changes must be reconciled explicitly. Merely executing a rule or passing a test does not establish owner intent.

- Champion profile: `strategy9-e3-research-champion-v1`; SHA256 `1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26`.
- Candidate source: `ba74e79490beb8950611b1d17f5d124833b3d91e`; run [34007704385](https://github.com/flabber1835/stocker/actions/runs/34007704385).
- Certificate source: `27bb992087182c42c3c051e62bf837895f5d2ab7`; run [34014048220](https://github.com/flabber1835/stocker/actions/runs/34014048220).
- Champion evidence checkpoint: `3af356ab6d329e7bc6cdc015a49a6ca2d4e4b864`.
- Pinned production/runtime: `887f479b15ad861313da666ad698034d3847121c`.
- Canonical corpus SHA256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.
- Canonical package: `ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c`.

Source references below:

- **R**: exact generated candidate program retained in run 34007704385, assembled from `backtester/research_champion_corrected_classification.py`; underlying retained runner `research/sentinel-fastgate/experiments/2026-08-25-pit-vs-full-c/ldrc_ab_replay_20260825.py`.
- **C**: exact certificate assembly from `backtester/run_research_champion_strict_pit_20y_v2.py` at the certificate source SHA.
- **P**: `shared/stock_strategy_shared/wealth_core/{engine,adapter,terminal}.py` at the pinned runtime SHA.
- **T**: `backtester/research_terminal_grace_overlay.py`, `research_champion_terminal_leadership_overlay.py`, and candidate `research_terminal_lifecycle.py`.
- **K**: `backtester/canonical_pit_dataset.py`, `canonical_pit_package.py`, and the pinned manifest.
- **FZ**: [RESEARCH_CHAMPION_V1.md at the certified source](https://github.com/flabber1835/stocker/blob/27bb992087182c42c3c051e62bf837895f5d2ab7/research/strategy9-e3-broad-stability/RESEARCH_CHAMPION_V1.md), introduced by `6777961a3b8d11bcda2f721a97447ede5d076130` on 2026-09-05T17:31:36Z.

## Classification key

A = frozen Research Champion strategy economics. B = production economics intentionally inherited. C = certification-only assumption. D = data-causality requirement. E = accidental implementation artifact/defect. F = unresolved intended rule or insufficient proof. The primary classification in the table applies to the stated issue; notes identify additional provenance where relevant.

## Economic inventory

| ID | Input or rule | Actual behavior / established specification | Class | Authority or remaining issue |
|---|---|---|---|---|
| 01 | Initial shadow capital | Both paths initialize `Book.cash=100_000_000` at warmup start. Preserve this value during attribution. | A | R/C; predates certification. Deployment-capital applicability remains item 03. |
| 02 | Warmup and measurement | Warmup 2006-01-03; measurement 2006-07-31 through 2026-07-31; warmup trades and controller state carry into measurement; reported strategy NAV rebases to 1 at measurement start. | A | R/C/FZ. This is not a fresh all-cash launch on 2006-07-31. |
| 03 | Certified capital meaning | $100M is the starting shadow book, not a demonstrated deployable account capacity or the measured-start NAV. The actual portfolio is represented by a synthetic allocation overlay. | F | Explicit deployment-capital interpretation and account/shadow coupling require approval. |
| 04 | Position count | 25 slots. | A | R: N_SLOTS. |
| 05 | Entry sizing | New target `min(0.04 * current shadow equity, cash)`; existing winners are not routinely resized to 4%. | A | R/C admission loop. |
| 06 | Share granularity | New orders use whole shares. Held quantities can become fractional through split multiplication. Delivered conversion shares are floored with cash-in-lieu terms. | A | R/C Slot and split logic; T conversion convention. |
| 07 | Numerical rounding | Order sizing floors; pending quantities round to integer for execution; floating book accounting; some rolling market-history arrays use float32. | A | R/C. Strict capital-scale invariance is already false at rounding boundaries. |
| 08 | Liquidity eligibility | Minimum raw close $1; trailing-20 average dollar volume $20M; current-session dollar volume $5M. | A | R/C MIN_PRICE/MIN_ADV20/MIN_DAY_DV. Eligibility is a close decision. |
| 09 | Executable-order capacity | Certificate adds a 10% prior-20-share-volume ceiling. Corrected candidate and pinned production execution omit that guard. | E | T and P; the earlier user handoff explicitly identifies the synthetic rule as a harness defect and prohibits reintroduction. |
| 10 | Oversized-order treatment | Certificate retains the full order and retries it; no capacity-sized partial progress or expiry. Held exits and reserved entries can remain blocked. | E | T `defer_excess=True`; whole-order `continue` branches. |
| 11 | Capacity history | Certificate uses the latest 20 positive raw-compatible observations, appended after open fills; missing authority raises. Split-domain continuity of that history requires separate proof if capacity is ever adopted. | C | T; not an approved Champion execution model. |
| 12 | Cash-limited fill | At an executable open, quantity is clipped to affordable whole shares; pending request is then cleared. The unfilled cash-limited residual does not persist. | A | R/C buy loop; capacity guard is checked before this clipping in C. |
| 13 | Missing execution price/volume | Pending orders wait for a positive raw open and positive session volume. | A | R/C. Intraday availability of final daily volume is item 49. |
| 14 | Signal and order timing | Closing-session data generate orders for a subsequent open; pending prior orders execute before new closing admissions. | A | R/C; exact intraday input visibility still requires independent testing. |
| 15 | Execution prices | Canonical as-traded raw open; signal-domain open used for the entry review basis. | B | R/C and pinned production review-basis correction lineage. |
| 16 | Review timing | One review at age at least 119 trading sessions; underwater and unqualified positions queue an exit. | A | R/C REVIEW_AGE and review predicate. |
| 17 | Stops and exit timing | Close-based 30% peak drawdown stop; queued exit seeks a later executable open. | A | R/C STOP_RET=0.70. |
| 18 | Replacement logic | Initial population can fill multiple ready slots; subsequent admissions are limited to one per session after initialization. | A | R/C admission loop. |
| 19 | Cooldown | 21-session slot and security cooldown after ordinary release/settlement. | A | R/C COOLDOWN and sec_ready. |
| 20 | Ranking | Momentum from lagged 21/126-session closes; risk-normalized log-momentum score; top max(25,ceil(10% of eligible)) momentum pool; deterministic permanent-ID tie breaks. | A | R/C feature, pool, and durable-ranking code. Exact formulas remain in the pinned generated program. |
| 21 | Fresh-entry momentum | Nonnegative recent return required for admission. | A | R/C recent-return admission predicate. |
| 22 | Minimum history / IPOs | Listing effective by session and 126 valid return observations plus required finite features. There is no separate discretionary IPO calendar. | D | R/C listing and continuous-history gates. |
| 23 | Universe | Broad canonical security episodes satisfying price/liquidity/history/type rules. Neither S&P 500 nor Russell index membership defines these two runs. | A | R/C/K. |
| 24 | Historical security type | Certificate admits canonical `common`; unknown is excluded. Candidate adds inferred/reviewed classifications for canonical unknowns. | F | Effective intended universe and acceptable evidence standard must be resolved jointly; factual historical type alone does not prove contemporaneous availability. |
| 25 | Future classification evidence | Candidate applies PDS non-common correction on 2006-07-05 with evidence_available_from=2010-06-01. | E | Candidate SecurityTypeEstimate._historical_correction tests effective interval, not evidence availability. Exact-source probe reproduces it. |
| 26 | Current metadata | Current SHARADAR TICKERS fields are inactive in the certificate replay. Candidate estimate provenance explicitly includes provisional/non-PIT evidence. | D | C metadata audit; candidate best-effort classification module and summary. |
| 27 | Exchange eligibility | No current-exchange gate; a current snapshot cannot establish historical exchange membership. | D | R/C explicit source annotation. |
| 28 | Permanent identity / survivorship | Canonical security episodes and action identities are consumed chronologically; dead names remain in the historical corpus. | D | K/R/C. This does not independently certify every metadata publication timestamp. |
| 29 | Issuer and sector labels | Champion uses singleton permanent-security keys for issuer/sector-dependent seams; it does not inherit production's full issuer-family policy. | A | R/C issuer_key and fixed-breadth transform. |
| 30 | Correlation/breadth | Dynamic residual-correlation peers from strictly prior history; peer lookback 252, minimum 120 observations, up to 3 peers, correlation floor 0.145. | A | R/C `_prior_residuals`, `_peer_corr`, `dynamic_peer_breadth`; full predicates are source-pinned. |
| 31 | Structural cash | Cash retained inside the Wealth Core shadow book receives zero yield. | A | R/C Book accounting. |
| 32 | Defensive cash | Allocation complement receives canonical defensive-cash return factors, using BIL factors when available and lagged GS3M Treasury factors otherwise. | C | K and backtester/historical_cash.py; model applicability must be explicit in a final contract. |
| 33 | Treasury cash timing | Previous calendar-month GS3M yield, calendar-day accrual split into overnight gap and one intraday day, annual divisor 365.2425. | C | historical_cash.py. |
| 34 | Cash data vintage | Prior-month lag is visible in code; contemporaneous publication/vintage authority has not been independently established for all adopted GS3M observations. | F | A lagged observation date is not itself a vintage-availability proof. No finding of an actual GS3M revision is asserted. |
| 35 | Dividend entitlement | Prior-close ownership, transformed for a same-session split; open buyers receive no ex-date dividend, open sellers retain it. | B | R/C `prior_qty`; P.apply_dividends. |
| 36 | Dividend settlement lag | Candidate uses 1 session; certificate uses 15. Production explicitly adopts 1; FZ explicitly adopts 15 for formal certification. | F | Both are documented conventions. The 15-session rule predates the target certificate result. Resolve this contract conflict explicitly. |
| 37 | Dividend open-boundary accounting | Both generated paths append ex-date claims after computing open equity. Production accrues them before that allocation boundary. | E | Exact-source source probes show allocation-change dividend misattribution. Closed-book arithmetic can pass while the open entitlement is incomplete. |
| 38 | Split processing | Transform quantities before dividend entitlement and open execution; use canonical split ratio and as-traded dividends. | B | R/C/T and P. |
| 39 | Pending orders and splits | Whole-share pending entry transformations can be cancelled when integral execution quantity cannot be preserved; held fractions are retained. | B | R/C split loop and P transformation policy. |
| 40 | Known terminal terms | Authenticated cash merger, write-off, stock conversion and mixed consideration use explicit terms; stock fractions require cash-in-lieu authority. | B | T exact_terminal_economics and frozen terminal-terms loader. |
| 41 | Unknown terminal outcomes | Both book paths can carry a C1 claim at the last positive raw mark and later convert that modeled value to cash after 10 missing sessions. This is a proxy-recovery convention. | F | FZ names terminal grace, but applicability of full last-mark cash recovery to each uncertain claim still requires intended-model adjudication and held-path validation. |
| 42 | Delistings/liquidations/acquisitions | Canonical terminal actions and exact terms drive account transitions; no universal zero-recovery rule applies. | B | R/C/T. Actual payment timing and unknown outcomes remain item 41. |
| 43 | Terminal event ordering | Splits precede captured dividend entitlement and terminal transformations; pending fills follow. Research dividend posting is late (item 37). | B | R/C/T/P. |
| 44 | Terminal retirement | Candidate permanently removes canonical terminal IDs from eligibility and cancels pending re-entry. Certificate uses same-session cancellation and next-witness filtering. | F | Intent/economic consequence of permanent retirement versus episode authority requires explicit resolution and causal terminal knowledge. |
| 45 | Recent-leadership terminal return | Candidate uses exact terminal consideration when available, with a zero-contribution missing-return route; certificate uses observed signal-close return and fail-closed missing data. | F | Candidate terminal lifecycle and C terminal-leadership overlay; FZ explicitly names fail-closed missing leadership. |
| 46 | Missing held marks / NAV | Candidate carries last marks and blocks new admissions when unresolved. Certificate aborts after measurement start except approved carried terminal claims with a prior positive mark. | F | FZ/C adopt stricter NAV; candidate production-parity closure chose another contract. |
| 47 | Valuation | Book NAV is cash plus dividend receivables plus held quantities times current raw marks or the admitted carried mark. A carried terminal slot is counted once. | B | R/C Book.equity; independent arithmetic and entitlement completeness are separate checks. |
| 48 | Realized/unrealized P&L | No separate authoritative realized/unrealized tax-lot report is retained by these replay artifacts. Cash/share/claim transitions permit reconstruction when complete stage evidence exists. | F | Independent full-horizon P&L and terminal-settlement reconstruction remain open. |
| 49 | Intraday causality | Whole-day volume is tested for open executability; current terminal-session close can be used during pre-open terminal accounting. Exact information-availability semantics need adversarial tests. | F | R/C/P source inspection; code order alone does not resolve data availability. |
| 50 | Commission/slippage/spread | Constant 10bps per-side Wealth Core fill cost. No separately parameterized commission, bid/ask spread, or market-impact curve. | A | R/C COST=0.001; this is a modeling convention, not a live fill forecast. |
| 51 | Overlay transition cost | Additional COST*abs(new allocation-old allocation) at allocation changes. | A | R/C apply_overlay. |
| 52 | Wealth Core shadow state | Shadow positions and controller observations keep evolving while the reported allocation is defensive. | A | R/C chronological run and Native/CandidateA state. |
| 53 | Sentinel / controller scope | This replay executes the retained Native plus CandidateA allocation model. It does not run a broker account, live Sentinel reconciliation, or live execution service. | A | R/C; production-kernel tests do not establish this generated model's equivalence. |
| 54 | Frozen E3 parameters | REC=8, R20=-0.085, V=0.11, DD=-0.10, divergence SPY floor=0, full-recovery r40 floor=0, FAST damaged=0.88, healthy damaged ceiling=0.63. | A | Profile/FZ. Unchanged throughout this audit. |
| 55 | Remaining controller predicates | Preserve exact Native and CandidateA classes, transition ordering, histories, release routes, ordinary/FAST/SLOW dictionaries, and initial states from the pinned source. | A | Full generated program plus normalized AST hashes are the executable enumeration of these rules. No tuning is authorized. |
| 56 | Research-path promotion | Candidate A is promoted to authoritative research_nav and research_allocation; promoted series must match A exactly. | A | R/C Champion promotion and FZ. |
| 57 | Fail-closed exclusions | Missing history, invalid prices, insufficient eligibility evidence and explicit integrity failures have distinct effects; they must be counted separately from capacity-driven deferrals. | D | R/C/K; any changed exclusion policy is an economic dimension. |
| 58 | Certification causality coverage | Existing dynamic future-poison/truncation evidence invokes the pinned production kernel. It does not execute this generated Champion program. | F | future_leak_certification_pinned_runtime.py and retained dynamic-future-leak.json. Exact-Champion scope and equivalence remain unproven. |
| 59 | Checkpoint/resume coverage | The certificate receives PASS labels; an independently checked complete checkpoint/resume chain for this exact generated Champion state has not been established by this investigation. | F | Finalizer inputs and retained test/replay evidence. |
| 60 | Portfolio accounting completeness | Decimal reconstruction of recorded state is required, plus independent entitlement completeness, corporate-action conservation and terminal cash authority. | D | A self-consistent recorded ledger alone cannot prove every economic claim is present or justified. |

## Initial-capital and capacity adjudication

The $100M constant was present when the retained runner was introduced by `68565d70d02a2f4f93943cf690ada8b3773e4540` on 2026-08-26. It was not introduced for the September 6 certificate. Both target runs use it. On the first measured session their already-traded shadow NAVs are $92,410,966.71752562 and $93,207,107.2657491 respectively.

The capacity ceiling was introduced in research overlay commit `8c88ba180f9a7158ed02505e6562084eeffe848a` and changed to persistent whole-order deferral by `466bf93211851dc5c1ec45e10c5ee538cfee19a8`. Source comparison with pinned production and the earlier user handoff establish that its reappearance is a harness regression. Lowering initial capital would mask that regression and change integer-share economics. Capital stays fixed for this investigation.

A deployment capacity curve would require a separately adopted execution/participation specification and explicit account capital. This audit does not authorize that model or an arbitrary $100K certification.

## Required contract resolutions before final certification

1. Resolve the **documented 1-versus-15 dividend-lag conflict**, and the corresponding strict versus production-parity missing-mark/leadership policies. Record the approval independently of return results.
2. Define the causal evidence policy for historically unknown security types and terminal outcomes. Repair PDS availability enforcement and audit the inferred-classification population.
3. Remove the demonstrated unintended capacity semantics in the correctness repair, preserve source-lineage evidence, and test exact intended order behavior.
4. Repair the shared open-dividend entitlement boundary and prove both ordinary and allocation-change accounting, including same-day split/terminal combinations.
5. Specify shadow capital, measured-start state, defensive cash convention, terminal proxy valuations and their applicability to any deployment claim.
6. Complete exact-Champion causality, accounting and checkpoint proofs for the stated contract. Only then execute and certify a newly identified full replay.

**No currently reported CAGR is approved by this document.** See `CANDIDATE_VS_CERTIFIED_SEMANTIC_DIFF.md`, `ECONOMIC_ATTRIBUTION_AUDIT.md`, and `REPRODUCTION.md` for the evidence and bounded scope.

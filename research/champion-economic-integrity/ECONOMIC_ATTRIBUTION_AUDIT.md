# Economic attribution audit: Research Champion

Date: 2026-09-06. Outcome category: **E — certification remains unresolved because the intended economic contract contains unresolved conflicts.** Readiness: **HOLD**.

The evidence establishes an unintended capacity rule in the certificate, a decision-time classification defect in the candidate, and a shared dividend/open-equity implementation defect. Neither published CAGR is approved as the return of a fully established, correctly implemented intended Champion contract. The full 20-year causal decomposition, complete independent accounting proof and final contract remain open.

## 1. Exact evidence and scope

| Role | Source / identity |
|---|---|
| Candidate, run [34007704385](https://github.com/flabber1835/stocker/actions/runs/34007704385) | ba74e79490beb8950611b1d17f5d124833b3d91e |
| Certificate, run [34014048220](https://github.com/flabber1835/stocker/actions/runs/34014048220) | 27bb992087182c42c3c051e62bf837895f5d2ab7 |
| Pinned runtime | 887f479b15ad861313da666ad698034d3847121c |
| Profile | strategy9-e3-research-champion-v1 |
| Profile SHA256 | 1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26 |
| Corpus SHA256 | 5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993 |
| Bounded observation source | b0a3033d83584541f4d6f306ecee27e318d29a59 |
| Bounded observation run | [34042141867](https://github.com/flabber1835/stocker/actions/runs/34042141867), original attempt 1 |
| Successful complete offline publication | [34044202728](https://github.com/flabber1835/stocker/actions/runs/34044202728), source d342842550e177cc8e4f006956da8f987a970bbf |
| Complete evidence commit | ede62f51d2047394b8b1fa089a6cb848beffa2c7 |
| Additional successful core-evidence publication | [34044212525](https://github.com/flabber1835/stocker/actions/runs/34044212525), source 33aacbf8c27a9c7c4c0248653b51ec0a62238fed |
| Core-evidence commit | 14ba19b7ec26201d65de271a7b35556b2c6bb95b |

The preregistered prefix starts at the original warmup boundary, **2006-01-03**, and stops after **2006-08-02**: **147 sessions** per case. The measurement boundary stays **2006-07-31**. The full canonical package and declared full endpoint remain unchanged. Initial shadow cash stays **$100,000,000**. All Champion parameters stay frozen.

Two baseline observations recover state missing from the original reports. Three controls each change one dimension: executable-order participation, dividend settlement lag, or the unknown-security-type classifier. Their source transformations were registered in `EXPERIMENT_PLAN.md` before execution. These controls are diagnostic and issue no certified CAGR.

### Baseline reproduction and recovery

All five observation cases completed. The initial workflow then failed in postprocessing because the original reports use `research_wealth_core_equity` and `research_wealth_core_open_equity`, while the observer retains `shadow_equity` and `open_equity`.

`validate_champion_economic_prefix.py` applies that explicit report-column mapping to the retained bytes. Both original baselines reproduce **all 30 common columns for all three measured sessions**, with relative tolerance 1e-12 and absolute tolerance 1e-7. The recovered candidate's normalized source AST matches its original retained generated program. Stripping read-only observer calls gives each case's unchanged economic AST. Validation ran on Python **3.12.14**.

The original failed workflow, its job log and the successful offline validation are preserved. The five economic observations were not rerun during this recovery.

Primary data: [`baseline-reproduction.json`](evidence/bounded-prefix/baseline-reproduction.json), [`controlled-replay-identities.json`](evidence/bounded-prefix/controlled-replay-identities.json), [`economic-attribution.json`](evidence/bounded-prefix/economic-attribution.json), [`controlled-replays.csv`](evidence/bounded-prefix/controlled-replays.csv).

## 2. First economically meaningful divergence

The first measured daily record is already downstream of different warmup decisions. Comparing only the rebased July 31 curves hides the actual first divergence.

| Observable | First differing session | Candidate | Certificate |
|---|---|---|---|
| Eligible universe | 2006-07-05 close | 1,102 securities | 837 securities |
| Durable/leadership ranking population | 2006-07-05 close | 111 | 84 |
| First different selected admission | 2006-07-05 close | Slot 2: FALB, 75,028 requested shares | Slot 2: TTI, 131,577 requested shares |
| Pending order set | 2006-07-05 close | Candidate admission orders | Different certificate admission orders |
| First fill/share difference | 2006-07-06 open | Identical MED request executes | MED request is deferred by participation guard |
| Cash after the buy stage | 2006-07-06 | $34.847525626886636 | $27,987,265.84574911 |
| Closing shadow NAV | 2006-07-06 | $99,615,288.33752564 | $99,329,237.17574912 |
| Open shadow NAV | 2006-07-07 | $99,661,004.16183762 | $99,442,739.1623921 |
| Reported rebased strategy NAV | 2006-08-01 | 0.9834836198103472 | 0.98489555570064 |
| First different dividend or corporate-action outcome | Not established in this prefix | No held dividend events; two held splits | No held dividend events; the same two held splits |

Ticker labels are the canonical dataset's display labels. Permanent security IDs supply identity: FALB `1040633074096912075`; TTI `720308907044255892`. The display label alone is not evidence of the ticker used by an exchange on the historical date.

### The earlier classification divergence

The first two admissions are MED and ACLI in both original cases. The third differs because the candidate applies its provisional classifier to canonical unknowns. FALB's candidate ledger classification is `INFERRED_COMMON` and explicitly marked `BEST_EFFORT_NOT_PIT_CERTIFIED`. Its inference includes the vendor category `CanadianCommonStock` and a unique price episode; it does not establish contemporaneous publication authority.

The classifier-only control reproduces the July 5 universe and admission change while retaining the certificate's capital, execution guard, dividend lag and terminal policies. This proves a classification-driven cause independent of the subsequent fill deferrals.

### The first capacity-driven fill divergence

Both original cases request **205,028 MED shares** for July 6 at the raw open of **$19.87**. The certificate's prior-20-session mean share volume is **1,324,405**, giving a 10% ceiling of **132,440.5 shares**. The requested participation is **15.480763059638103%**.

The candidate fills that order and spends **$4,077,980.266360**, including its 10bps cost. The certificate retains the full request. The capacity-off control executes that same request while keeping the certificate's eligible universe and rankings identical.

This is a direct, controlled explanation of the first capacity fill difference. It does not assign the whole 20-year CAGR difference to capacity.

## 3. One-dimensional controlled results

All values below are at **2006-08-02**, after the same 147-session prefix. Cash is the Wealth Core shadow book's cash, not the reported synthetic overlay's defensive allocation.

| Case | Sole changed dimension | Held positions | Cash | Interpretation |
|---|---|---:|---:|---|
| Original candidate | None; observation only | 25 | $34.85 | Reproduces the retained candidate prefix |
| Original certificate | None; observation only | 18 | $27,987,265.85 | Reproduces the retained certificate prefix |
| Certificate, capacity guard removed | Executable-order participation only | 25 | $4.64 | Previously oversized orders execute; eligible sets and rankings remain identical to the certificate throughout this prefix |
| Certificate, dividend lag 1 | Settlement lag 15 to 1 only | 18 | $27,987,265.85 | Identical observed state; no held ex-date dividend occurs, so this dimension is unexercised |
| Certificate, candidate type classifier | Unknown-type classification only | 15 | $39,912,446.25 | Different rankings select a different group of orders that interact with the unchanged execution ceiling |

The original certificate retains seven blocked orders through the prefix. The analyzer records **140 over-capacity order/session observations**. Capacity-off records seven orders above the hypothetical ceiling, all executable under that case. An over-capacity observation is not automatically a deferral when the guard is disabled.

The classifier-only case has 215 over-capacity observations. Its different cash deployment proves that classification and capacity interact. One-factor effects cannot be summed into an additive CAGR decomposition.

At July 31, capacity removal produces shadow NAV **$90,904,976.068718**, compared with **$93,207,107.2657491** for the original certificate. The capacity defect is established from intended-rule lineage and execution semantics. The short-prefix return direction provides no correctness criterion.

### Dividend-lag control limitation

No held dividend entitlement arises in these 147 sessions. Identical output therefore establishes only that the unexercised lag change did not alter other observed state. The historical impact of the 1-versus-15 lag remains **unidentified by this prefix**.

## 4. Independent portfolio-accounting checks

The observer independently reconstructs each recorded open and close NAV using Decimal arithmetic:

`cash + sum(held quantity * contemporaneous raw mark) + outstanding dividend receivables`.

Admissible carried terminal values occupy held slots and are counted once. The observer's reconstruction does not call the backtester's NAV function.

| Case | Recorded-state accounting checks | Failed checks | Buy fills | Sell fills |
|---|---:|---:|---:|---:|
| Candidate | 1,651 | 0 | 25 | 0 |
| Certificate | 1,518 | 0 | 18 | 0 |
| Capacity off | 1,651 | 0 | 25 | 0 |
| Dividend lag 1 | 1,518 | 0 | 18 | 0 |
| Candidate classifier | 1,446 | 0 | 15 | 0 |
| Total | **7,784** | **0** | **108** | **0** |

These include **1,470 independent open/close NAV reconstructions**. Buy cash flows include the 10bps cost. Split checks are performed each applicable session; most sessions use a ratio of one.

Two actual held split transformations occur in every case: canonical display label MNST, security `530996274575880476`, July 10 ratio 4, quantity 19,459 to 77,836; and TEX, security `950063614365024268`, July 17 ratio 2, quantity 40,379 to 80,758. The quantities reconcile.

There are **no held dividend, sale or terminal/conversion events** in the prefix. Zero-transfer checks on those dates do not prove nonzero-event accounting. Full-horizon realized/unrealized P&L, terminal settlement authority, dividends and complete share/claim conservation remain outstanding.

### A shared entitlement-completeness defect survives arithmetic reconciliation

Both generated programs compute open equity before posting the current ex-date dividend receivable. They correctly capture prior-owner quantity, but post its claim after the open-equity boundary. Production accrues that receivable before its open witness.

An exact-source synthetic fixture uses prior NAV 100, ex-dividend open position value 90, valid receivable 10, and close NAV 100. With the implemented transition cost:

| Allocation transition | Generated overlay factor | Factor with the valid claim present at the open boundary |
|---|---:|---:|
| 100% to 0% | 0.8991 | 0.9990 |
| 0% to 100% | 1.1100 | 0.9990 |
| 100% to 100% | 1.0000 | 1.0000 |

The exact extracted functions reproduce this error on Python 3.12.14. The result proves an implementation defect in both paths. Its historical CAGR effect remains unmeasured, and the prefix contains no dividend event that exercises it. See [`source-probes.json`](evidence/source-probes.json).

## 5. Causality and certification-claim coverage

### Candidate classification authority

The exact candidate `_historical_correction` method returns a PDS non-common exclusion for **2006-07-05**, even though the selected row declares **evidence_available_from=2010-06-01**. It tests the classification's effective interval and omits the decision-time availability test. The source probe reproduces this result for permanent security `594891209465982980`.

The historical fact may be accurate. The code's contemporaneous-authority claim is unsupported for the 2006 decision. The broader inferred-common population also requires an explicit, defensible evidence policy.

### Financial and checkpoint labels

Run [34043631885](https://github.com/flabber1835/stocker/actions/runs/34043631885) executes the exact certified collector on Python 3.12.14. Using only a summary declaration and a metadata declaration, it obtains `financial_semantics=PASS` and `checkpoint_resume=PASS`; `annual_chain` remains null. It supplies no replay, ledger or exercised checkpoint.

This is an evidence-collector fixture. It does not demonstrate that fabricated evidence passes the complete finalizer. It establishes that those particular labels do not independently prove accounting or resume correctness. The financial predicate explicitly requires the declared 15-session lag; a correctly declared convention is not equivalent to a correct entitlement ledger.

### Dynamic test target

The retained future-poison/truncation tests execute the pinned Production kernel. The generated Research Champion program has different, demonstrated economic semantics. The test result does not establish dynamic causality for that exact generated program.

Current-session volume at open execution, terminal-session close values used during terminal processing, full historical classification/terminal publication authority and cash-yield vintage availability remain explicit causality proof obligations. These are scope gaps; an actual violation is asserted only where directly reproduced, such as PDS.

See [`CERTIFICATION_CLAIM_COVERAGE.md`](CERTIFICATION_CLAIM_COVERAGE.md).

## 6. Economic intent and the $100M question

The original retained runner already initializes its shadow book with $100M. Commit `68565d70d02a2f4f93943cf690ada8b3773e4540` introduced that runner on August 26. Both target runs use it. July 31 is a rebased measurement boundary after warmup trading; it is not a fresh cash deployment.

The executable 10% volume ceiling was added in research overlay `8c88ba180f9a7158ed02505e6562084eeffe848a` and changed to persistent whole-order deferral by `466bf93211851dc5c1ec45e10c5ee538cfee19a8`. Pinned Production execution omits that ceiling. Corrected closure removed it, and the earlier user handoff explicitly prohibited its reintroduction. The certificate reintroduces an unintended rule.

Capital remains $100M during this investigation. A $100K result would change an economic dimension and could obscure the unintended execution behavior. Integer-share rules already create small capital-scale effects even when the participation guard is absent. A deployable capital-capacity contract still needs explicit adoption.

The dividend lag has a different provenance. Production and the corrected candidate use one session; the freeze document explicitly requires 15 for formal certification. That formal requirement predates the two target outputs. The conflict concerns which documented contract represents the intended Champion claim. The audit cannot resolve that intent by comparing performance.

Other unresolved contract items include unknown security-type evidence, terminal retirement/leadership policy, unresolved-mark treatment, C1 proxy recovery, shadow/account-capital interpretation and cash convention. The 60-rule inventory records them in [`CERTIFICATION_ECONOMIC_SPEC.md`](CERTIFICATION_ECONOMIC_SPEC.md).

## 7. Full-path observations and remaining proof

Both original artifacts retain 5,032 measured sessions. The first strategy-allocation difference occurs on **2015-08-26**: candidate 0%, certificate 100%. Earlier stock, cash and ranking differences precede it. The original artifacts report 506 versus 197 buys and 424 versus 169 sells.

The semantic audit identifies seven independent axes: executable capacity, unknown-type classification, dividend lag, terminal retirement, terminal leadership return, next leadership witness, and missing-mark policy. The prefix isolates two exercised mechanisms and one unexercised control. Additional full-horizon terminal/dividend accounting and exact-Champion causality evidence is required to close the other axes.

The audit therefore does not assert a numerical decomposition of the 20.09%-versus-9.20% CAGR gap, a complete first-dividend/corporate-action divergence, or an approved replacement CAGR.

## 8. Final readiness verdict and resumption checkpoint

**Category E. Certification readiness: HOLD.** The observed outputs cannot settle the unresolved intended-model contract. Demonstrated implementation defects require correctness repairs, and the exact Champion needs independent accounting and causality proof.

The next step is to record authoritative decisions for the documented contract conflicts, then implement the narrowly identified corrections with tests that fail when each defect is reintroduced. The exact generated Champion's entitlement-complete accounting, future-information resistance and complete-state resume equivalence must pass before a newly specified full certification replay.

Strategy parameters, starting capital, main and Production remain unchanged by this audit. Source inspection, original paths, state observations, controlled metadata, exact-source probes, failed-postprocessor evidence and successful validations are retained on the isolated research branch. `REPRODUCTION.md` identifies the two immutable publication manifests and their scope.

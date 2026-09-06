# Economic-integrity investigation: preregistered diagnostic contract

Status: INVESTIGATION ONLY. No final certification or promotion is authorized by this document.

## Immutable authorities

- Candidate: run 34007704385, source ba74e79490beb8950611b1d17f5d124833b3d91e.
- Certificate: run 34014048220, source 27bb992087182c42c3c051e62bf837895f5d2ab7.
- Champion evidence checkpoint: 3af356ab6d329e7bc6cdc015a49a6ca2d4e4b864.
- Runtime: 887f479b15ad861313da666ad698034d3847121c.
- Profile: strategy9-e3-research-champion-v1, SHA256 1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26.
- Canonical dataset: 5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993.
- Package: ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c.
- Source/history collection: https://github.com/flabber1835/stocker/actions/runs/34041287501 ; archive SHA256 2d1ba513508755b9ad2c378dcec5b6c3012e9f71d87fb4e8b16576a087e756fa.

## Findings established before experiments

The generated programs differ in execution participation checks, security classification, dividend cash timing, terminal leadership treatment, permanent terminal retirement, and the unresolved-NAV failure policy. The common corpus hash does not bind those effective economic rules.

Both engines initialize the Wealth Core shadow book with $100,000,000 at the beginning of warmup. The value predates certification: the retained runner was introduced by 68565d70d02a2f4f93943cf690ada8b3773e4540 on 2026-08-26. The reported July 31, 2006 measurement starts with already-traded books: candidate $92,410,966.71752562 and certificate $93,207,107.2657491. Their published strategy curves are separately rebased to 1.0. Warmup capital and measurement-start capital must be distinguished.

The 10%-of-prior-20-volume execution ceiling was introduced in research overlay commit 8c88ba180f9a7158ed02505e6562084eeffe848a and changed to whole-order deferral in 466bf93211851dc5c1ec45e10c5ee538cfee19a8. It is absent from the pinned Wealth Core execution adapter. The corrected closure source explicitly removed it. A prior user handoff also explicitly prohibited reintroducing it. The formal certificate nevertheless includes it.

Pinned Production WealthCoreConfig declares a one-session dividend settlement convention and requires a larger lag to be explicitly selected. Certification hardening e820e3af9e2893cae301198201e2f5bf4b8f6944 imposed 15 sessions.

The candidate remains unsuitable for an unqualified PIT claim. Its security-type estimate module explicitly labels itself non-PIT. For PDS, a non-common classification is applied starting 2006-07-05 using a correction row with evidence_available_from=2010-06-01. The effective interval is tested; publication availability at the decision session is not tested. This is a decision-time authority defect even if the historical classification is factually accurate.

## Bounded evidence-recovery experiment

Replay prefix: original warmup 2006-01-03 through 2006-08-02 inclusive. Original measurement boundary stays 2006-07-31. Original full dataset and its declared end remain unchanged. A read-only end-of-session observer stops execution at the prefix boundary. It does not issue a CAGR or certificate.

| Case | Baseline | Sole changed economic dimension | Preregistered consequence |
|---|---|---|---|
| candidate | Exact candidate | None; recover missing quantities/cash ledger | Reproduce retained candidate prefix |
| certified | Exact certificate | None; recover missing quantities/cash ledger | Reproduce retained certified prefix |
| certified_capacity_off | certified | Remove the two execution participation guards | Previously oversized orders can execute; capital, classification and dividend lag stay unchanged |
| certified_dividend_1 | certified | Dividend settlement lag 15 to 1 | Entitlement and ex-date receivable amount stay unchanged; spendable cash arrives earlier |
| certified_candidate_types | certified | Use the exact candidate unknown-type classification layer | Eligible population/rank geometry may change; capacity, terminal policies and dividend lag stay unchanged |

The two baseline observations are evidence recovery, not new performance evaluations. The three counterfactuals identify separate semantic causes. They are not a parameter search and cannot select a preferred result by return. Classification-counterfactual output inherits the candidate's provisional/non-PIT limitations.

The starting $100M, all Champion parameters, transaction costs, corpus, warmup and prefix endpoint are fixed across all cases. No $100K case is authorized. A capacity curve is not authorized by this experiment.

## Required proof and interpretation

1. Record source/runtime/profile/corpus IDs, generated-source hashes, normalized AST hashes, and the exact transformation for each case.
2. Strip read-only observer calls from the instrumented AST and prove equality with that case's economic AST. Output path changes are separately identified.
3. Compare baseline prefix output with the retained original daily output; fail on a material mismatch.
4. Retain pre-action, post-split, pre-fill, post-sell, post-buy, post-dividend, close-NAV and final state observations, including cash, share quantities, marks, receivables, pending orders and candidate sets.
5. Independently reconstruct observed NAV using Decimal cash + shares times contemporaneous raw marks + dividend receivables. Identify carried terminal claims separately; their value is already included in the held-position term.
6. Independently check settlement cash conservation, split share conservation, buy/sell cash flows including 10bps, and dividend accrual. Report unexercised terminal/conversion cases explicitly.
7. Locate first differing eligible set, ranking, order, fill, quantity, cash, corporate-action result and NAV, including warmup.
8. Report bounded evidence as bounded. It does not decompose the full 20-year CAGR gap or certify all terminal cases and all intraday causality boundaries.

## Remaining final-certification blockers

A complete economic inventory, source-specific intended-rule adjudication, full terminal/missing-mark causality, candidate classification authority closure, and exact-Champion dynamic causality tests remain necessary. The existing future-leak canary invokes the pinned Production kernel, not this generated Champion program. Passing it cannot establish equivalence of the two economic programs.

Final certification remains blocked while any intended-rule classification is unknown or an implementation defect remains active.

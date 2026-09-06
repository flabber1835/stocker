# Factual security-type audit V2

Date: 2026-09-06

Status: PARTIAL_FACTUAL_AUDIT_NOT_CERTIFIED

## Completed first batch

Seven canonical unknown-type estimates change from `common` to `non_common` under the existing common-stock-only policy:

| Ticker | Legal security class | Canonical interval |
|---|---|---|
| GOLLQ | ADS representing preferred shares | 2006-07-05 through 2021-06-30 |
| CIG | ADS representing preferred shares | 2006-10-05 through 2022-11-17 |
| PBR.A | ADS representing preferred shares | 2006-07-05 through 2026-07-31 |
| NTI | Limited-partnership common units | 2013-01-29 through 2016-05-23 |
| NGL | Limited-partnership common units | 2014-06-18 through 2019-03-11 |
| CVRR | Limited-partnership common units | 2013-07-19 through 2018-08-21 |
| UAN | Limited-partnership common units | 2013-06-10 through 2022-05-19 |

The 18-source legal-fact docket, exact canonical IDs, CUSIPs, interval reasoning and primary-source locators are retained in `backtester/data/champion-security-truth-factual-batch-v2.json`.

Its SHA-256 is `b08d6e4b92bb0a0e106927e15c6ea7ef5f8f0ffec3174c4aacc93bbd60cde517`.

The UAN post-split exact-CUSIP event document remains an identity-retention follow-up. Issuer filings establish the LP-unit type on both sides of the reverse-unit split. This is a type correction, not a full identity certificate.

## Coverage defect

The initial 715-case queue selected multiple-CUSIP, manual-conflict and unusual-category cases. A single CUSIP and a vendor common-stock label did not establish factual security type. Five of this batch's seven errors were absent from that queue.

On retained path run 34007704385, the complete 1,751-security candidate inventory contains 83 held/pending securities. The initial queue contained 27 and omitted 56. V2 exposes all 1,751 candidates and adds every held/pending case to the targeted review frontier.

The pre-replay expanded frontier contains 775 securities. Seven type corrections leave 768 targeted cases open: 81 held/pending, 444 durable-ranked, 182 leadership and 61 ranking/base. Of the original 715 cases, 713 remain open. Securities outside the targeted frontier remain explicitly labeled base hypotheses.

These counts describe the retained pre-correction path. The V2 replay records fresh path counts for the complete candidate inventory. No path count, ranking, realized performance or future survival supplies a classification decision.

## Controlled replay and invariants

The comparison baseline is successful run 34047029680, approximately 17.92% CAGR. Its retained artifact supplies the comparison path and identity. No V2 return is claimed before execution completes.

Frozen controls: Research Champion `strategy9-e3-research-champion-v1`, $100,000,000 initial shadow cash, runtime `887f479b15ad861313da666ad698034d3847121c`, canonical corpus `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`, warmup 2006-01-03, measurement 2006-07-31 through 2026-07-31. The two unintended whole-order participation guards remain removed. Dividends, terminal handling, controller, sizing, costs and Champion parameters remain unchanged.

The seven-case overlay is applied only at canonical unknown-security-type seams. Existing reviewed-18 and dated PDS/EQM corrections remain in force. PBR common ADSs remain unchanged.

The generated program must restore byte-for-byte to the previous controlled program after removing the single classifier-import change and the read-only observer call. The observer receives copied tuples of security-ID strings. Exact module-origin, commit, corpus, date and comparison-identity checks bind the run.

## Tests and reproduction

31 regression tests passed locally before publication. They exercise real candidate classifications across all 1,751 security-interval boundaries, seven-only changes, PDS/EQM preservation, common/preferred siblings, date/CUSIP/identity/hash tampering, outcome-field rejection, full-inventory coverage, observer immutability and source-seam reversibility.

The reproducible CI entry is `.github/workflows/champion-security-truth-audit-v2.yml`. It checks out the exact audit head, previous classifier `ba74e79490beb8950611b1d17f5d124833b3d91e`, formal economic source `27bb992087182c42c3c051e62bf837895f5d2ab7`, and frozen runtime. It reruns tests, builds the coverage audit, preserves an immutable audit checkpoint, pulls and verifies the exact canonical package, runs the full horizon, computes direct and trailing 5/10/15/20-year metrics, refreshes review priorities, and preserves the replay checkpoint.

Audit and replay outputs are committed under `research/champion-economic-integrity/security-truth/audit-v2/<run_id>-<attempt>/`. An additional 90-day Actions artifact contains logs and evidence. Git checkpoints remain retained after Actions artifact expiry.

Primary-source raw-byte recovery uses bounded access attempts and records unavailable sources explicitly. A successful workflow does not certify complete raw-source retention or close the broader factual review.

## Next checkpoint

Inspect the V2 runner's published `audit/SUMMARY.json` and eventual `replay/controlled/RESULT.json`. Continue factual review using the refreshed complete held/pending inventory, then durable-ranked cases. Preserve unresolved episode/identity questions. Freeze each subsequent factual correction batch before measuring its economic effect. Final production-equivalent classification certification remains open.

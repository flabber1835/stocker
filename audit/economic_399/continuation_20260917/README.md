# Economic audit #399 — continuation evidence, 2026-09-17

Production baseline: aff4461d9af6d4a7367018768fda18d948958b49.
Production tree: 56790bb69b1c65b981ffee94c2a58542916b3b52.

These audit-only tests assert counterexamples on the unchanged baseline. A passing counterexample is evidence of its stated baseline behavior, not a successful remediation or exhaustive economic certification. No production source, live broker account or trading state was changed.

## Probes and retained execution results

| Probe | Ledger | Cases | Result |
|---|---|---:|---|
| test_cash_capability.py | C1 / F6, one capability gap | 8 | passed in 2.09s |
| test_recovery_sse_quarantine.py | F8 | 3 | passed in 1.85s |
| test_rounded_nav.py | F9, both rounding directions | 4 | passed in 3.59s |
| test_leadership_terminal_capability.py | C2 | 2 | passed in 2.58s |
| test_stop_decimal_boundary.py | F10 | 3 | passed in 3.71s |

Runtime: exported locked image, Python 3.12.13. Cash and recovery probes use disposable PostgreSQL 17. The other probes are pure canonical-state/target tests. All external transport is replaced by explicit deterministic fakes or independent arithmetic; credentials are literal audit-only placeholders. Authority callbacks in the recovery probe are explicit pre-satisfied seams.

The host/database campaign recorded separately in #399 used PostgreSQL 16 and completed as Actions run 35277633918: 956 passed in 295.16s. Artifact 10520834605, SHA256 a17491f53de0880cf9ffc1567e1bef9dc4afbde9b0898ae673a1e31cf86bf8a6. The missing receipt-key failures from its predecessor were runner configuration errors.

## Additional unchanged-source regressions

- Broker/execution/cash/performance-quarantine tranche: 289 passed in 40.94s.
- Rolling action-history/retirement/projection/terminal tranche: 228 passed in 530.57s.
- Shared/Wealth Core/V5/Median-5/champion/controller tranche: 1115 passed, 3 expected failures in 213.75s. Expected failures are the existing intentional reference-hash re-pin cases.

Counts may overlap other campaigns and are not added into a unique-case certification total. Detailed local logs and JUnit are retained with the audit bundle. These are test-selection dispositions, not assertions that all functions have been reviewed.

## Reproduction arrangement

Use an exact checkout of the production baseline with its locked image and test dependencies. Keep these probe files together outside production source. Expose the production package, baseline tests, and probe directory to pytest. The PostgreSQL probes require disposable database tooling and the repository test fixture. Set an audit-only publication receipt key of at least 32 bytes when running relevant database regressions. Do not supply live broker credentials.

The original local run used /app for production code, /work/tests for the baseline tests, /work/repo for the baseline repository mirror, and /audit/probes for these files. Environment included PYTHONPATH=/work:/app, SENTINEL_REPO_ROOT=/work/repo, SENTINEL_IN_IMAGE=1, and SENTINEL_IMAGE_SOURCE_REVISION equal to the pinned SHA. Run `python -m pytest /audit/probes -q -s --junitxml=/audit/evidence/probes.xml` in that arrangement.

## Exact original probe SHA256

- test_cash_capability.py: 76bedc547cc55319358d260c55c3a5393a27be017f78c445d0a003c12eb8dd95
- test_recovery_sse_quarantine.py: 07577b86bc56c7ddb29633e58332366246f55f671b3bfd2cc157dff02b15bdb4
- test_rounded_nav.py: 8cfd8852a461e6e2c370a6abc603bcbe7f56ad058a38e2a849c1be03c1d1b52a
- test_leadership_terminal_capability.py: 806dd9954f2df3fadb29be7f5fca7d741dccf68a2936269d3391ee255353e9a4
- test_stop_decimal_boundary.py: 5580b169cd6eb9e3d59c9b0f958b41a33936535a1b289d1fa71a2da3d022f898

## Numbering and scope

C1 and F6 are the same non-fill cash capability and count once. F7 belongs to the uncertain-submit false-cancellation finding in comment 5721828274. The recovery SSE-quarantine finding in comment 5721838114 was corrected from its original concurrent F7 label to F8. C2 is an explicitly unsupported terminal sensor capability. No baseline transition occurred. The audit and remaining coverage ledger stay open.

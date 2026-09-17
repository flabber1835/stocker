# Economic audit #399 — counterexample evidence

Production source: aff4461d9af6d4a7367018768fda18d948958b49.
Ledger: https://github.com/flabber1835/stocker/issues/399.

These audit-only pytest probes assert the observed defects and independent controls. A passing probe demonstrates its recorded counterexample; it does not establish a corrected implementation. No production source change is included.

Use the exact-source sentinel test image built by Actions run 35262421704. Copy the probes into its disposable `/work/tests/sentinel/` directory and invoke pytest from `/work`. The rolling tests use real ephemeral PostgreSQL and the existing explicit source-transport/deployment-certification test fixtures. The budget test exercises the actual canonical adapter and account opening target projection.

Observed local image-filesystem runtime: Python 3.12.13, pandas 3.0.5, numpy 2.4.6, psycopg 3.3.4, exchange_calendars 4.13.2. Executed through a chroot with ephemeral PostgreSQL; Docker isolation applies separately to the GitHub test campaign.

| Probe | Cases | Recorded execution |
| --- | ---: | --- |
| `test_economic_review.py` | 2 | 23.71 s; exact factor 0.5 advances; common quantized factor 0.997123 refuses |
| `test_budget_floor.py` | 1 | 2.49 s; exact 25-share intended budget gives 24 in both canonical and account projection |
| `test_dated_rename.py` | 1 | 17.67 s; valid same-permaticker current-session rename blocks daily advancement |

Historical incidence, aggregate dollar/CAGR impact, NAS operation and actual broker execution are not established by these probes. Full logs, source inventories and test outcome reconciliation are retained by the audit ledger and final evidence bundle.

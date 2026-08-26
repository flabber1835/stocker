# Orion SEC security-type coverage analysis

Archives inspected: **82** (2006q1_form345.zip through 2026q2_form345.zip).

## Executed-buy classification coverage

- Authoritative executed-buy rows with dates: **722**
- Automatically verified common before buy: **573**
- Curated/manual verified common before buy: **143**
- Curated/manual verified non-common before buy: **3**
- Total causally classified before buy: **719/722 (99.58%)**
- Unresolved executed-buy rows: **3**

## Automatic evidence coverage

- Positive common-stock symbols from Form 3/4/5 security-title evidence: **24,764**
- Legacy Sharadar common-stock symbols: **24,611**
- Legacy common-stock ticker coverage: **13,394/24,611 (54.42%)**
- Authoritative executed-buy tickers with any direct-symbol positive evidence: **518/654 (79.20%)**

## Manual evidence admission

- Curated evidence files inspected: **28**
- Admitted exact-buy evidence rows: **149**
- Admitted exact-buy pairs: **146**
- Rejected/non-admitted rows: **1**

## PIT rule

Automatic evidence requires a matching SEC issuer trading symbol and a positive common/ordinary-equity security title. Curated evidence is admitted only for its exact Orion ticker/buy-date pair, with an explicit verified status, a documented causal join, and an evidence date strictly earlier than the decision session. Same-day filings are not admitted without separate session-phase proof. Verified preferred, LP-unit, or other non-common instruments resolve as ineligible. Absence of evidence remains **unknown/ineligible**.

## Interpretation

This report is the executed-buy economic gate, not the final certification. Once unresolved executed buys reach zero, Orion still requires full candidate/session coverage against the same causal evidence boundary before a provenance-retaining `SEC_SECURITY_TYPE_PIT_ONLY` tape can be certified.

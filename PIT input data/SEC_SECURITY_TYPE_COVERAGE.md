# Orion SEC security-type coverage analysis

Archives inspected: **82** (2006q1_form345.zip through 2026q2_form345.zip).

## Coverage

- Positive common-stock symbols from Form 3/4/5 security-title evidence: **24,764**
- Legacy Sharadar common-stock symbols: **24,611**
- Legacy common-stock ticker coverage: **13,394/24,611 (54.42%)**
- Authoritative executed-buy tickers with any positive evidence: **518/654 (79.20%)**
- Executed-buy rows causally covered before buy date: **573/722 (79.36%)**
- Executed-buy rows lacking prior positive evidence: **149**

## PIT rule

A ticker becomes eligible as common stock only after an SEC filing whose issuer trading symbol matches the ticker and whose non-derivative security title positively identifies common/ordinary equity. Preferred, warrant, option, RSU, phantom, and convertible titles are not positive evidence. Absence of evidence is **unknown/ineligible**. Filing-date evidence must be strictly earlier than the Orion decision session.

## Interpretation

This is a coverage diagnostic, not yet a certification. Form 3/4/5 security titles can provide causal positive evidence, but final use depends on whether candidate/session coverage is sufficiently complete. Executed-buy coverage is the first economic materiality gate; full candidate/session coverage remains the promotion gate.

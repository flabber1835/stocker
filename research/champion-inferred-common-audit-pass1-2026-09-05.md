# Research Champion decision-relevant INFERRED_COMMON audit — pass 1

Date: 2026-09-05
Status: diagnostic / NOT CERTIFIED

## Source replay

Corrected historical-security-type replay:
- Actions run: 34007704385
- artifact: champion-corrected-classification-34007704385-1
- artifact id: 9981966560
- artifact digest: sha256:4860751ea45f7480f785e927bc4cebba1c8be3783b354d186ce059d6fb09a841
- corrected result: 20.09% 20-year CAGR, ending multiple 38.91x, max drawdown -23.83%

Isolated attribution run:
- Actions run: 34007737168
- PDS-only: effectively identical to reviewed baseline (~16.78% CAGR)
- EQM-only: effectively identical to fully corrected replay (~20.09% CAGR)

Conclusion from causal attribution: the large reviewed-to-corrected performance change is caused by the EQM classification correction and its downstream path dependence; PDS contributes essentially zero.

## Decision-relevant inferred-common surface

The corrected artifact generated `decision-relevant-inferred-common-audit.csv`.

Counts:
- total decision-relevant INFERRED_COMMON securities: 1,492
- HELD_OR_PENDING: 83
- DURABLE_RANKED: 28
- LEADERSHIP_SIGNAL: 1,298
- RANKING_INPUT: 83

Immediate audit priority is HELD_OR_PENDING because these names have direct realized-path contact. Leadership-only names remain important because the proven June-2020 controller example shows that a never-held security can affect aggregate leadership and therefore allocation.

## First authority checks

This pass began with high-contact and structurally suspicious/legacy identities, using SEC filings and other contemporaneous/public issuer evidence where available. No new EQM-like limited-partnership/common-unit defect has yet been proven in this first batch.

Examples checked or partially checked:

- Valspar Corp, CUSIP 920355104: SEC/13F evidence describes the security as common stock.
- Eaton Vance Corp, CUSIP 278265103: SEC Schedule 13G identifies the class as common stock.
- Mirant Corp, CUSIP 60467R100: SEC filing identifies common stock, par value $0.01 per share.
- Dollar Thrifty Automotive Group, CUSIP 256743105: SEC tender-offer filing identifies common stock, $0.01 par value.
- GenOn Energy, CUSIP 37244E107: SEC Schedule 13G identifies common stock.
- SailPoint Technologies Holdings, CUSIP 78781P105: SEC Schedule 13G identifies common stock.
- Valeant Pharmaceuticals International, CUSIP 91911X104: SEC Schedule 13D identifies common stock.
- Unit Corp, CUSIP 909218109: SEC Schedule 13G / 13F evidence identifies common stock.
- Patriot Coal Corp, CUSIP 70336T104: SEC 13F evidence identifies common stock.
- Silvergate Capital Corp, CUSIP 82837P408: SEC Schedule 13G identifies common stock.
- Digital Ally / Kustom Entertainment identity chain, including CUSIP 25382P208 / later 25382T-series: SEC/issuer evidence identifies common stock and a later 2026 corporate rename/ticker change to KUST. This is an identity-continuity item to retain in the audit, but no non-common interval has been established.

These checks are evidence-gathering only. A present-day or later filing cannot by itself certify an earlier interval; certification requires authority that covers the relevant historical admitted interval.

## Important methodological finding

Vendor/13F labels such as `Common Stock` are not sufficient by themselves. SEC 13F tables can label limited-partnership units as common stock (for example, partnership-unit instruments can appear in the `COMMON STK` category while the issuer/class description explicitly says `LP common units` or `limited partner interests`). Therefore the audit must inspect issuer/class legal descriptions, not merely the coarse asset-class field. This is exactly the failure mode demonstrated by EQM.

## Next executable steps

1. Complete authoritative interval checks for all 83 HELD_OR_PENDING inferred-common securities, prioritizing old/renamed identities, multiple-CUSIP chains, energy/resource structures, ADR/foreign structures, REIT/trust conversions, and securities whose legal form changed during the replay window.
2. For every candidate with any partnership/trust/unit/preferred/depositary ambiguity, obtain contemporaneous SEC/issuer/exchange evidence covering the actual admitted dates.
3. Add only proven historical corrections to the dated correction ledger; do not infer corrections from name similarity.
4. Re-run the exact frozen Champion replay for every newly proven correction.
5. After held/pending closure, audit leadership-only names that have the largest recent-leadership-session counts and/or rank-1 contact, because these can alter the controller without ever being held.
6. Run bounded one-name and small-basket classification perturbations on decision-relevant inferred-common names as a robustness diagnostic. These perturbations are not historical truth and must remain labeled NOT CERTIFIED.

## Current interpretation

The 20.09% result is materially stronger than the reviewed 16.78% baseline, but it is not yet certifiable because 1,492 decision-relevant classifications still rest on inference rather than complete historical authority. The key practical question is now narrower: whether any of the 83 direct-contact inferred-common names, or the highest-impact leadership-only names, contain another EQM-like legal-form error capable of changing the realized path.
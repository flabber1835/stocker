# Final security-truth integration and contradiction audit

Date: 2026-09-06

Base: `5b9d9ea2e378044f49d217fe311b36b45c73124c`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

## Scope

This integration retains the completed P0 fresh-path delta, all ten P1 durable-ranked shard reviews and applicable cleanups, all four P2 leadership reviews and applicable cleanups, and both P3 ranking/base reviews plus the ranking cleanup. The source reviews cover P0 held/pending, 442 P1 durable-ranked cases, 182 P2 leadership cases, and 61 P3 ranking/base cases.

All cleanup worklists are closed. There are zero remaining factual security-type unresolved cases in P0/P1/P2/P3.

No replay, backtest, runtime change, strategy change, or economic change was performed by this integration.

## Precedence

For a security reviewed in a cleanup artifact, the cleanup decision supersedes the earlier unresolved decision from its parent shard. Identity/CUSIP anomalies remain metadata findings and do not override an authoritatively established decision-period legal type.

## Cross-shard contradiction audit

### REIT / beneficial-interest cases

The apparent `GPT2` conflict is not a conflict after canonical-interval review. `GPT2` covers 2015-04-14 through 2015-08-05, when Gramercy Property Trust Inc. was a Maryland corporation and its NYSE security was common stock. The later December 2015 merger converted that corporate common stock into common shares of beneficial interest of a Maryland REIT after the canonical interval. `GPT2` therefore remains `common`.

The reviewed trust-beneficial-interest cases `PRET`, `PLD1`, `OPITQ`, `SFR1`, `EOP`, and `IHT` remain `non_common` under the adopted trust-interest policy. Corporate REIT common-stock cases remain `common`. No cross-shard correction is required for `GPT2`.

### LLC / unit-form cases

`LB` remains `common`: its exact public class is authoritatively described both as Class A shares representing LLC interests and as Class A common stock, and the review adjudicated it as the issuer's residual publicly traded common-equity class. Partnership/common-unit and LLC-unit cases such as `LINEQ` and `SDLPQ` remain `non_common`. No contradiction remains after legal-class-specific review.

### Hybrid cases

`BEPC` remains `non_common`. Its public Class A exchangeable subordinate voting shares are redeemable/exchangeable one-for-one for BEP LP units or cash and are distinguished by the issuer from its residual common-equity class. `FMX` remains `common` under the held/pending integration adjudication because its bundled BD unit components are equity-share series rather than a partnership/trust/warrant instrument.

## Transition-boundary audit

- `AM`: `non_common` through 2019-03-12; `common` from 2019-03-13.
- `CBDBY`: preferred-share ADS `non_common` through 2020-03-04; common-share ADS `common` from 2020-03-05.
- `ERF`: trust units `non_common` through 2010-12-31; corporate shares `common` from 2011-01-03.
- `OBE`: trust units `non_common` through 2010-12-31; corporate shares `common` from 2011-01-03.
- `PVX`: trust units `non_common` through 2010-12-31; corporate shares `common` from 2011-01-03.
- `PDS`: for decision-session classification, retain `non_common` through 2010-06-01 and `common` from 2010-06-02. The legal conversion completed June 1, but issuer evidence states NYSE common-share trading was to commence June 2 concurrently with delisting of the trust units. This session boundary supersedes the shard-03 legal-effective interval that started common on June 1.

The PDS boundary is an integration adjudication of session semantics, not a new security-type ambiguity.

## Identity-contamination audit

Known cases including `ROSEQ`, `ZNB`, `NIKI`, `HCR1`, `THOR1`, `UNTCQ`, `VTNRQ`, and `BPZRQ` retain identity/CUSIP hygiene notes separately from factual type. None remains unresolved for classification.

## Result

Classification truth scrub status: **CLOSED**.

Remaining factual security-type unresolved cases: **0**.

The next stage is economic-semantic alignment to Production. No performance replay should be run until those economic semantics are frozen.
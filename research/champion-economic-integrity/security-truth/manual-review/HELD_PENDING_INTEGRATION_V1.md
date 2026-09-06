# Held/pending security-type integration V1

Date: 2026-09-06

Status: `HELD_PENDING_TYPE_CLASSIFICATION_CLOSED_IDENTITY_HYGIENE_OPEN`

This checkpoint integrates the five independent held/pending review shards against the production-equivalent perfect-classification contract. It does not run an economic replay and does not certify final Champion performance.

## Inputs

All five shards branched from checkpoint `428721fd4a7494df477c2c9cd3d94ded1c1f5d37` and changed only their assigned JSON/Markdown review artifacts. The integration branch starts from later parent checkpoint `ab96ca68d6e546cc88b9801878ae7848108a9f7b`, which adds only the retained seven-correction diagnostic replay evidence.

Shard heads:

- shard 1: `e278b020240a04ca8fcdf2be28c1c2c58c43ab8b`
- shard 2: `b9dde98f123ed94e04ff7540b00c5125938b9121`
- shard 3: `1e234e386303a9bb7d25e43fffa7aab6466a0703`
- shard 4: `08024c92781690744d02e3ee05b3527c86cc423f`
- shard 5: `6b56e57b8d2ceb1f3f3bc573f860b6dd6a1dfdad`

The five shards cover the 73 cases remaining after the earlier held/pending review batch. Their first-pass result was 68 common, zero non-common, zero interval splits and five conservative unresolved cases: FMX, HCR1, THOR1, UNTCQ and VTNRQ.

## Integration rule

The economic contract asks for the factual security type on each historical decision session. A stale, predecessor, successor or erroneous CUSIP that appears in a canonical aggregate identity row does not by itself make the historical type unresolved when the security actually trading throughout the decision interval is independently and continuously identified and its legal class is unambiguous.

Identity anomalies remain recorded. They are not silently discarded. This separates two questions:

1. `type_classification_status`: what security type should Wealth Core have received on the decision sessions?
2. `identity_hygiene_status`: is every historical identifier attached to the canonical episode fully reconciled?

This distinction is required because several already-resolved shard cases contain predecessor/successor CUSIPs outside their decision interval. Requiring every aggregate CUSIP to be active and independently authenticated inside the target interval would apply inconsistent standards across cases.

## Adversarial resolution of the five first-pass unresolved cases

### FMX — common

CUSIP `344419106` is the FEMSA BD Unit ADS. A 2006 SEC Schedule 13D/A states that each ADS represents one BD Unit and each BD Unit consists of one Series B share, two Series D-B shares and two Series D-L shares. FEMSA filings describe these series as its capital/common stock structure. The ADS therefore represents a bundle composed exclusively of common-equity share series. It is not preferred stock, a partnership interest, a trust unit, warrant or right.

Decision: `common` for 2006-07-05 through 2026-07-31.

Primary evidence: `https://www.sec.gov/Archives/edgar/data/1061736/000090342306000386/femsa13da6_0410.htm`.

### HCR1 — common; predecessor identity note remains

The canonical decision interval is 2006-07-05 through 2007-12-21. SEC voting/holdings records in that interval identify Manor Care, ticker HCR, CUSIP `564055101`, as common stock. The additional older CUSIPs are historical identity-chain metadata and do not create a type ambiguity on the target interval.

Decision: `common` for the full canonical interval.

Identity hygiene: predecessor CUSIP `421937103` remains less strongly authenticated than the target-period CUSIP and should stay on an identity-lineage follow-up list.

Primary target-period evidence: `https://www.sec.gov/Archives/edgar/data/819978/000118811208002862/t63733l_n-px.htm`.

### THOR1 — common; predecessor identity note remains

The canonical interval is 2008-08-05 through 2015-10-07. SEC-filed holdings repeatedly identify Thoratec Corp CUSIP `885175307` as common stock throughout that interval. The unexplained predecessor `885175109` is not needed to establish the legal class of the security trading during the decision interval.

Decision: `common` for the full canonical interval.

Identity hygiene: retain `885175109` as a predecessor-CUSIP lineage follow-up.

Primary evidence includes SEC Form 13F tables identifying `885175307` as Thoratec Common Stock.

### VTNRQ — common; canonical stale-CUSIP contamination proven

The target interval is 2021-05-27 through 2023-04-25. SEC filings identify Vertex Energy CUSIP `92534K107` as common stock, and a DTCC corporate-action record binds predecessor World Waste CUSIP `981517105` to Vertex. Separate SEC evidence proves canonical CUSIP `92861H107` belonged to Voice Powered Technology International in 2003, not the Vertex/World Waste lineage.

Decision: `common` for the full target interval.

Identity hygiene: `92861H107` is recorded as unrelated stale CUSIP contamination in the aggregate canonical identity metadata; it must not be used as evidence about Vertex's security class.

Primary contrary-identity evidence: `https://www.sec.gov/Archives/edgar/data/890447/000101738603000090/vpt_2003nt10q.htm`.

### UNTCQ — type common; canonical identity metadata remains open

The target interval is 2006-07-05 through 2016-12-28. SEC/issuer records repeatedly identify Unit Corporation's listed equity as common stock under CUSIP `909218109` through the target period. The issuer's later Form 8937 identifies `909218109` as the old stock and different CUSIPs after the 2020 restructuring. No authoritative Unit binding for aggregate CUSIP `909218208` was found.

Decision: `common` for the target interval because the decision-period security is directly and continuously bound to common stock.

Identity hygiene: `909218208` remains an unresolved canonical metadata anomaly. This is not represented as a proven Unit predecessor or successor and remains open for corpus identity cleanup.

## Integrated held/pending result

For the 73 parallel-shard cases after adversarial integration:

- common: 73
- non-common: 0
- interval splits: 0
- type unresolved: 0

Combined with the earlier eight common confirmations and the two held/pending names among the seven established non-common corrections (`GOLLQ` and `CIG`), the retained pre-correction held/pending inventory of 83 cases now has a deterministic type classification for every case.

This closes **security-type classification** for the held/pending layer. It does not claim that every historical CUSIP in the canonical identity topology is clean. Identity-hygiene follow-up remains for HCR1, THOR1, UNTCQ and VTNRQ, and should be fixed in the corpus/identity audit without reopening the decision-period type unless contrary class evidence is found.

## No economic claim

No economic replay is authorized by this integration checkpoint. The seven-correction replay retained at `ab96ca68d6e546cc88b9801878ae7848108a9f7b` remains diagnostic only. The final production-equivalent backtest waits until the broader decision-relevant security-type scrub and remaining production-economic semantics work are complete.

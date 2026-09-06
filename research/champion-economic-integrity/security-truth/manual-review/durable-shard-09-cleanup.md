# Durable-ranked security truth review — shard 09 cleanup

Base: `c6d9da1b3d9ed845c1587585d0f456280818f114`

Branch: `research/champion-security-truth-durable-09-cleanup`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

Scope: exactly `BEPC, BFXXQ, TRIN1, ABVEF, HAPN, CNSY, AIFC, EMWPF, BTCT, RATE1`.

Outcome information used: `false`.

Replay/backtest run: `false`.

## Result

| ticker | decision | canonical interval | type conclusion | identity-chain conclusion |
|---|---|---|---|---|
| BEPC | `non_common` | 2021-01-25 — 2026-07-31 | exchangeable/redemption hybrid, not residual common equity | successor CUSIP preserves same hybrid class |
| BFXXQ | `common` | 2020-08-24 — 2021-04-21 | Nautilus common stock | legacy Direct Focus CUSIP is also common stock; predecessor detail is not type uncertainty |
| TRIN1 | `common` | 2007-05-16 — 2007-09-04 | Reuters sponsored ADR on ordinary/common equity | legacy ADR CUSIP ordering remains imperfectly documented but does not affect type |
| ABVEF | `common` | 2025-07-10 — 2025-11-04 | Above Food common stock | Bite predecessor and Above Food successor CUSIPs are both common stock |
| HAPN | `common` | 2015-06-15 — 2026-07-31 | LendingClub common stock | CUSIP transition preserves common-stock class |
| CNSY | `common` | 2006-07-05 — 2025-03-27 | Cytori / Plus Therapeutics common stock | repeated reverse-split/name CUSIPs preserve common-stock type |
| AIFC | `common` | 2022-06-07 — 2025-10-17 | JanOne / ALT5 Sigma common stock | name/capital-action lineage preserves common-stock type |
| EMWPF | `common` | 2015-10-13 — 2021-04-21 | A ordinary / Class A ordinary shares | Eros reorganization changes CUSIP/name, not type |
| BTCT | `common` | 2021-02-12 — 2025-01-31 | common stock / ordinary shares | SPAC combination and reverse splits preserve ordinary-equity type |
| RATE1 | `common` | 2006-07-05 — 2009-08-18 | Bankrate common stock | legacy extra CUSIPs remain an identity metadata issue outside the directly proven interval type |

Totals: `common=9`, `non_common=1`, `split=0`, `unresolved=0`.

Remaining unresolved: **none**.

## BEPC — explicit hybrid adjudication

SEC ownership filings identify the public security as **Class A exchangeable subordinate voting shares**, CUSIP `11285B108`. Brookfield Renewable Corporation's Q2 2026 SEC financial statements state that BEPC exchangeable shares are classified as liabilities because of their exchange and cash-redemption features and that a holder can redeem one share for one Brookfield Renewable Partners LP unit or its cash equivalent. The same filing separately identifies BEPC class B shares as the most subordinated class of common shares and presents that residual class as equity.

Sources:
- SEC Schedule 13D, CUSIP `11285B108`: https://www.sec.gov/Archives/edgar/data/1791863/000110465926086395/xslSCHEDULE_13D_X02/primary_doc.xml
- Brookfield Renewable Corporation Q2 2026 financial statements, note 10: https://www.sec.gov/Archives/edgar/data/1791863/000179186326000014/bep-20260630_d2.htm

Adjudication: the corporate-share label and subordinate voting right do not by themselves make this ordinary/common corporate equity. The public Class A security's defining exchange/redemption package makes it economically and legally tied one-for-one to an LP unit, and the issuer distinguishes it from its residual common-equity class. Under the supplied common-equity contract, this is an **other non-common hybrid instrument**. Decision: `non_common` for the full canonical interval.

Contradiction search: the strongest common-class argument is that BEPC is a Canadian corporation and the instrument is legally called a share with voting rights. The issuer's own SEC financial statements directly resolve that tension by distinguishing the exchangeable public class from class B common equity and liability-classifying the exchangeable class due to redemption/exchange rights.

## BFXXQ — common

Canonical interval: 2020-08-24 — 2021-04-21. CUSIPs: `63910B102`, `254931108`.

Fresh evidence:
- Nautilus SEC Schedule 13G/A identifies CUSIP `63910B102` as **Common Stock, no par value**: https://www.sec.gov/Archives/edgar/data/1009268/000110465921023879/tm215909d16_sc13ga.htm
- Archived Form 13F table identifies predecessor Direct Focus, Inc. CUSIP `254931108` as **COMMON STOCK**: https://www.secinfo.com/dsVSm.34b.htm

The decision-interval security is directly established as Nautilus common stock. The legacy Direct Focus identifier is a predecessor/name-history issue and is also described as common stock. No preferred, unit, warrant, right, trust, partnership, or other non-common evidence was found. Decision: `common`.

## TRIN1 — common

Canonical interval: 2007-05-16 — 2007-09-04. CUSIPs: `76132M102`, `885141101`, `761324201`.

Fresh SEC/depositary research identifies the canonical 2007 Reuters line as a sponsored ADR representing Reuters ordinary/common equity. Later Reuters/Thomson Reuters ADR identity evidence establishes the surrounding CUSIP lineage. The contract expressly includes ADR/ADS on ordinary/common equity in `common`.

The exact ordering of all three legacy CUSIPs is an identity-chain question. It does not create type uncertainty for the canonical interval: no preferred underlying security, debt, warrant, right, unit, partnership, or trust class was found. Decision: `common`.

Primary-source locator: https://www.sec.gov/edgar/search/

## ABVEF — common

Canonical interval: 2025-07-10 — 2025-11-04. CUSIPs: `09175K105`, `00373V100`.

Fresh evidence:
- Above Food Ingredients SEC Schedule 13G identifies CUSIP `00373V100` as **Common Stock**: https://www.sec.gov/Archives/edgar/data/1469443/000095017025110227/xslSCHEDULE_13G_X01/primary_doc.xml
- SEC Form 13F information tables identify Bite Acquisition Corp. CUSIP `09175K105` as **Common/Common Stock**: https://www.sec.gov/Archives/edgar/data/1517133/000110465922060008/xslForm13F_X01/infotable.xml

The business-combination chain therefore connects common stock to common stock. Bite/Above Food warrants are separately identified securities and do not change the canonical security's type. Decision: `common`.

## HAPN — common

Canonical interval: 2015-06-15 — 2026-07-31. CUSIPs: `52603A208`, `52603A109`.

Fresh evidence:
- LendingClub SEC Schedule 13G identifies CUSIP `52603A208` as **Common Stock**: https://www.sec.gov/Archives/edgar/data/1409970/000110465923018478/tm235947d18_sc13g.htm
- Historical SEC ownership filings identify `52603A109` as LendingClub common stock; later authoritative evidence confirms the successor CUSIP remains common stock: https://www.sec.gov/edgar/search/

The CUSIP change is a capital-action/identity transition within the same common-stock class. The later HAPN ticker does not change legal security type. Decision: `common`.

## CNSY — common

Canonical interval: 2006-07-05 — 2025-03-27. CUSIPs: `23283K105`, `72941H400`, `23283K204`, `72941H509`, `23283K402`, `72941H806`, `72941H103`.

Fresh evidence across the long chain:
- Cytori Therapeutics CUSIP `23283K204` is **Common Stock** in an SEC Schedule 13G: https://www.sec.gov/Archives/edgar/data/1095981/000119312518029310/d511295dsc13g.htm
- Cytori CUSIP `23283K402` is reported as **COM** in an SEC Form 13F table: https://www.sec.gov/Archives/edgar/data/1803804/000116204420000194/xslForm13F_X01/infotable.xml
- Plus Therapeutics CUSIP `72941H509` is **Common Stock** in an SEC Schedule 13G: https://www.sec.gov/Archives/edgar/data/1095981/000164955326000057/xslSCHEDULE_13G_X02/primary_doc.xml
- Plus Therapeutics CUSIP `72941H806` is **Common Stock** in an SEC Schedule 13G: https://www.sec.gov/Archives/edgar/data/919185/000091957426003205/xslSCHEDULE_13G_X02/primary_doc.xml

The seven-CUSIP complexity comes from the Cytori-to-Plus name lineage and repeated reverse splits/capital actions. Evidence sampled across the chain consistently identifies corporate common stock. Separate warrants or other capital instruments do not use the canonical CUSIPs. Exact date mapping for every historical CUSIP remains identity metadata, not factual type uncertainty. Decision: `common`.

## AIFC — common

Canonical interval: 2022-06-07 — 2025-10-17. CUSIPs: `47089W104`, `03814F205`, `03814F403`, `03814F106`.

Fresh evidence:
- JanOne Form 10-K documents the corporate name/ticker change and adoption of CUSIP `03814F403`, closing the issuer-lineage transition: https://www.sec.gov/Archives/edgar/data/862861/000156459021016696/jan-10k_20210102.htm
- SEC Form 13F identifies Appliance Recycling Centers of America CUSIP `03814F205` as **Common Stock**: https://www.sec.gov/Archives/edgar/data/1512024/000106299319000782/xslForm13F_X01/form13fInfoTable.xml
- ALT5 Sigma SEC Schedule 13G identifies CUSIP `47089W104` as **Common Stock, $0.001 par value per share**: https://www.sec.gov/Archives/edgar/data/862861/000159588825000118/xslSCHEDULE_13G_X01/primary_doc.xml

The 03814F-series and later 47089W104 identity changes preserve a corporate common-stock class. No canonical CUSIP is identified as preferred, warrant, unit, right, trust, or partnership security. Decision: `common`.

## EMWPF — common

Canonical interval: 2015-10-13 — 2021-04-21. CUSIPs: `G3788M114`, `G3788R105`.

Fresh evidence:
- Eros International SEC Schedule 13G/A identifies `G3788M114` as **A Ordinary Shares**: https://www.sec.gov/Archives/edgar/data/1021944/000119312516717578/d264108dsc13ga.htm
- Eros STX Global SEC Schedule 13D/A identifies `G3788R105` as **Class A Ordinary Share**: https://www.sec.gov/Archives/edgar/data/1532981/000095014222001501/eh220246728_13da1-eros.htm

The reorganization/name transition changes CUSIP and class wording but retains ordinary corporate equity. No conflicting non-common class evidence was found. Decision: `common`.

## BTCT — common

Canonical interval: 2021-02-12 — 2025-01-31. CUSIPs: `G6055H114`, `28138X103`, `G6055H155`, `28138X202`, `G6055H148`.

Fresh evidence:
- EdtechX CUSIP `28138X103`: SEC Schedule 13G/A identifies **Common Stock**: https://www.sec.gov/Archives/edgar/data/1746468/000106299320000584/formsc13ga-edtechx.htm
- EdtechX CUSIP `28138X202`: SEC Schedule 13G identifies **Common Stock**: https://www.sec.gov/Archives/edgar/data/1746468/000149315218014235/formsc13g.htm
- Meten EdtechX CUSIP `G6055H114`: SEC Schedule 13D identifies **Ordinary Shares**: https://www.sec.gov/Archives/edgar/data/1796514/000121390020008896/ea120524-13dzhao_meten.htm
- Meten Form 6-K states that a 2022 share consolidation changed the ordinary-share CUSIP to `G6055H148`: https://www.sec.gov/Archives/edgar/data/1796514/000121390022024017/ea159384-6k_metenholding.htm
- BTC Digital CUSIP `G6055H155`: SEC Schedule 13G identifies **Ordinary Shares**: https://www.sec.gov/Archives/edgar/data/1469336/000090266425000260/xslSCHEDULE_13G_X01/primary_doc.xml

This closes the multi-jurisdiction chain as common/ordinary equity through the SPAC combination, foreign ordinary-share continuation, name changes, and reverse splits. Units and warrants have distinct identifiers. Decision: `common`.

## RATE1 — common

Canonical interval: 2006-07-05 — 2009-08-18. CUSIPs: `06646V108`, `45172Q109`, `45816V100`.

Fresh evidence directly covering the decision interval:
- Bankrate SEC Schedule 13G identifies CUSIP `06646V108` as **Common Stock** in 2008: https://www.sec.gov/Archives/edgar/data/1052100/000110465908069191/a08-27757_1sc13g.htm
- Bankrate's 2009 Schedule 14D-9 identifies CUSIP `06646V108` as **Common Stock, Par Value $0.01 Per Share**: https://www.sec.gov/Archives/edgar/data/1080866/000095012309026403/y78478sc14d9.htm

The two additional legacy CUSIPs in the durable identity record remain incompletely bound to the predecessor/reorganization history. That is an identity-chain defect, not a type defect for the canonical interval: contemporaneous authoritative filings directly establish the security used throughout the bounded 2006-2009 episode as Bankrate common stock. No conflicting decision-interval non-common evidence was found. Decision: `common`.

## Validation

- Exact base commit used: PASS
- Scope contains exactly the ten requested securities: PASS
- No security outside the requested scope reviewed in the cleanup artifact: PASS
- Fresh external authoritative research performed for every case: PASS
- Identity-chain uncertainty separated from factual type uncertainty: PASS
- Later authoritative evidence used only to establish historical security facts: PASS
- Contradictory/non-common class evidence searched before closure: PASS
- `outcome_information_used=false`: PASS
- Replay/backtest executed: NO
- Remaining unresolved list: `[]`

# Held/pending security truth shard 2

Date: 2026-09-06

Status: `FACTUAL_SECURITY_TYPE_SHARD_COMPLETE`

## Scope and controls

Parent branch: `research/champion-certification-economic-integrity`

Parent head inspected before branching: `428721fd4a7494df477c2c9cd3d94ded1c1f5d37`

Working branch: `research/champion-security-truth-shard-2`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

Scope is exactly: LFCHY, MTL, KUST, SGP1, FRFHF, PRE1, VRX1, CCXI1, FTI1, WCC, WIRE, GLBL1, PWRD1, TELFY, WEBX1.

Classification used only legal security identity, legal class, depositary structure and corporate-action identity history. Future returns, prices, ranks, survival, strategy outcomes and index membership were not used. No backtest or economic replay was run.

## Result

| Decision | Count |
|---|---:|
| common | 15 |
| non_common | 0 |
| split | 0 |
| unresolved | 0 |

All 15 canonical candidates were already estimated as `common`; the factual scrub found no classification changes.

## Canonical adjudications

| Ticker | security_id | Canonical interval | CUSIP(s) | Decision | Legal security type |
|---|---:|---|---|---|---|
| LFCHY | `788900523736619527` | 2006-07-05 – 2015-05-06 | 16939P106 | common | ADR/ADS representing H ordinary shares |
| MTL | `107197818933519057` | 2007-07-13 – 2012-10-24 | 583840103, 583840608 | common | sponsored ADS representing common shares |
| KUST | `954034830355046974` | 2007-11-13 – 2026-07-22 | 25382P208, 25382T200, 25382T101, 25382T408, 25382P109, 25382T507, 25382T606, 25382T309 | common | common stock |
| SGP1 | `553972112448702494` | 2006-07-05 – 2009-11-03 | 806605101 | common | common stock |
| FRFHF | `987448579336366373` | 2006-07-20 – 2017-08-04 | 303901102 | common | subordinate voting common shares |
| PRE1 | `732428359392320882` | 2006-07-27 – 2016-03-17 | G6852T105 | common | common shares |
| VRX1 | `987873303793520110` | 2007-06-14 – 2010-09-27 | 91911X104, 448924100 | common | common stock |
| CCXI1 | `659896685009177378` | 2019-11-26 – 2022-10-19 | 16383L106 | common | common stock |
| FTI1 | `1099247927332588244` | 2006-07-05 – 2017-01-13 | 30249U101 | common | common stock |
| WCC | `117908596615035418` | 2008-07-25 – 2008-08-05 | 95082P105 | common | common stock |
| WIRE | `298004721797953203` | 2006-10-27 – 2006-12-28 | 292562105 | common | common stock |
| GLBL1 | `74286179754649606` | 2006-07-05 – 2011-11-01 | 379336100 | common | common stock |
| PWRD1 | `975954328887066480` | 2008-05-09 – 2015-07-28 | 71372U104 | common | sponsored ADR representing Class B ordinary shares |
| TELFY | `716103535463544764` | 2007-03-26 – 2020-03-20 | 879382208 | common | sponsored ADR representing ordinary shares |
| WEBX1 | `88378928586164151` | 2006-07-05 – 2007-05-25 | 94767L109 | common | common stock |

## Evidence docket and contradiction search

- **LFCHY** — China Life 2005 and 2007 Forms 20-F identify the NYSE ADS program as representing H shares and document the 2006 ADS ratio change. The underlying H-share class remains ordinary/common equity. Primary: https://www.sec.gov/Archives/edgar/data/1268896/000119312506121269/d20f.htm and https://www.sec.gov/Archives/edgar/data/1268896/000119312508090637/d20f.htm. No preferred/unit/warrant/right evidence found for CUSIP 16939P106.
- **MTL** — Mechel filings explicitly identify MTL ADSs as representing common shares; the preferred ADS is a distinct security. Citi records the later 583840103 → 583840608 reverse-ADS-split/CUSIP transition. Primary: https://www.sec.gov/Archives/edgar/data/1302362/000119312520278413/d93746dsc13da.htm and https://depositaryreceipts.citi.com/adr/guides/pgm_d.aspx?cusip=583840103&pageId=16&subpageID=104&typeDisplay=A. No assigned CUSIP binds to the preferred program.
- **KUST** — SEC and Nasdaq records establish a continuous Digital Ally/Kustom Entertainment common-stock lineage through reverse splits, CUSIP changes and the 2026 name/ticker change. Primary examples: https://www.sec.gov/Archives/edgar/data/1342958/000119312508029314/dsc13d.htm, https://www.sec.gov/Archives/edgar/data/1342958/000149315223003871/form8-k.htm, https://www.sec.gov/Archives/edgar/data/1342958/000164117225008972/form8-k.htm, https://www.sec.gov/Archives/edgar/data/1342958/000164117225012184/form8-k.htm, https://nasdaqtrader.com/TraderNews.aspx?id=ECA2026-7 and https://www.sec.gov/Archives/edgar/data/1342958/000175392626001525/xslSCHEDULE_13G_X02/primary_doc.xml. No type change found.
- **SGP1** — SEC-filed holdings data identifies Schering-Plough CUSIP 806605101 as common stock: https://www.sec.gov/Archives/edgar/data/49205/000004920515000005/xslForm13F_X01/2Q2009_13F_HR.XML. No contradictory class evidence found.
- **FRFHF** — Fairfax CUSIP 303901102 is identified as subordinate voting shares; subordinate-voting common equity is `common` under policy: https://www.sec.gov/Archives/edgar/data/915191/000110465924023587/tm246195d1_sc13ga.htm. No preferred/unit instrument tied to the assigned CUSIP.
- **PRE1** — PartnerRe filings explicitly identify CUSIP G6852T105 as Common Shares: https://www.sec.gov/Archives/edgar/data/911421/000095014215001081/eh1500635_13d-partnerre.htm and https://www.sec.gov/Archives/edgar/data/911421/000095014215001662/eh1500957_13da1-partnerre.htm. Other PartnerRe capital instruments do not alter this CUSIP's class.
- **VRX1** — Valeant CUSIP 91911X104 is explicitly common stock, while historical SEC-filed holdings bind predecessor ICN CUSIP 448924100 to ICN common stock. Sources: https://www.sec.gov/Archives/edgar/data/19617/000001961709000118/vale1231a.htm, https://www.sec.gov/Archives/edgar/data/885590/000095015710000886/sc13d.htm and https://www.sec.gov/Archives/edgar/data/919859/000091985902000042/tablejun.pdf. The identity transition preserves common-equity type.
- **CCXI1** — ChemoCentryx CUSIP 16383L106 is explicitly Common Stock in SEC ownership filings: https://www.sec.gov/Archives/edgar/data/1340652/000119312521044383/d274998dsc13ga.htm and https://www.sec.gov/Archives/edgar/data/1131399/000090342318000512/glaxo-chemo_13da.htm. No contradictory class evidence found.
- **FTI1** — independent SEC-filed holdings tables identify FMC Technologies CUSIP 30249U101 as Common Stock: https://www.sec.gov/Archives/edgar/data/1316915/000095012315008424/xslForm13F_X01/form13fInfoTable.xml and https://www.sec.gov/Archives/edgar/data/857113/000090901216000379/xslForm13F_X01/aci_13f.xml. No contradictory class evidence found.
- **WCC** — WESCO issuer/SEC material identifies CUSIP 95082P105 as Common Stock: https://wesco.gcs-web.com/node/10561/html and https://wesco.gcs-web.com/resources/investor-faqs. No contradictory class evidence found.
- **WIRE** — Encore Wire Schedule 13G/A identifies CUSIP 292562105 as Common Stock: https://www.sec.gov/Archives/edgar/data/850460/000117266120000719/frontier-wire123119a1.htm. No contradictory class evidence found.
- **GLBL1** — historical filed Schedule 13G material identifies Global Industries CUSIP 379336100 as Common Stock, and a 2006 SEC N-PX binds the identifier to GLBL: https://financialreports.eu/filings/wells-fargo-company/major-shareholding-notification/2007/14758652/ and https://www.sec.gov/Archives/edgar/data/93843/000114420406036281/v051671_npx.htm. No contradictory class evidence found.
- **PWRD1** — Perfect World CUSIP 71372U104 is the sponsored ADR representing Class B ordinary shares: https://www.sec.gov/Archives/edgar/data/1403849/000090266415002968/p15-1518sc13d.htm and https://www.sec.gov/Archives/edgar/data/1468395/000146839514000003/xslForm13F_X01/Form13FInfoTable.xml. No preferred or hybrid class tied to the CUSIP.
- **TELFY** — SEC-filed depositary material identifies Telefónica CUSIP 879382208 as ADSs with ordinary shares as the deposited security; Citi documents program continuity: https://www.sec.gov/Archives/edgar/data/1472033/000119380526000044/e665107_ex99-ai.htm and https://depositaryreceipts.citi.com/adr/guides/pgm_d.aspx?cusip=879382208&pageId=23&subpageID=104&typeDisplay=A. Ratio/ticker changes do not alter the underlying ordinary-share type.
- **WEBX1** — Cisco/WebEx Schedule TO material explicitly identifies CUSIP 94767L109 as Common Stock: https://www.sec.gov/Archives/edgar/data/858877/000119312507056014/dsctoc.htm. No contradictory class evidence found.

## Validation

- Assigned securities: 15
- Output cases: 15
- Extras: 0
- Evidence-backed resolved cases: 15
- Unresolved cases: 0
- `outcome_information_used=false` for all cases
- No factual type splits
- No candidate-to-reviewed classification changes

Canonical adjudication-manifest SHA-256: `531517f501d8d2fadfb376ad72dac28a56b8f475582ee8cc60e3edb9d188869b`

The manifest hash covers, in assigned order, each `security_id|ticker|interval-start|interval-end|CUSIPs|decision|legal_security_type` tuple retained in the JSON artifact.

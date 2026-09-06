# Leadership shard 00 cleanup

Date: 2026-09-06  
Base: `09949d242b9658b6be1eddb7ca2303bb048b56da`  
Branch: `research/champion-security-truth-leadership-00-cleanup`

## Scope

Reviewed exactly these 23 unresolved P2 leadership cases from leadership shard 00:

`CZOOF`, `SYNE`, `IDMCQ`, `TRIRF`, `USPI1`, `IVPR`, `RENX2`, `THMRQ`, `XSELY`, `MPG1`, `KMG1`, `XYLO`, `ALD1`, `MODVQ`, `GNSS1`, `WEJOQ`, `SAIH`, `DCOY`, `HAN`, `LIN2`, `SMX`, `CNTFY`, `NXL1`.

Classification follows `PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`. No future prices, returns, ranks, Champion selections, survival, profitability, future membership, replay output, or strategy outcomes were used.

## Result

| ticker | decision | legal security type | identity / contradiction conclusion |
|---|---|---|---|
| CZOOF | common | Class A ordinary shares | CUSIP churn is corporate-action/reverse-split history. SEC evidence identifies the quoted class as Class A ordinary shares; no preferred/unit/warrant mapping found for CZOOF. |
| SYNE | common | common stock | SEC-filed holdings identify CUSIP 871628301 as Synthesis Energy Systems common stock. Reverse-split CUSIPs do not alter type. |
| IDMCQ | common | common stock | SEC expressly calls IDMCQ IndyMac common stock. DTCC separately identifies IDMCP/IDMPQ as units, providing a direct contradictory-class control. |
| TRIRF | common | Class A ordinary shares | OCC states TRIT became TRIRF and the deliverable is Triterras Class A Ordinary Shares. SPAC predecessor identifiers and OTC migration are identity events. |
| USPI1 | common | common stock | SEC records bind USPI CUSIP 913016309 to United Surgical Partners International public equity; issuer filings describe USPI equity as common stock. No contrary class evidence found for the reviewed CUSIP. |
| IVPR | common | Class A common stock | SEC prospectus explicitly identifies IVPR as Class A common stock. Class B common and Series B preferred exist but are distinct classes. |
| RENX2 | common | sponsored ADR on ordinary shares | Citi depositary records tie ENL/RENX CUSIPs to a sponsored ADR over RELX/Reed Elsevier N.V. ordinary shares. Name, ratio, and merger changes are identity-chain events. |
| THMRQ | common | common stock | SEC explicitly identifies THMRQ as Thornburg Mortgage common stock and separately lists four preferred tickers. |
| XSELY | common | Class A common-share / ADS chain | SEC Schedule 13D identifies CUSIP 983982109 as Xinhua Finance Media A Common Shares. CUSIP change is depositary/share-ratio history. |
| MPG1 | common | common REIT equity | SEC-filed holdings identify MPG Office Trust CUSIP 553274101 as COM. Name/CUSIP history does not establish a non-common class. |
| KMG1 | common | common stock | SEC-filed holdings bind Kerr-McGee CUSIP 492386107 to shares of the public company; contemporaneous issuer records describe the public class as common stock. |
| XYLO | common | ADS on ordinary shares | SEC Form 20-F explicitly states XYLO ADSs represent ordinary shares. CUSIP sequence reflects ADS ratio/reverse splits. |
| ALD1 | common | common stock | SEC-filed holdings identify Allied Capital CUSIP 01903Q108 as common stock, including contemporaneous 2006 evidence. |
| MODVQ | common | common stock | SEC Form 10-Q explicitly lists MODVQ as common stock. Bankruptcy suffix and prior CUSIP are identity events. |
| GNSS1 | common | common stock | SEC tender materials identify Genesis Microchip CUSIP 37184C103 as common stock. |
| WEJOQ | common | common shares | SEC Schedule 13G identifies Wejo CUSIP G9525W109 as common shares. SPAC predecessor and bankruptcy suffix are identity history. |
| SAIH | common | ordinary shares | SEC Form 20-F lists SAIH ordinary shares and separately lists SAIHTW warrants, directly controlling for the non-common class. |
| DCOY | common | common stock | SEC Form 10-Q lists DCOY as common stock. Flex Pharma/Salarius/Decoy name and ticker history is identity-chain history. |
| HAN | common | ADR on ordinary shares | SEC Schedule 13D and Citi identify HAN as Hanson plc ADS/ADR, each representing five ordinary shares. |
| LIN2 | common | ADS on common shares | SEC Schedule 13D states LINE Corporation NYSE ADSs each represent one common share. Merger/ticker changes do not alter the historical type. |
| SMX | common | ordinary shares | SEC prospectus states SMX is ordinary shares and SMXWW is the separately listed warrant. Multiple CUSIPs are reverse-split identifiers. |
| CNTFY | common | ADR/ADS on ordinary common equity | SEC reporting for China Netcom describes its U.S.-traded ADSs as representing ordinary shares. OTC/post-delisting identifier changes are type-neutral. |
| NXL1 | common | common REIT equity | SEC-filed holdings identify New Plan Excel Realty Trust CUSIP 648053106 as common stock. Preferred securities use distinct identifiers. |

## Authoritative evidence highlights

- CZOOF: SEC Schedule 13D/A — Cazoo Group Ltd Class A Ordinary Shares.
- SYNE: SEC-filed Form 13F information table — CUSIP 871628301, `COM`.
- IDMCQ: SEC administrative order — IDMCQ is IndyMac common stock; DTCC separately identifies IndyMac units.
- TRIRF: OCC memo 50012 — Triterras Class A Ordinary Shares.
- IVPR: SEC Form 424B3 — IVPR Class A common stock.
- RENX2: Citibank Depositary Receipt Services — sponsored ADR, deposited securities ordinary shares.
- THMRQ: SEC Section 12(j) materials — common stock; four preferred tickers separately identified.
- XYLO: SEC Form 20-F — ADSs representing ordinary shares.
- MODVQ: SEC Form 10-Q — common stock.
- GNSS1: SEC Schedule 14D-9 — common stock, CUSIP 37184C103.
- WEJOQ: SEC Schedule 13G — common shares, CUSIP G9525W109.
- SAIH: SEC Form 20-F — ordinary shares; warrants separately listed.
- DCOY: SEC Form 10-Q — common stock.
- HAN: SEC Schedule 13D plus Citibank ADR record — ADS/ADR on ordinary shares.
- LIN2: SEC Schedule 13D — ADSs each representing one LINE common share.
- SMX: SEC prospectus — ordinary shares; warrants separately listed.
- NXL1: SEC-filed holdings table — common stock, CUSIP 648053106.

Full evidence URLs and per-case contradiction notes are recorded in `leadership-shard-00-cleanup.json`.

## Counts

- common: **23**
- non_common: **0**
- split: **0**
- unresolved: **0**

Remaining unresolved names: **none**.

`outcome_information_used=false`.

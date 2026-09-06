# Leadership security-type review — shard 02

Date: 2026-09-06

Base: `research/champion-security-truth-held-pending-integration` @ `5b9d9ea2e378044f49d217fe311b36b45c73124c`

Branch: `research/champion-security-truth-leadership-02`

## Assignment and validation

Filter `priority == P2_LEADERSHIP`, sort by integer `security_id` then `ticker`, select zero-based `i % 4 == 2`.

Assigned: 45. Reviewed: 45. Extras: 0. Missing: 0. Duplicates: 0.

Classifications: 45 `common`, 0 `non_common`, 0 unresolved. Type corrections: 0. Interval splits: 0.

All cases use `outcome_information_used=false`.

## Exact retained assignment

- `17159090121204713` `NXUR`
- `32974016278498836` `PHXM`
- `73450089656923190` `CUPR`
- `92506667189012807` `VSME`
- `117705586566981393` `SFN1`
- `136874785304216743` `PRFX`
- `181712688269645497` `QNTM`
- `199185697115041180` `APTOF`
- `218572092380512800` `GOCOQ`
- `233189665423411967` `PWAVQ`
- `246935175493407989` `ATNXQ`
- `267576191249806189` `YAAS`
- `289699865864951191` `BAOS`
- `302967941881581516` `EONGY`
- `322630251933381263` `OCG`
- `357682836404705598` `USBC`
- `379900522967298057` `PSTI1`
- `394112553857045151` `TU`
- `424099180503622082` `VSTE`
- `450317911727604097` `BHATF`
- `472470523584007203` `ZAPP`
- `494106095955525849` `MATR1`
- `515779142969303930` `QVCGB`
- `568706458403231309` `VJTTY`
- `594644032218297668` `BFAM1`
- `633661694719460024` `MTC`
- `651798515940468989` `LAUR1`
- `687689361886221535` `IS`
- `703291776797057040` `CLSDQ`
- `732186125444103069` `CPOP`
- `763211457704323541` `TWG`
- `775861136859211393` `RARE1`
- `842806401459493658` `GNCAQ`
- `863372863639270983` `CNCT1`
- `877888972841438604` `SKYA`
- `890200990076735722` `STEL1`
- `905482684706096774` `SPHL`
- `946325887613166050` `LAIXY`
- `965251650458029578` `AIIXY`
- `987218777470557287` `GMVDF`
- `1012830998144725822` `CIMG`
- `1037115478952756071` `FSV`
- `1057977022122607134` `AVCTQ`
- `1086144274115457561` `MIMI`
- `1114676339922425532` `NDZ`

## Findings

All assigned decision-period securities are common/ordinary corporate equity or ADR/ADS wrappers on common/ordinary equity. Multiple-CUSIP records are identity metadata: predecessor/successor issuers, reverse splits, depositary changes, renames, reorganizations, or stale identifiers. None establishes a legal type transition inside an assigned canonical interval.

Explicit reorganization/identity chains reviewed: `NXUR`, `PHXM`, `PSTI1`, `VSTE`, `ZAPP`, `CIMG`, and `AVCTQ`. Each preserves common-equity type for the canonical decision interval.

## Unresolved worklist

None.

## JSON integrity

SHA-256: `9cd54de48f7f6e564e6242cec4f689ebeed969568463defaa17dd94f08106576`

## Per-case docket

- `17159090121204713` `NXUR` — `common` / `CLASS_A_COMMON_STOCK`; interval `2024-12-30`–`2025-01-06`; evidence: https://www.sec.gov/Archives/edgar/data/1702202/000107997325000014/xslSCHEDULE_13G_X01/primary_doc.xml
- `32974016278498836` `PHXM` — `common` / `ADR_REPRESENTING_ORDINARY_SHARES`; interval `2021-08-02`–`2021-08-03`; evidence: https://www.sec.gov/Archives/edgar/data/1624422/000092189518000017/sc13g07422ery_01022018.htm
- `73450089656923190` `CUPR` — `common` / `CLASS_A_ORDINARY_SHARES`; interval `2026-06-15`–`2026-06-30`; evidence: https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-353
- `92506667189012807` `VSME` — `common` / `CLASS_A_ORDINARY_SHARES`; interval `2026-06-10`–`2026-06-16`; evidence: https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2024-285
- `117705586566981393` `SFN1` — `common` / `COMMON_STOCK`; interval `2011-07-21`–`2011-09-02`; evidence: https://www.sec.gov/Archives/edgar/data/932471/000093247107001363/strategicsmallcapequity615.htm
- `136874785304216743` `PRFX` — `common` / `ORDINARY_SHARES`; interval `2023-07-14`–`2025-08-20`; evidence: https://www.sec.gov/Archives/edgar/data/1801834/000117891323000834/zk2329293.htm
- `181712688269645497` `QNTM` — `common` / `CLASS_B_SUBORDINATE_VOTING_COMMON_SHARES`; interval `2025-02-04`–`2025-02-13`; evidence: https://www.sec.gov/Archives/edgar/data/1425930/000182912623007134/xslForm13F_X02/infotable.xml
- `199185697115041180` `APTOF` — `common` / `COMMON_SHARES`; interval `2021-03-24`–`2021-04-20`; evidence: https://www.sec.gov/Archives/edgar/data/882361/000119312526291467/d159509dsc13e3a.htm
- `218572092380512800` `GOCOQ` — `common` / `CLASS_A_COMMON_STOCK`; interval `2021-01-29`–`2021-10-04`; evidence: https://www.sec.gov/Archives/edgar/data/1808220/000138713121002330/goco-sc13ga_123120.htm
- `233189665423411967` `PWAVQ` — `common` / `COMMON_STOCK`; interval `2006-07-05`–`2007-11-27`; evidence: https://www.sec.gov/Archives/edgar/data/1023362/000093583613000121/kry13gamd1.htm
- `246935175493407989` `ATNXQ` — `common` / `COMMON_STOCK`; interval `2019-12-13`–`2021-06-02`; evidence: https://www.sec.gov/Archives/edgar/data/1300699/000119312519034487/d647775dsc13ga.htm
- `267576191249806189` `YAAS` — `common` / `CLASS_A_ORDINARY_SHARES`; interval `2026-04-27`–`2026-04-28`; evidence: https://www.sec.gov/Archives/edgar/data/1964946/000149315225015503/form6-k.htm
- `289699865864951191` `BAOS` — `common` / `ORDINARY_SHARES`; interval `2024-12-24`–`2025-01-06`; evidence: https://www.sec.gov/Archives/edgar/data/1811216/000110465922031054/tm228583d2_sc13g.htm
- `302967941881581516` `EONGY` — `common` / `ADR_REPRESENTING_ORDINARY_SHARES`; interval `2007-02-27`–`2007-08-30`; evidence: https://depositaryreceipts.citi.com/adr/guides/pgm_d.aspx?cusip=268780103&pageId=23&subpageID=104&typeDisplay=A
- `322630251933381263` `OCG` — `common` / `ORDINARY_SHARES`; interval `2025-12-09`–`2025-12-10`; evidence: https://www.nasdaqtrader.com/TraderNews.aspx?id=eca2026-267
- `357682836404705598` `USBC` — `common` / `COMMON_STOCK`; interval `2025-06-09`–`2025-07-08`; evidence: https://www.sec.gov/Archives/edgar/data/1074828/000107482826000052/usbc-20260713.htm
- `379900522967298057` `PSTI1` — `common` / `COMMON_STOCK`; interval `2006-11-06`–`2007-01-18`; evidence: https://www.sec.gov/Archives/edgar/data/311884/000022532204000038/fidtaxmgdstock_00343n-514.htm
- `394112553857045151` `TU` — `common` / `COMMON_SHARES`; interval `2020-02-13`–`2026-07-31`; evidence: https://www.sec.gov/Archives/edgar/data/277751/000114554925057304/xslFormNPORT-P_X01/primary_doc.xml
- `424099180503622082` `VSTE` — `common` / `ORDINARY_SHARES`; interval `2024-11-01`–`2024-11-25`; evidence: https://www.sec.gov/Archives/edgar/data/1964630/000121390024096965/ea0220781-13da1agcent_vast.htm
- `450317911727604097` `BHATF` — `common` / `ORDINARY_SHARES`; interval `2022-06-23`–`2022-07-22`; evidence: https://www.sec.gov/Archives/edgar/data/1759136/000173112226000326/e7387_ex99-1.htm
- `472470523584007203` `ZAPP` — `common` / `ORDINARY_SHARES`; interval `2024-07-02`–`2024-07-31`; evidence: https://www.sec.gov/Archives/edgar/data/1955104/000119312523137794/d450502dsc13g.htm
- `494106095955525849` `MATR1` — `common` / `COMMON_STOCK`; interval `2008-01-25`–`2008-02-21`; evidence: https://www.sec.gov/Archives/edgar/data/814232/000081423206000006/npx06final.htm
- `515779142969303930` `QVCGB` — `common` / `SERIES_B_COMMON_STOCK`; interval `2022-08-03`–`2022-08-04`; evidence: https://www.sec.gov/Archives/edgar/data/1355096/000155837025001837/R1.htm
- `568706458403231309` `VJTTY` — `common` / `ADR_REPRESENTING_ORDINARY_SHARES`; interval `2014-07-07`–`2014-07-29`; evidence: https://depositaryreceipts.citi.com/adr/guides/pgm_d.aspx?cusip=92912L206&pageId=16&subpageID=104&typeDisplay=A
- `594644032218297668` `BFAM1` — `common` / `COMMON_STOCK`; interval `2008-01-23`–`2008-02-11`; evidence: https://www.sec.gov/Archives/edgar/data/1437578/000143757826000006/bfam-20251231.htm
- `633661694719460024` `MTC` — `common` / `COMMON_SHARES`; interval `2025-11-05`–`2025-11-14`; evidence: https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2022-173
- `651798515940468989` `LAUR1` — `common` / `COMMON_STOCK`; interval `2006-07-21`–`2007-07-26`; evidence: https://www.sec.gov/Archives/edgar/data/912766/000092189507000386/sc13d06872002_02212007.htm
- `687689361886221535` `IS` — `common` / `CLASS_A_ORDINARY_SHARES`; interval `2021-09-20`–`2022-11-04`; evidence: https://www.sec.gov/Archives/edgar/data/1802967/000180296722000001/xslForm13F_X01/taocapmngtlp_13f-4q21.xml
- `703291776797057040` `CLSDQ` — `common` / `COMMON_STOCK`; interval `2018-03-08`–`2021-07-14`; evidence: https://www.sec.gov/Archives/edgar/data/1539029/000119312525282949/clsd-20250930.htm
- `732186125444103069` `CPOP` — `common` / `CLASS_A_ORDINARY_SHARES`; interval `2021-12-29`–`2024-02-22`; evidence: https://www.sec.gov/Archives/edgar/data/1807389/000121390026076379/ea029741701ex99-1.htm
- `763211457704323541` `TWG` — `common` / `CLASS_A_ORDINARY_SHARES`; interval `2024-10-15`–`2025-12-09`; evidence: https://www.sec.gov/Archives/edgar/data/1475597/000147559725000025/xslForm13F_X02/form13fInfoTable.20250630.xml
- `775861136859211393` `RARE1` — `common` / `COMMON_STOCK`; interval `2007-08-17`–`2007-10-01`; evidence: https://www.sec.gov/Archives/edgar/data/883976/000090221906001044/sec_filing.htm
- `842806401459493658` `GNCAQ` — `common` / `COMMON_STOCK`; interval `2016-04-07`–`2016-04-14`; evidence: https://www.sec.gov/Archives/edgar/data/1097218/000095012315004935/xslForm13F_X01/form13fInfoTable.xml
- `863372863639270983` `CNCT1` — `common` / `COMMON_STOCK`; interval `2006-11-08`–`2006-11-17`; evidence: https://www.sec.gov/Archives/edgar/data/49205/000004920520000003/xslForm13F_X01/QTR22020_13F_HR.XML
- `877888972841438604` `SKYA` — `common` / `COMMON_STOCK`; interval `2025-08-27`–`2025-09-23`; evidence: https://www.sec.gov/Archives/edgar/data/1737995/000149315226036513/form10-q.htm
- `890200990076735722` `STEL1` — `common` / `COMMON_STOCK`; interval `2006-11-10`–`2006-12-01`; evidence: https://www.sec.gov/Archives/edgar/data/867347/000095013406021098/f25041sc13d.htm
- `905482684706096774` `SPHL` — `common` / `CLASS_A_ORDINARY_SHARES`; interval `2026-01-15`–`2026-01-30`; evidence: https://www.sec.gov/Archives/edgar/data/2062053/000101376225002195/xslSCHEDULE_13D_X01/primary_doc.xml
- `946325887613166050` `LAIXY` — `common` / `ADS_REPRESENTING_CLASS_A_ORDINARY_SHARES`; interval `2021-02-05`–`2021-02-26`; evidence: https://www.sec.gov/Archives/edgar/data/1742056/000095010322003256/dp167880_sc13ga-laix.htm
- `965251650458029578` `AIIXY` — `common` / `ADS_REPRESENTING_ORDINARY_SHARES`; interval `2010-04-05`–`2010-06-02`; evidence: https://www.sec.gov/Archives/edgar/data/1089496/000110465916151650/a16-19315_4sc14d9a.htm
- `987218777470557287` `GMVDF` — `common` / `ORDINARY_SHARES`; interval `2022-01-20`–`2022-02-02`; evidence: https://www.sec.gov/Archives/edgar/data/1760764/000121390022008741/ea155958-13ggeva_gmedical.htm
- `1012830998144725822` `CIMG` — `common` / `COMMON_STOCK`; interval `2021-11-11`–`2024-10-21`; evidence: https://www.sec.gov/Archives/edgar/data/1527613/000149315222010718/formsc13g.htm
- `1037115478952756071` `FSV` — `common` / `COMMON_STOCK`; interval `2025-01-13`–`2026-07-31`; evidence: https://www.sec.gov/Archives/edgar/data/1637810/000094059426000046/xslSCHEDULE_13G_X02/primary_doc.xml
- `1057977022122607134` `AVCTQ` — `common` / `COMMON_STOCK`; interval `2020-08-06`–`2022-10-21`; evidence: https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2020-60
- `1086144274115457561` `MIMI` — `common` / `CLASS_A_ORDINARY_SHARES`; interval `2025-10-03`–`2025-10-06`; evidence: https://www.sec.gov/Archives/edgar/data/1998560/000121390026051168/ea0288869-6k_mintinc.htm
- `1114676339922425532` `NDZ` — `common` / `COMMON_STOCK`; interval `2010-04-06`–`2014-04-28`; evidence: https://www.sec.gov/Archives/edgar/data/1091561/000110465913078650/xslForm13F_X01/a13-23015_1informationtable.xml

# Durable-ranked security-type review — shard 06

Date: 2026-09-06  
Base: `research/champion-security-truth-held-pending-integration` @ `5b9d9ea2e378044f49d217fe311b36b45c73124c`  
Branch: `research/champion-security-truth-durable-06`

## Assignment

Filter `priority == P1_DURABLE_RANKED`, sort ascending by `(security_id as integer, ticker)`, assign zero-based `i`, retain rows where `i % 10 == 6`.

Eligible P1 durable-ranked rows: **442**. Assigned rows: **44**.

`6 CCE1 11216770926041725`; `16 SGI1 39846923719649688`; `26 JRJC 64206123129785849`; `36 VZLA 106719732073423530`; `46 SUN 153962662178470060`; `56 TEN1 179460760874548237`; `66 HOKUQ 210189795761413012`; `76 RPRX1 227365020521330341`; `86 DHOXY 263440498600908021`; `96 FLNA 280302887364922861`; `106 GTI1 300480570843838414`; `116 RSLS1 324987086697435354`; `126 SPG 347578475150470281`; `136 POET 366588347960507460`; `146 BBVA 397304374943978012`; `156 HESM 414354049493551403`; `166 EGIOQ 435995005362000574`; `176 DMTKQ 469456447416982021`; `186 TT2 487869582447266471`; `196 FTRCQ 511484518106596204`; `206 NOVNQ 554954176952665665`; `216 GTATQ 573548210310379987`; `226 PSIG 597464188108207633`; `236 LTMAY 616497452040356659`; `246 WR1 647605362927682776`; `256 OBQI 661122241998976287`; `266 OSI2 694575590377385878`; `276 HCA1 709117510027464757`; `286 TIOG 746158814089704953`; `296 AMTD1 766320971625686200`; `306 RELX 804112171693242775`; `316 ESLRQ 831371468261077058`; `326 WINMQ 856115972129012903`; `336 MITI1 884241433752390727`; `346 WEST2 910334444152931164`; `356 NEUP 942564779172582485`; `366 HOLI 965579180728514841`; `376 DTV1 990484726740043660`; `386 IOGPQ 1020754940824385887`; `396 STM 1042422373680994522`; `406 PSNY 1080971315611263813`; `416 STLA 1101603435419704379`; `426 PLG 1124761511834148777`; `436 FUN 1144271736914874719`.

## Contract

Applied `PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`. Security type is reconstructed as factual historical legal security type. Later authoritative evidence may establish the earlier fact. Future returns, prices, ranks, Champion selections, survival, profitability, future index membership, and strategy outcomes were excluded. `outcome_information_used=false` for every case.

## Results

- **common: 33**
- **non_common: 3**
- **split: 0**
- **unresolved: 8**

Classification changes from the queue hypothesis:

- `SUN`: `common` → `non_common`. Sunoco LP common units represent limited partner interests; predecessor Susser Petroleum Partners was also an LP security.
- `HESM`: `common` → `non_common`. Hess Midstream securities are partnership interests; the reviewed predecessor filing identifies common units representing limited partner interests.
- `FUN`: `common` → `non_common`. Cedar Fair CUSIP `150185106` was depositary units representing limited partner interests through the canonical endpoint 2024-07-01. Successor Six Flags common stock begins after the merger boundary.

No resolved case required an intra-interval type split.

## Unresolved worklist

- `HOKUQ` (`210189795761413012`): CUSIP/name chain across `434711107` and `434712105` was not fully closed.
- `FLNA` (`280302887364922861`): `14817C107` is Cassava Sciences common stock, while `69562K100` / `69562K506` were not established as the same canonical issuer episode.
- `TT2` (`487869582447266471`): CUSIPs `892893108` and `029712106` were not tied by primary evidence to one continuous legal class.
- `PSIG` (`597464188108207633`): foreign CUSIP sequence `G0R45S109`, `G7308J105`, `G7308J113` was not fully tied to one ordinary-share episode.
- `OSI2` (`694575590377385878`): CUSIPs `689899102` and `67104A101` were not tied to the same canonical issuer episode.
- `MITI1` (`884241433752390727`): CUSIPs `59509C105` and `13738Y107` were not tied to one continuous common-share episode.
- `WEST2` (`910334444152931164`): CUSIPs `009720103`, `96040V101`, and `033355108` were not tied to one continuous legal class.
- `NEUP` (`942564779172582485`): current `64136E102` is common stock, but the canonical interval starts before Neuphoria's 2024 incorporation and includes predecessor CUSIPs `09063M205` and `Q1521J108`; continuity remains open.

## Validation

- Assignment formula reproduced: **PASS**
- Every assigned case exactly once: **PASS**
- Foreign cases: **0**
- All resolved cases evidence-backed: **PASS**
- Explicit unresolved worklist: **PASS**
- Outcome information used: **false**

The machine-readable JSON contains the per-case canonical interval, all queue CUSIPs, decision, legal security type, effective intervals, evidence URLs, source documents, factual findings, identity-transition analysis, contradiction search, outcome-information flag, and review status.

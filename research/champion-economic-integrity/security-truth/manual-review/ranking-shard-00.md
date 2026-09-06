# Ranking/base security-truth review — shard 00

Base branch: `research/champion-security-truth-held-pending-integration`  
Base head: `5b9d9ea2e378044f49d217fe311b36b45c73124c`  
Review branch: `research/champion-security-truth-ranking-00`

## Deterministic assignment

Filter: `priority == P3_RANKING_OR_BASE`  
Sort: `(security_id as integer, ticker)` ascending  
Index: zero-based `i`  
Shard rule: `i % 2 == 0`

P3 rows: 61. Assigned rows: 31.

| i | security_id | ticker |
|---:|---:|---|
| 0 | 57044006746155268 | ODTC |
| 2 | 132672321362575555 | FER |
| 4 | 137714657591136915 | TMPOQ |
| 6 | 153414598251739485 | TVIAQ |
| 8 | 169684801850084882 | ANG-PB |
| 10 | 198390113242719162 | CFRXQ |
| 12 | 228058489043892858 | ANG-PA |
| 14 | 229963927054418472 | EPR-PE |
| 16 | 232112979474058723 | BPY |
| 18 | 241773249272800956 | EMESQ |
| 20 | 270907768212940979 | VIEWQ |
| 22 | 278856321542165771 | CORSQ |
| 24 | 391908814644765747 | CCI-PA |
| 26 | 420287026268986271 | WTRU |
| 28 | 494080213499901728 | LGCYQ |
| 30 | 551585671305244475 | PLM |
| 32 | 639821035856559974 | DBRG-PI |
| 34 | 648904847475652130 | ELP |
| 36 | 727435643303361912 | JZXN |
| 38 | 734347851745471872 | AB |
| 40 | 784068816139277733 | EVEIQ |
| 42 | 820488167476030287 | USAC |
| 44 | 841546519006260116 | SUBCY |
| 46 | 927001813921390541 | CADE-PA |
| 48 | 941553026160917585 | ATH-PA |
| 50 | 982072475162188385 | SHLX |
| 52 | 1013898987216920348 | LILMF |
| 54 | 1038919393884227344 | SDLPQ |
| 56 | 1089698460273142770 | CWEN.A |
| 58 | 1093865446405037869 | RTLR |
| 60 | 1148177820383038150 | EPD |

## Results

- common: 13
- non_common: 18
- split: 0
- unresolved: 0
- outcome information used: false for every case

Common: ODTC, FER, TMPOQ, TVIAQ, CFRXQ, VIEWQ, CORSQ, PLM, JZXN, EVEIQ, SUBCY, LILMF, CWEN.A.

Non-common: ANG-PB, ANG-PA, EPR-PE, BPY, EMESQ, CCI-PA, WTRU, LGCYQ, DBRG-PI, ELP, AB, USAC, CADE-PA, ATH-PA, SHLX, SDLPQ, RTLR, EPD.

## Factual corrections

| ticker | queue hypothesis | reviewed decision | factual basis |
|---|---|---|---|
| LGCYQ | common | non_common | Contemporaneous 2014 SEC materials describe Legacy Reserves LP securities as units representing limited partner interests. The later corporate reorganization does not alter the 2014 legal form. |
| ELP | common | non_common | COPEL's SEC Form 15 identifies ELP ADSs as representing preferred shares and separately identifies the common-share ADS line. |
| SDLPQ | common | non_common | Seadrill Partners issuer material filed with the SEC identifies SDLP securities as common units representing limited liability company interests. |

The manual-conflict cases BPY, EMESQ, AB, USAC, SHLX, RTLR, and EPD resolve to `non_common` because their authoritative legal form is partnership/unit ownership, not corporate common stock. WTRU is a tangible equity unit consisting of a stock purchase contract and amortizing note.

## Validation

- Exact deterministic assignment retained above and in JSON.
- All 31 assigned cases occur exactly once.
- No unassigned security is reviewed.
- Every resolved case records CUSIPs, canonical interval, legal type, effective interval, evidence locator(s), identity-transition analysis, contradiction search, and `outcome_information_used=false`.
- No genuine historical type transition was established inside an assigned canonical interval.
- Unresolved worklist: empty.
- No Champion run, replay, backtest, economic change, runtime change, or strategy change was performed.

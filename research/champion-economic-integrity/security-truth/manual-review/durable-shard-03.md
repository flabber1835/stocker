# Durable-ranked factual security-type review — shard 03

Date: 2026-09-06

Base: `research/champion-security-truth-held-pending-integration` @ `5b9d9ea2e378044f49d217fe311b36b45c73124c`

Branch: `research/champion-security-truth-durable-03`

## Assignment

Reproduced exactly: filter `priority == P1_DURABLE_RANKED`; sort ascending by `(security_id as integer, ticker)`; assign zero-based `i`; retain `i % 10 == 3`.

Eligible P1 rows: **442**. Assigned rows: **44**.

```text
3    6925516220905516 HEXO
13   34225094003874007 AFMDQ
23   56251943382633799 HK1
33   102913681476067012 C
43   149209101404250271 LLL1
53   175205642536175483 CGGYY
63   200782403799405397 DNA1
73   223849730517685501 SQBGQ
83   253712989797197450 EGLE2
93   277908412373409816 MT
103  292100658301919299 BLDP
113  323335118726927382 FLG
123  342247754560677675 BEC1
133  360366760615663399 OIBRQ
143  389655448979765487 TSEM
153  410428273002319352 FWONK
163  429424164408492505 SPNS
173  461600950471082009 BRLCQ
183  482195723341052987 ETP1
193  498165093608150980 IEP
203  548570527460070038 ABWTQ
213  569370157886073038 DNMRQ
223  594891209465982980 PDS
233  606652031906884063 NXTT
243  636803527620694979 GENE
253  657581892454514237 FBNIQ
263  681764378359853114 ENGC
273  700503722601979334 RYI1
283  727654521122872319 EP1
293  764076178552891930 NS
303  801001360341549242 CYBR
313  821088485879503592 LCINQ
323  843455423519216577 TTCFQ
333  877979492663188035 XNDU
343  905064659577868827 ASAPQ
353  935924025138960001 USG1
363  957008674074369745 S2
373  985458183012447728 SPWRQ
383  1012536259009666805 CA1
393  1037451286237013475 DFODQ
403  1068602958000339053 GLFMQ
413  1100081557843370397 D
423  1119755750402433659 TRIL1
433  1137097334490607165 INSG
```

## Results

| security_id | ticker | decision | legal security type |
|---:|---|---|---|
| 6925516220905516 | HEXO | common | common shares |
| 34225094003874007 | AFMDQ | common | common shares |
| 56251943382633799 | HK1 | common | common stock |
| 102913681476067012 | C | common | common stock |
| 149209101404250271 | LLL1 | common | common stock |
| 175205642536175483 | CGGYY | common | ADR on ordinary shares |
| 200782403799405397 | DNA1 | common | common stock |
| 223849730517685501 | SQBGQ | common | common stock |
| 253712989797197450 | EGLE2 | common | common stock |
| 277908412373409816 | MT | common | ordinary shares |
| 292100658301919299 | BLDP | common | common shares |
| 323335118726927382 | FLG | common | common stock |
| 342247754560677675 | BEC1 | common | common stock |
| 360366760615663399 | OIBRQ | common | ADS on common shares |
| 389655448979765487 | TSEM | common | ordinary shares |
| 410428273002319352 | FWONK | common | Series C common tracking stock |
| 429424164408492505 | SPNS | common | ordinary shares |
| 461600950471082009 | BRLCQ | common | common stock |
| 482195723341052987 | ETP1 | non_common | limited-partnership common units |
| 498165093608150980 | IEP | non_common | depositary units representing limited partner interests |
| 548570527460070038 | ABWTQ | common | common stock |
| 569370157886073038 | DNMRQ | common | Class A common stock |
| 594891209465982980 | PDS | split | trust units → corporation common shares |
| 606652031906884063 | NXTT | common | common stock |
| 636803527620694979 | GENE | common | sponsored ADR on ordinary shares |
| 657581892454514237 | FBNIQ | common | common stock |
| 681764378359853114 | ENGC | common | common stock |
| 700503722601979334 | RYI1 | common | common stock |
| 727654521122872319 | EP1 | common | common stock |
| 764076178552891930 | NS | non_common | limited-partnership common units |
| 801001360341549242 | CYBR | common | ordinary shares |
| 821088485879503592 | LCINQ | common | common stock |
| 843455423519216577 | TTCFQ | common | Class A/common stock across business combination |
| 877979492663188035 | XNDU | common | common equity across identity transition |
| 905064659577868827 | ASAPQ | common | common stock |
| 935924025138960001 | USG1 | common | common stock |
| 957008674074369745 | S2 | common | common equity |
| 985458183012447728 | SPWRQ | common | common stock |
| 1012536259009666805 | CA1 | common | common stock |
| 1037451286237013475 | DFODQ | common | common stock |
| 1068602958000339053 | GLFMQ | common | common stock |
| 1100081557843370397 | D | common | common stock |
| 1119755750402433659 | TRIL1 | common | common stock |
| 1137097334490607165 | INSG | common | common stock |

Counts: **40 common / 3 non_common / 1 split / 0 unresolved**.

## Classification changes

- `ETP1` (`482195723341052987`): queue candidate `common` → `non_common`. SEC filings identify Energy Transfer Partners, L.P. common units.
- `IEP` (`498165093608150980`): queue candidate `common` → `non_common`. SEC filings identify depositary units representing limited partner interests.
- `PDS` (`594891209465982980`): queue candidate `unknown` → split. Precision Drilling Trust units are `non_common` through 2010-05-28; the June 1, 2010 conversion exchanged all trust units one-for-one for Precision Drilling Corporation common shares, which are `common` from 2010-06-01. NYSE common-share trading was expected from June 2.
- `NS` (`764076178552891930`): queue candidate `common` → `non_common`. NuStar Energy is an MLP common-unit security.

## Validation

- Assignment formula reproduced: `true`
- Every assigned case exactly once: `true`
- Foreign cases: `0`
- All resolved cases evidence-backed: `true`
- Unresolved worklist: **empty**
- Outcome information used: `false`

Complete canonical intervals, CUSIP sets, effective intervals, evidence URLs, source-document descriptions, factual findings, identity-transition analyses and contradiction searches are retained in `durable-shard-03.json`.

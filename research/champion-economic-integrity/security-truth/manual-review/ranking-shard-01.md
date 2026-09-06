# Ranking/base security-truth review — shard 01

Base: `research/champion-security-truth-held-pending-integration` @ `5b9d9ea2e378044f49d217fe311b36b45c73124c`

Branch: `research/champion-security-truth-ranking-01`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

No Champion, replay, backtest, runtime, strategy, or economic result was used. Every record has `outcome_information_used=false`.

## Deterministic assignment

Filter `priority == P3_RANKING_OR_BASE`, sort ascending by `(security_id as integer, ticker)`, assign zero-based `i`, retain `i % 2 == 1`.

Assigned count: **30**.

| i | security_id | ticker |
|---:|---:|---|
| 1 | 110726389677702988 | IMPH |
| 3 | 134130355196555097 | SKIL |
| 5 | 146845651130596317 | CMLP |
| 7 | 161168179129897137 | LB |
| 9 | 188640629095435560 | SXTC |
| 11 | 202200000063691725 | SYCRF |
| 13 | 228207928463147707 | ETP |
| 15 | 230485976154984954 | PFBC |
| 17 | 241694605179777667 | ARGO-PA |
| 19 | 258046948374938664 | ASTL |
| 21 | 275062087927273775 | GPT2 |
| 23 | 299712706490312370 | GRI |
| 25 | 397172774526346028 | NCV-PA |
| 27 | 450075566409889078 | BIP |
| 29 | 534005804985681589 | AIFU |
| 31 | 607033349837235157 | MMP |
| 33 | 648373417461465308 | WPZ |
| 35 | 726313399179454655 | ACR-PC |
| 37 | 730525788357019090 | OCS |
| 39 | 780929740903947449 | QNGYQ |
| 41 | 812131184133218118 | AUDAQ |
| 43 | 824100797961064199 | BTTGY |
| 45 | 866652633497189649 | VNTRQ |
| 47 | 934304255431280640 | CVOVQ |
| 49 | 970701175286846075 | EPR-PC |
| 51 | 995314484072140452 | LCIDW |
| 53 | 1019479234403084594 | BEP |
| 55 | 1066160137614589315 | JTKWY |
| 57 | 1092594788232214414 | WES |
| 59 | 1118115652775499706 | NEE-PO |

## Results

Counts: **12 common / 11 non_common / 0 split / 7 unresolved**.

| ticker | decision | legal security type |
|---|---|---|
| IMPH | common | common stock |
| SKIL | common | Class A common stock |
| CMLP | non_common | common units representing limited partner interests |
| LB | unresolved | unresolved |
| SXTC | common | ordinary shares |
| SYCRF | unresolved | unresolved |
| ETP | non_common | common units representing limited partner interests |
| PFBC | common | common stock |
| ARGO-PA | non_common | depositary shares representing preferred stock |
| ASTL | common | common shares |
| GPT2 | common | common shares of beneficial interest |
| GRI | common | common stock |
| NCV-PA | unresolved | unresolved |
| BIP | non_common | limited partnership units |
| AIFU | common | ADS on ordinary shares during canonical interval |
| MMP | non_common | common units of a limited partnership |
| WPZ | non_common | common units representing limited partner interests |
| ACR-PC | unresolved | unresolved |
| OCS | common | ordinary shares |
| QNGYQ | common | common stock |
| AUDAQ | common | Class A common stock |
| BTTGY | unresolved | unresolved |
| VNTRQ | unresolved | unresolved |
| CVOVQ | unresolved | unresolved |
| EPR-PC | non_common | convertible preferred stock |
| LCIDW | non_common | public warrant to purchase Class A common stock |
| BEP | non_common | limited partnership units |
| JTKWY | common | sponsored ADS on ordinary/common equity |
| WES | non_common | common units representing limited partner interests |
| NEE-PO | non_common | convertible preferred stock |

## Correction

`CMLP` changes from the queue candidate `common` to **`non_common`**. SEC issuer/prospectus evidence identifies Crestwood Midstream Partners as a limited partnership and the traded CMLP security as common units representing limited-partner interests.

## Identifier transitions

Every listed queue CUSIP for the 30 assigned cases was included in the review. No genuine legal security-type transition was established inside an assigned canonical interval. Identifier changes supporting resolved cases were treated as identity/corporate-action continuity only where the evidence supported that conclusion.

## Unresolved worklist

Authoritative evidence remains insufficient for deterministic resolution of: **LB, SYCRF, NCV-PA, ACR-PC, BTTGY, VNTRQ, CVOVQ**.

These cases remain explicit `unresolved`; none defaults to common or non-common.

## Validation

- deterministic assignment reproduced from the frozen queue
- 30 assigned cases represented exactly once
- zero extras
- 23 resolutions carry security-specific evidence URLs in the JSON
- 7 unresolved cases are explicit in the worklist
- `outcome_information_used=false` for every case
- no Champion or replay execution performed

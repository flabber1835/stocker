# Durable security-truth review — shard 00

- Base: `research/champion-security-truth-held-pending-integration` @ `5b9d9ea2e378044f49d217fe311b36b45c73124c`
- Branch: `research/champion-security-truth-durable-00`
- Queue filter: `priority == P1_DURABLE_RANKED`
- Sort: ascending `(security_id as integer, ticker)`
- Index: zero-based sequential `i`
- Shard predicate: `i % 10 == 0`
- Qualifying P1 rows: **442**
- Assigned rows: **45**

## Retained assignment (before research)

- i=0: `219953444935140` `VIVO1`
- i=10: `20237171367150132` `ECHO2`
- i=20: `55356489462400378` `LEVGQ`
- i=30: `93116911439830233` `CDCAQ`
- i=40: `133702805808789102` `AOBI`
- i=50: `169645355004035769` `GOGL1`
- i=60: `193588831378973240` `OKS`
- i=70: `214877619014563439` `FUVV`
- i=80: `242817260532849391` `CPPRQ`
- i=90: `272478278078438193` `WOLF2`
- i=100: `287367877320854308` `TTE`
- i=110: `313809790950811771` `BEAM2`
- i=120: `338428006488523117` `EQNR`
- i=130: `354775206449723957` `ASLN`
- i=140: `385446091142772687` `ENFY`
- i=150: `405838849220324175` `KL`
- i=160: `426798777460435924` `KZL`
- i=170: `453781472257660077` `LKM`
- i=180: `477532852063999654` `ALR1`
- i=190: `492909916813820707` `NUAI`
- i=200: `543574442698263052` `PWCM`
- i=210: `562358948924032972` `BTI`
- i=220: `582648323211762298` `MRGE1`
- i=230: `604744643544663608` `FIRY`
- i=240: `623190443678201852` `VIAB`
- i=250: `652563215601597373` `TFCFA`
- i=260: `677962974828146176` `ONTO`
- i=270: `697608626643031114` `FRO`
- i=280: `718834017621263734` `GRFS`
- i=290: `758943436528193872` `GLIBA1`
- i=300: `784755978994935882` `ANVGQ`
- i=310: `818902908814402884` `GNS`
- i=320: `838821611242754318` `AM`
- i=330: `872015801854314611` `BEBE1`
- i=340: `895494186251194405` `ALP`
- i=350: `924217175469612074` `POM1`
- i=360: `950956618868470019` `SNBRQ`
- i=370: `969277775854771395` `ROSGQ`
- i=380: `1001469623216439292` `CNH1`
- i=390: `1035563312054045998` `GSK`
- i=400: `1056985280028675237` `CAA`
- i=410: `1086213726748371489` `LKCOF`
- i=420: `1116777537423033703` `ARVLF`
- i=430: `1132110208875336824` `NGG`
- i=440: `1147890361491130219` `PESXQ`

## Results

- common: **43**
- non_common: **1**
- split: **1**
- unresolved: **0**

### Classification changes

- `193588831378973240 OKS`: `common` → `non_common`; ONEOK Partners listed common units representing limited partner interests for the canonical interval.
- `838821611242754318 AM`: `common` → `split`; through 2019-03-12 the security represented limited partner interests, and from 2019-03-13 it was Antero Midstream Corporation common stock.

## Unresolved worklist

None.

## Validation

- Assignment formula reproduced: PASS
- Every assigned case exactly once: PASS
- Foreign cases: 0
- Every resolved case evidence-backed: PASS
- Explicit unresolved worklist: PASS
- `outcome_information_used=false` for every case: PASS
- JSON SHA-256: `1e71529e23d1388ebe567a7cfe61570c9e429105650ecefcb61da4ba2a613852`

Primary/official evidence URLs and per-case factual findings are retained in `durable-shard-00.json`.

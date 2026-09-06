# Durable-ranked factual security-type review — shard 02

Date: 2026-09-06

Base: `research/champion-security-truth-held-pending-integration` @ `5b9d9ea2e378044f49d217fe311b36b45c73124c`

Branch: `research/champion-security-truth-durable-02`

## Assignment

Filtered `priority == P1_DURABLE_RANKED`, sorted ascending by `(security_id as integer, ticker)`, assigned zero-based sequential index `i`, retained only `i % 10 == 2`.

Eligible durable-ranked rows: **442**. Assigned rows: **44**.

| i | security_id | ticker |
|---:|---:|---|
| 2 | 5807491936277145 | PSD |
| 12 | 30587235456063600 | APPHQ |
| 22 | 55985294582827288 | EAGL1 |
| 32 | 98904311513022875 | EBGMY |
| 42 | 144700299941973079 | ACV1 |
| 52 | 175011040903136105 | CSCIF |
| 62 | 200319825958933502 | NBGGY |
| 72 | 222519066932371093 | BSMX |
| 82 | 249507410123302203 | EBODF |
| 92 | 274122717897772948 | DDC2 |
| 102 | 291579668231200993 | TFCF |
| 112 | 320644562611881241 | SOV |
| 122 | 341746105654828485 | SNDL |
| 132 | 358367629315548264 | ABCM |
| 142 | 387526833910121934 | FDG1 |
| 152 | 408251035869802766 | LOCMQ |
| 162 | 428643462170905296 | LADX |
| 172 | 458587006915592303 | IDEXQ |
| 182 | 481857333199692347 | NBEVQ |
| 192 | 496216258498328341 | SKE |
| 202 | 548321324542581421 | BRFS |
| 212 | 567937871571707165 | INFO1 |
| 222 | 592620618586223442 | ALLGF |
| 232 | 606019229277999905 | MODL1 |
| 242 | 624525762102619037 | XEL |
| 252 | 657510510567157460 | HGLI |
| 262 | 680958553726136812 | OGI |
| 272 | 698514937491238880 | DM |
| 282 | 726163640089553293 | FABU |
| 292 | 760884981490078455 | AMRSQ |
| 302 | 790051607473284035 | CHE |
| 312 | 819877013220958897 | ELON1 |
| 322 | 843426090895312559 | ATHXQ |
| 332 | 873022257646047532 | ISUNQ |
| 342 | 900676606992458222 | TRP |
| 352 | 932688238263985034 | WPM |
| 362 | 955594671819826686 | MEG1 |
| 372 | 979008730059053664 | SEGG |
| 382 | 1005418764309241651 | MBAI |
| 392 | 1036427516070314394 | CEQP |
| 402 | 1067506624231909172 | HGENQ |
| 412 | 1096003132450043065 | DD1 |
| 422 | 1119089831900074750 | NSH1 |
| 432 | 1135878622873171323 | DPRO |

## Results

- `common`: **41**
- `non_common`: **3**
- split: **0**
- unresolved: **0**

Classification corrections from the queue/base common hypothesis:

- `FDG1` → `non_common`: Fording Canadian Coal Trust trust units.
- `CEQP` → `non_common`: Crestwood Equity Partners common units representing limited partner interests.
- `NSH1` → `non_common`: NuStar GP Holdings units representing limited liability company interests.

`TRP` resolves the queue manual-conflict/unknown state to `common`; TC Energy/TransCanada evidence identifies a common-share predecessor/successor chain.

## Identity analysis

`LADX` is an identity anomaly. The assigned `232828...` CUSIP family is identified in SEC filings as CytRx common stock. The canonical ticker is retained exactly as assigned. The mismatch is recorded as an identity issue and does not establish a security-type transition.

SPAC/reorganization cases were checked for separate units and warrants. Where present, those instruments carry distinct identifiers from the assigned common-equity chain.

## Validation

- assignment formula reproduced: **PASS**
- every assigned case exactly once: **PASS**
- foreign cases: **0**
- all 44 resolved cases evidence-backed: **PASS**
- explicit unresolved worklist: **empty**
- outcome information used: **false**

The JSON contains the exact canonical intervals, all queue CUSIPs, legal security type, effective interval, evidence URL, source document, factual finding, identity-transition analysis, contradiction search, outcome-information flag, and review status for every assigned case.

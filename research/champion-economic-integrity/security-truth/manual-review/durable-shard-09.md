# Durable-ranked security truth review — shard 09

Base: `research/champion-security-truth-held-pending-integration` @ `5b9d9ea2e378044f49d217fe311b36b45c73124c`

Branch: `research/champion-security-truth-durable-09`

Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

Outcome information used: `false`

## Assignment reproduction

Filter `priority == P1_DURABLE_RANKED`; sort ascending by `(security_id as integer, ticker)`; assign zero-based `i`; retain `i % 10 == 9`.

P1 rows: **442**. Assigned rows: **44**.

| i | security_id | ticker |
|---:|---:|---|
| 9 | 19023067751406413 | DGXX |
| 19 | 51094239347832668 | ZSANQ |
| 29 | 82170842208443514 | ASML |
| 39 | 127841760883980821 | CMMB |
| 49 | 162310595552625902 | OBE |
| 59 | 190675113231122773 | MIC2 |
| 69 | 214204248915913096 | EOP |
| 79 | 241908488000062163 | BEPC |
| 89 | 270195894721936305 | GP |
| 99 | 285093631861891744 | BFXXQ |
| 109 | 311401067615371248 | CAMPQ |
| 119 | 337837786733686004 | BKI1 |
| 129 | 352070480355017297 | ASNAQ |
| 139 | 371238123781729047 | EDR1 |
| 149 | 404606604472462818 | LIFE2 |
| 159 | 425303532627889774 | TRIN1 |
| 169 | 452579604509674802 | ABVEF |
| 179 | 477302961403569227 | ISEE |
| 189 | 490553424496543785 | BASXQ |
| 199 | 524549508080165904 | RCPIQ |
| 209 | 560993313900465152 | EIGRQ |
| 219 | 579480250446220316 | DCT1 |
| 229 | 604552861545382186 | HAPN |
| 239 | 622802662196915364 | RADCQ |
| 249 | 652203078943743046 | CNSY |
| 259 | 675494685548212930 | EZCH |
| 269 | 696840622211111662 | AIFC |
| 279 | 716443807172864880 | EMWPF |
| 289 | 752616570720626425 | CNET1 |
| 299 | 779267533562127263 | IRNTQ |
| 309 | 818427207626286294 | PGN1 |
| 319 | 837082428109450568 | NEBLQ |
| 329 | 871770975475258308 | IHT |
| 339 | 890276907122412598 | BTCT |
| 349 | 918779475935318553 | BIOCQ |
| 359 | 947831258121099345 | AGR1 |
| 369 | 968616391269493492 | PVX |
| 379 | 997629165763677336 | AHMIQ |
| 389 | 1032530646820936253 | WFC |
| 399 | 1054346876338705895 | TACO2 |
| 409 | 1084544820972407346 | NCI1 |
| 419 | 1111338238950530033 | YGEHY |
| 429 | 1130449855367497432 | SAX1 |
| 439 | 1145718711669119820 | RATE1 |

## Results

- `common`: **29**
- `non_common`: **3**
- `split`: **2**
- `unresolved`: **10**

Classification changes from the queue candidate `common`: **OBE, MIC2, EOP, IHT, PVX**.

### Factual corrections

- **OBE** — Penn West income-trust units are `non_common` through 2010-12-31; after the trust-to-corporation conversion, Penn West/Obsidian common shares are `common` from 2011-01-03.
- **PVX** — Provident Energy Trust units are `non_common` through 2010-12-31; Provident Energy Ltd. common shares are `common` from 2011-01-03.
- **MIC2** — Macquarie Infrastructure Company LLC interests are `non_common` as an other non-common legal instrument.
- **EOP** — Equity Office Properties Trust common shares of beneficial interest are trust interests and therefore `non_common` under the supplied policy.
- **IHT** — InnSuites Hospitality Trust shares of beneficial interest are trust interests and therefore `non_common`.

## Unresolved worklist

The following cases remain explicitly unresolved. No default classification is applied:

- BEPC — exchangeable subordinate voting-share hybrid requires policy/class closure.
- BFXXQ — predecessor/successor CUSIP class continuity incomplete.
- TRIN1 — three-CUSIP identity chain incomplete.
- ABVEF — two-CUSIP identity transition incomplete.
- HAPN — legal class across CUSIP transition incomplete.
- CNSY — seven-CUSIP long identity chain incomplete.
- AIFC — four-CUSIP identity chain incomplete.
- EMWPF — foreign-issuer identity/class continuity incomplete.
- BTCT — multi-jurisdiction five-CUSIP identity chain incomplete.
- RATE1 — three-CUSIP predecessor/reorganization chain incomplete.

## Validation

- Assignment formula reproduced: PASS
- Every assigned case exactly once: PASS
- Zero foreign cases: PASS
- All resolved cases include legal-class findings and source/evidence locators: PASS
- Explicit unresolved worklist: PASS
- `outcome_information_used=false` for every case: PASS

The review uses legal identity, legal form, security class, CUSIP/name/reorganization continuity, and corporate-action history only. Future prices, returns, ranks, Champion selections, survival, profitability, future index membership, and strategy outcomes were excluded.

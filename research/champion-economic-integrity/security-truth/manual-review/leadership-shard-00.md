# Leadership security-truth review — shard 00

Date: 2026-09-06  
Base: `research/champion-security-truth-held-pending-integration` @ `5b9d9ea2e378044f49d217fe311b36b45c73124c`  
Branch: `research/champion-security-truth-leadership-00`  
Contract: `research/champion-economic-integrity/PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md`

## Deterministic assignment retained before research

Filter `priority == P2_LEADERSHIP`, sort ascending by `(security_id as integer, ticker)`, assign zero-based `i`, select `i % 4 == 0`.

P2 leadership rows: **182**  
Assigned rows: **46**

```text
  0  4842876510331218     TIRXF
  4  23239698889305908    CZOOF
  8  47199860771341941    SYNE
 12  87519734003931149    ZEVY
 16  106569218926078867   IDMCQ
 20  123898231451370628   TRIRF
 24  159505778493115423   WPP1
 28  189720321740141225   BOXDQ
 32  210042061840655813   LNAI
 36  223649094030910552   USPI1
 40  238785323839507876   ARA1
 44  255537641544311712   AUVIQ
 48  280655384494202876   CYRNQ
 52  302421230588989111   WEWKQ
 56  319248286586397404   OLOX
 60  352648217497685819   IVPR
 64  365837557702778102   RENX2
 68  389428543536150575   AIFA
 72  419581290243521131   CIGI
 76  450154553112428191   ATPC
 80  463006732998201278   THMRQ
 84  487329770828806227   RKTO
 88  504872827721303870   DFSC
 92  543083518703645156   XSELY
 96  574441503402547337   MPG1
100  616207656933335880   KMG1
104  638843741005544965   XYLO
108  667140484759602374   ALD1
112  699738264904030965   MFLTF
116  720912212270057585   ALIZY
120  739770619759153468   DEO
124  766906363217850051   MLNTQ
128  815365834997670741   CYCU
132  848418269852065962   MODVQ
136  872933797384182660   GNSS1
140  887467891507310080   WEJOQ
144  893706224077607177   PCLA
148  916254279996296439   SAIH
152  953705492274993059   DCOY
156  971433568129744166   IMVIQ
160  994753932541300734   HAN
164  1023640270036081506  LIN2
168  1041589921112577847  SMX
172  1062221465538336135  BIPC
176  1102529782480971848  CNTFY
180  1141671989288289515  NXL1
```

## Results

- `common`: **22**
- `non_common`: **1**
- factual type splits: **0**
- unresolved: **23**

### Classification change

`ARA1` (`238785323839507876`) changes from the queue candidate `common` to **`non_common`**. Aracruz issuer filings identify the U.S. ADS program as representing **Class B preferred shares**. The reviewed depositary/CUSIP changes do not establish conversion to common equity.

### Resolved common cases

`TIRXF`, `ZEVY`, `WPP1`, `BOXDQ`, `LNAI`, `AUVIQ`, `CYRNQ`, `WEWKQ`, `OLOX`, `AIFA`, `CIGI`, `ATPC`, `RKTO`, `DFSC`, `MFLTF`, `ALIZY`, `DEO`, `MLNTQ`, `CYCU`, `PCLA`, `IMVIQ`, `BIPC`.

The machine-readable JSON records the exact legal-security-type label, interval, CUSIPs, evidence URLs, source documents, factual findings, identity-transition analysis, contradiction search, and `outcome_information_used=false` for every case.

## Unresolved worklist

- `CZOOF`
- `SYNE`
- `IDMCQ`
- `TRIRF`
- `USPI1`
- `IVPR`
- `RENX2`
- `THMRQ`
- `XSELY`
- `MPG1`
- `KMG1`
- `XYLO`
- `ALD1`
- `MODVQ`
- `GNSS1`
- `WEJOQ`
- `SAIH`
- `DCOY`
- `HAN`
- `LIN2`
- `SMX`
- `CNTFY`
- `NXL1`

These remain unresolved because one or more queue-listed CUSIP/name/reorganization transitions could not be bound to sufficient primary evidence for the complete relevant interval. Candidate common labels were not promoted on incomplete evidence.

## Validation

- Exact deterministic assignment reproduced: **PASS**
- Every assigned case represented exactly once: **PASS**
- Foreign cases: **0**
- Every resolved case evidence-backed: **PASS**
- Explicit unresolved worklist: **PASS**
- `outcome_information_used=false` for all 46 cases: **PASS**
- Replay/backtest executed: **NO**

The JSON file is the machine-readable authority for this shard. Its Git blob SHA is recorded by GitHub; the final report records the byte-level SHA-256 when available from exact readback.

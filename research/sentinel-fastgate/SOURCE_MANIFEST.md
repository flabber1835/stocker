# Sentinel Fastgate source and evidence manifest

Strategy: `sentinel-fastgate` v1  
Canonical branch: `research/sentinel-fastgate-2026-08-24`  
Base: `main@722aa14ae0e452437b80425528ba30fcf133b029`  
Authoritative strategy lineage: `22ebcf48addadbc7ec4531df415041d1b8674f48`  
Strategy digest: `c1434409d8f91d8aa94405eccc20bf2f764479a9208a6030e60564999a281492`  
Canonical source SHA-256: `c60beab918b49ce0610445bb07d273d28d5e4b2fc3ddd702efe54ea251f12f54`  
Canonical source Git blob: `486de36a6764b9bab3a3b1b424c9930c3f0b61c1`

| File | Role | Bytes | Git blob SHA-1 |
|---|---|---:|---|
| `README.md` | canonical strategy definition and evidence index | 5,237 | `39080dec727e3e215caa31da8551d3cebfaaaad2` |
| `RESULTS.md` | retained historical results and qualification | 4,072 | `9c8303cecbdbb050d3b4826a4b55351fdbedc598` |
| `STRATEGY_IDENTITY.json` | deterministic strategy and dependency identity | 2,775 | `33109112cc91b2415d96aa560190d4c636dcd6d7` |
| `TEST_RESULTS.txt` | executed canonical source tests | 3,430 | `9768fc7b1d514b24b0ebb7addeb039456e96f694` |
| `control_parity.json` | unchanged-control parity evidence | 404 | `0c16ab6c1be8e48358f11d8ec5b717cc9229e5cd` |
| `episode_attribution.csv` | changed-exposure episode attribution | 489 | `939d82483dfe82e4075fecd199b8fc1a57cf418f` |
| `factorial_attribution.csv` | 2×2 mechanism attribution | 993 | `cf9c87de91502478767c10fa1bd424dacd7c1d0b` |
| `metrics_5_10_15_20.csv` | 5/10/15/20-year metrics | 2,590 | `8b2edd3869f42b37f548b73845937681daab19c2` |
| `provenance.json` | lineage, reference scope, and limitations | 2,934 | `241eb08e084417165dd1d1555295df75b658fa36` |
| `retained_confirmation_mapping.csv` | retained causal schedule mapping | 533 | `829b1097c051e080de283dc9063323c2d88c1a22` |
| `sentinel_fastgate_reference.py` | single canonical Fastgate source | 34,579 | `486de36a6764b9bab3a3b1b424c9930c3f0b61c1` |
| `sentinel_fastgate_transitions.csv` | retained transition audit | 4,310 | `ef5ae4ec2557cc2d5a7c50a58fbbc11421a363d1` |
| `test_sentinel_fastgate_reference.py` | canonical source tests | 13,042 | `7fc1615908cd5b0351ad0845d5c738aa9c1783e7` |

Canonical test source SHA-256: `a8bd6cb513d11ad53075dc6107320f047a699a93e9ced2b381b426bd1cc95021`.

The manifest intentionally excludes itself to avoid a self-referential hash. Git blob IDs are content-addressed and were fetched back from GitHub after each write. The single canonical source includes the raw-history residual/Jaccard builder, FAST confirmation, persistence gate, first-warning ownership, state codec, identity, and dependency verification.

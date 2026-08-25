# Sentinel Fastgate source and evidence manifest

Strategy: `sentinel-fastgate` v1  
Base: `main@722aa14ae0e452437b80425528ba30fcf133b029`  
Strategy digest: `7a18d1c66f221848ccdb327d1851c14e8d75f7c6d9a3fd51e390c6adef2d67b5`  
Canonical source SHA-256: `db56f26ae8251d6d3baf7f49b87d598af22ef34d60a6b32ca683a546a44326a4`

| File | Role | Bytes | Git blob SHA-1 |
|---|---|---:|---|
| `README.md` | strategy definition and evidence index | 3,539 | `38c05810808ceb81410dd3336d562ba6c6d1c94a` |
| `RESULTS.md` | retained historical results | 2,755 | `5e85a4255f186013559f600cddc27129d6c3b855` |
| `STRATEGY_IDENTITY.json` | deterministic strategy identity | 1,825 | `8d1feb46ef95922db2f4cb9cdd4b964f90404c67` |
| `TEST_RESULTS.txt` | executed canonical source tests | 1,993 | `63a2f784fec21edfcf1919235a909eb749b5689a` |
| `control_parity.json` | unchanged-control parity evidence | 404 | `0c16ab6c1be8e48358f11d8ec5b717cc9229e5cd` |
| `episode_attribution.csv` | changed-exposure episode attribution | 489 | `939d82483dfe82e4075fecd199b8fc1a57cf418f` |
| `factorial_attribution.csv` | 2x2 mechanism attribution | 993 | `cf9c87de91502478767c10fa1bd424dacd7c1d0b` |
| `metrics_5_10_15_20.csv` | headline metrics | 2,590 | `8b2edd3869f42b37f548b73845937681daab19c2` |
| `provenance.json` | lineage and limitations | 1,920 | `61ae64808f4b4b18854be98dda8b89a4f13f30c1` |
| `retained_confirmation_mapping.csv` | retained causal schedule mapping | 533 | `829b1097c051e080de283dc9063323c2d88c1a22` |
| `sentinel_fastgate_reference.py` | single canonical strategy source | 16,870 | `a1d4107ee552cba64373d896f49cebd3196087a5` |
| `sentinel_fastgate_transitions.csv` | transition audit | 4,310 | `ef5ae4ec2557cc2d5a7c50a58fbbc11421a363d1` |
| `test_sentinel_fastgate_reference.py` | canonical source tests | 6,159 | `3c6687a1eb817d48710d2b1935e5000900e8ffd1` |

The manifest intentionally excludes itself to avoid a self-referential hash.

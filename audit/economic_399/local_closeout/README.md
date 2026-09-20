# Stage 1 local closeout evidence

Reviewed quantity/restore code: `67a9c6a9`; integrated head and exact source hashes
are in `source-provenance.json`. Verified main: `eaae66f9e6626306f8b233fd723d25b278e13351`.
The [review, finding map and handoff](../../../docs/stage-one-local-closeout.md)
retain the economic oracles, failures, provider boundaries and remaining work.

Offline image: `sentinel-test:ci`, digest
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
Python 3.12.13, PostgreSQL 17.11. No NAS, real broker, provider credentials,
capability promotion, golden repin or xfail was used.

Exact Docker/pytest commands head each retained log. Test groups run through:

```
python audit/economic_399/rolling_status/run_local.py test <selectors from log>
python audit/economic_399/local_closeout/run_local.py
python audit/economic_399/local_closeout/run_local.py rounded_committed_sum
python audit/economic_399/local_closeout/prior_sources.py
```

| Retained log | Result |
| --- | --- |
| `local-numeric-before.log` | Six demonstrated sizing failures, seven controls pass |
| `local-numeric-regression.log` | 195 pass, 33.56 s |
| `local-quantity-before.log` | Four adjoining quantity/action failures, 35 pass |
| `local-quantity-regression.log` | 302 pass, 37.64 s |
| `local-quantity-mutants.log` | Partial campaign; redundant negative-denominator mutant survived |
| `local-quantity-mutants-v2.log` | 39 controls pass; 12 intended mutants detected |
| `local-committed-mutant.log` | 40 controls pass; committed-sum rounding detected |
| `local-populated-restore.log` | Correct missing-authority refusal in incomplete fixture |
| `local-populated-restore-v2.log` | Episode-map fixture assertion error after successful restore/advance |
| `local-closure-boundaries.log` | 168 pass, one warning, 145.48 s; corrected populated physical restore included |
| `local-integration-ownership.log` | 153 pass, 311.71 s; identity, membrane, process death, entitlement and rolling continuation |
| `local-syntax.log` | Changed Python sources parse |
| `local-pyflakes.log` | Pre-existing decision import/redefinition warning plus subsequently corrected audit f-string warning; final static check still required |

Counts overlap. Initial raw bytes are in `initial-evidence.zip`; its member
SHA-256 values are retained separately. Prior golden/evidence archives remain
untouched. The two available PIT manifests remain separately identified.

## Resource failure: still open local work

```
python audit/economic_399/local_closeout/run_stages.py --source ../stage-one-resource-source --evidence ../stage-one-resource-8408 --universe 8408
python audit/economic_399/local_closeout/run_stages.py --source ../stage-one-resource-source --evidence ../stage-one-storage-before --universe 8408 --stages storage
```

The source directory is an immutable copy of the working production files,
bound by `resource-source-SHA256SUMS.json`; it is not an assertion that the entire
later integration head was benchmarked. The inherited bounded generator only
extends cardinality; prior resource harnesses/artifacts remain unchanged.

Publication of 2,522,400 synthetic rows completed, but initial observation
assembly OOM-killed a PostgreSQL backend under 1 GiB. `memory.events` records
one OOM/kill. The SQL pairwise JSONB assembly statement is retained in the server
log; initialization returned failure. The independent storage-only probe also
fails at that statement. No status/HTTP/advance pass exists at this scale yet.
Runtime stays capped at 4 GiB/2 CPU, panel at 512 MiB/0.5 CPU and PostgreSQL at
1 GiB/1.5 CPU, with swap prohibited. This is P2 L09 code/resource work, not a
provider-only blocker and not an economic return measurement.

Required CI, the resource repair, final evidence reconciliation, authoritative
production-window admission, provider/policy E1-E4 and NAS N1 remain unresolved.

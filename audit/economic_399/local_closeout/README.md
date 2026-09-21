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

## Retained initial resource failure

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
fails at that statement. At that source revision no status/HTTP/advance pass existed at this scale.
Runtime stays capped at 4 GiB/2 CPU, panel at 512 MiB/0.5 CPU and PostgreSQL at
1 GiB/1.5 CPU, with swap prohibited. This is P2 L09 code/resource work, not a
provider-only blocker and not an economic return measurement.

Those initial results required a resource repair and final remeasurement. The
follow-up and final dispositions below supersede that implementation status.

## Storage and read follow-up

The paragraph above describes the retained initial failure, not the current
implementation disposition. The compressed storage repair passes PostgreSQL
16.14 and 17.11 storage checks, populated physical restore and complete 8,408-name
initialization. Full panel reads then exposed a second memory defect; private
canonical views address its duplicate feed arrays. The final full capped rerun
is now complete, with the pressure limitations below. See [exact follow-up commands/results](followup-commands.md).

`storage-followup-evidence.zip` retains 60 unedited log/source/manifest members;
`storage-followup-SHA256SUMS.json` binds each member's bytes and SHA-256.
`followup-source-provenance.json` binds the reviewed production source at
`5d309d5c869b5c80a057f037f774491fabd0484f` (last production edit `449c69a5`).
This archive preserves the unsuccessful pairwise SQL candidate, successful
compressed probes, the read allocation diagnostic showing the panel budget excess,
actual before/after mutation failures, PostgreSQL 16 evidence and the CI anchor
failure artifact. The allocation diagnostic itself exits successfully; its
531,144 KiB peak explains why the real 512 MiB processes failed and is not a
qualifying pass. Full resource campaign logs are retained separately after
completion. The prior `initial-evidence.zip` and all golden artifacts are intact.

Both derived PIT packages and the original raw Sharadar archives have now been
identified separately. `raw-input-inventory.json` proves the reconstructed SFP
source hash and records the available raw columns/date coverage and positive
TICKERS structural check. It does not invent the missing production acquisition
bracket, reference agreement, dated admission or publication/coverage receipts.
The finding map and locally feasible L09 measurements are complete. Delivery/CI,
external authority/budget/headroom and NAS qualification remain separate gates.

`oracle-ci-followup-evidence.zip` and its member SHA manifest retain six unedited
logs: CI's shared-process allocation failure, the isolated five-control/four-mutant
success, two populated published-price accounting controls, the invented-cash
falsifier, syntax and clean targeted Pyflakes output. The accounting oracle uses
published source prices rather than the strategy's retained marks. Forty-two
changed Python sources parse. The restored-copy mutant allocates 11,445,814 bytes
and still fails the unchanged 4 MiB threshold in its fresh interpreter.

## Final resource and economic evidence

`resource-evidence.zip` contains 94 verified members (353,150 bytes), SHA-256
`f4b634b5be12770d23f658b267215eb40ca314872ec8e74b8ec9066771d47b2c`.
`resource-SHA256SUMS.json` binds the archive and each member. It preserves the
failed intermediate full campaign, all eight completed final stages, PostgreSQL
metrics/exit states, both coordinator resumptions, original and adopted Docker
logs, immutable source manifests, exact host commands, reviewed-head CI snapshot
(two lanes still pending when captured), and final syntax/static checks.
The initial and storage-follow-up archives are unchanged.

Reproduce the report from an extracted `final/` directory and its immutable
source copy (or restore that copy from the bound Git/source bytes):

```sh
python audit/economic_399/local_closeout/resource_report.py --evidence ../stage-one-resource-read-8408 --source ../stage-one-resource-oracle-source --output audit/economic_399/local_closeout/resource-results.json
```

[`resource-results.json`](resource-results.json) records every cap, timing and
counter and binds all 406 production files to reviewed integration `e77c8285`.
All eight stages finish with zero OOM; PostgreSQL is **COMPLETED_WITH_PRESSURE**:
52,181 max-boundary events, peak 1,074,294,784 bytes, a 552,960-byte transient
excess over its enforced 1 GiB limit. This does not earn headroom acceptance.
Panel processes stay under their 512 MiB cap, including two reads at each frontier.
Actual reads take 204–224 seconds; no accepted latency budget is inferred.
The full HTTP fixture returns 200 and a verified shadow row, but overall panel
status remains fail because real operational authorities are deliberately absent.

Twenty positions cost $98,816.520 plus $98.816520 entry fees. The independent
published-price oracle explains NAV $99,901.18348 and cash $1,084.6634800000074
with only sub-$1e-8 representation differences. This is flat-price accounting,
not twenty-year performance or proof of historical decision equivalence.
No required provider/policy, authoritative real-window, latency/headroom or NAS
gate is closed. The deferred replay remains Stage 2. Final syntax parses 43
changed Python files; the final audit helpers pass Pyflakes and whitespace checks.

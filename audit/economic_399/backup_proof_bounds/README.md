# Backup proof closure evidence

Base independently fetched: `3c4fb030b3ad06bc8996771479b2d68b71cb17e6`.
Delivery is a feature-branch PR against main. No NAS, broker account or provider
capability was accessed or modified. The original economic goldens are unchanged.

The [design and NAS handoff](../../../docs/backup-proof-resource-bounds.md) and
[certification ledger](../../../docs/economic-code-closure.md) record three fixed
defects and the remaining maintenance/resource/provider/data/deployment gates.
The runtime no longer allocates over-budget WAL-name ranges or re-stats payload
length inside the hash read. More significantly, the actual PostgreSQL acceptance
test exposed coarse timestamp reuse after same-size replacement. Fresh bounded
content verification replaces metadata-based reuse. That is a deliberate safety
contract correction with an explicit extra-I/O qualification requirement.

Exact reproducible commands from repository root:

```text
python audit/economic_399/backup_proof_bounds/run_local.py regression
python audit/economic_399/backup_proof_bounds/run_local.py backup
python audit/economic_399/backup_proof_bounds/run_local.py mutations
python audit/economic_399/backup_proof_bounds/run_local.py payload --segments 64
python tools/validate_test_responsibility.py --base 3c4fb030b3ad06bc8996771479b2d68b71cb17e6 --output ownership.json
git diff --check
```

The runner prints exact Docker arguments. Offline local image:
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
Python 3.12.13, PostgreSQL 17.11. Source is read-only, network disabled, credentials
absent. GitHub builds and tests its own exact-head image; these local results do
not represent that image or deployed PostgreSQL 16.

* Final focused campaign: **94 passed in 15.98 seconds**.
* Final broader backup/physical campaign: **252 passed in 236.38 seconds**.
  Counts overlap. Four media failure classes cover each of 18 observed SQL reads
  (72 fault injections); the test does not freeze an implementation read count.
* **Nine mutants killed** at intended behavioral assertions; failures from
  collection or infrastructure do not count as killed.
* Maximum-horizon payload measurement: 64 x 16 MiB sparse synthetic files;
  2 GiB read per two-pass proof, 128 hash operations. Final samples: 2.432, 1.559,
  1.550 seconds; backend peak RSS 35,040 kB; whole-container peak 1,215,889,408
  bytes under a 2 GiB/two-CPU cap. This is a payload microbenchmark, not a full
  production caller or physical-storage qualification.

`results.zip` retains every campaign: the first 89-pass baseline; the 92-pass /
one-failure actual PostgreSQL timestamp discovery; the later 94-pass result;
the broader run with 60 stale-count failures and 248 passes; the final 252-pass
run; nine mutation traces; both payload measurements; ownership and static
results. The stale-count fixture was replaced with fault injection over every
observed read. The precision-collision test is deterministic and still reads
actual payload bytes through PostgreSQL; it no longer relies on wall-clock
position within a second. No failing gate was converted to an xfail.

`source-provenance.json` hashes the final changed Python and test source with
Git LF normalization. `SHA256SUMS.json` authenticates the retained package.
Source/evidence byte checks are repeated against committed Git blobs before push.
Economic certification and Step 1 remain open.

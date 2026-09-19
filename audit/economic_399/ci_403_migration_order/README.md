# PR 403 migration-order test follow-up

Failing head: `a92362e0847358cbe3b987c9aa73bc2045be635d`.
[CI main-suite job](https://github.com/flabber1835/stocker/actions/runs/35421927173/job/105841545067)
reported **2 failed, 5009 passed** in 2129.46 seconds. All other test lanes and
five independent workflows passed. The two failures searched a migration
method's source text for an inline stop call now owned by `_quiesce_database`.

Both tests now execute their actual deployment owner, including the shared
quiescence helper and generated migration Python. Only external process and
database operations are recorded locally. The ordered trace requires durable
fencing, both worker stops, PostgreSQL readiness, backup verification, physical
replay, another fence, behavioral migration and feed migration. Missing or
reordered operations fail independently of helper extraction.

Local relevant regression: **94 passed in 20.61 seconds**. All four targeted
mutants are killed after passing baselines: omit automation stop, replace
physical replay with a status read, omit core feed migration, omit bootstrap
feed migration. Two changed Python files parse; `git diff --check` passes.
No production source, financial expectations, capability, golden or CI gate
changed. The final GitHub head still requires its own complete CI validation.

`commands.json` records exact selectors and Docker environment. `results.zip`
retains raw output; `SHA256SUMS.json` authenticates files and archive entries.
This supplements, without rewriting, the earlier evidence packages.

# Runtime manifest bound evidence

Verified base: `65e261312ec219e014f062c0b6b374066db19d75` (owner-merged #405).
Branch: `codex/backup-manifest-bound`, PR-only delivery against `main`.
The containing commit and `source-provenance.json` identify reviewed source.
This branch starts from main, not the still-open archive-integrity PR #406.
Both fixes are needed; no #406 check or artifact was changed.

The selected manifest formerly used an unlimited file read and JSON parse.
The presence probe could also split a valid UTF-8 character at its 1 MiB text
boundary. Read presence as one binary byte, then allow JSON parsing only after
a bounded 8 MiB + one-byte read proves the selected manifest fits the new limit.
Do not grant range authority to an accepted prefix of an oversized file.

## Reproduction

Run from the checkout root:

```text
python audit/economic_399/manifest_bound/run_local.py regression
python audit/economic_399/manifest_bound/run_local.py backup
python audit/economic_399/manifest_bound/run_local.py mutations
python audit/economic_399/manifest_bound/run_local.py measure
python tools/validate_test_responsibility.py --base 65e261312ec219e014f062c0b6b374066db19d75 --output ownership.json
git diff --check
```

Local launcher:
`C:/Users/mbron/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
Runners retain their exact Docker arguments in each log. Runtime is the existing
offline `sentinel-test:ci` image
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
Python 3.12.13, PostgreSQL 17.11, psycopg 3.3.4; source is mounted read-only,
network disabled, memory limited to 2 GiB and CPUs to two. Databases and files
are disposable. `--image <accepted-test-image>` supports later NAS qualification.

## Results and limits

- **91 focused regression passes** on the finalized acceptance tests.
- **304 broader backup/physical-recovery passes in 239.02 seconds**. This run
  preceded addition of the growth-after-presence case, which passed in the final
  focused run. Counts overlap; they are not independent totals.
- **Three mutants killed**: missing overflow byte accepted a valid prefix;
  missing parse gate reached PostgreSQL's decoder on oversized invalid bytes;
  the old text probe broke a valid multibyte character. Final mutation evidence
  checks the decoder exception cause, rather than relying on its message text.
- **475 owned test modules, zero unowned; seven changed Python files parse and
  have zero pyflakes findings; diff whitespace clean.** Static inspection used
  `ast.parse` and `pyflakes.api.checkPath` on every path in the provenance map.
- Dense exact-limit manifest: **8,388,608 bytes**, **90,199 synthetic file
  entries**, three SQL calls in **0.229, 0.156, 0.159 seconds**. Backend high-water
  RSS **140,376 kB**; whole-container peak **277,151,744 bytes**. This measures
  the manifest SQL phase only on local PG17.11, not full authority or NAS I/O.

Actual SQL tests include literal WAL arithmetic, short/exact/oversize files,
invalid and missing media, repair, a sparse file larger than 1 GiB, a valid UTF-8
boundary crossing, and growth after presence detection. Production `require`
tests verify no fallback to an older valid base, no proof advancement or commits
after refusal, and successful recovery. The broader physical suite exercises
the real runtime authority against locally generated physical backup metadata.

`results.zip` retains original and final focused runs, the broader run, original
and final mutation traces, the resource measurement and ownership output.
`source-provenance.json` hashes Git-LF-normalized source; `SHA256SUMS.json` binds
the package. Committed blob checks are required before push. Existing audit
packages, golden returns, provider capabilities and backup files are unchanged.

The 8 MiB ceiling is an admission decision requiring measurement on deployed
manifests. See [design and concrete NAS criteria](../../../docs/backup-manifest-runtime-bound.md).
Step 1 and economic certification remain open: directory enumeration, recurring
verified maintenance, horizon rollover/retention, other recorded resource gaps,
provider guarantees, historical replay and NAS qualification are not closed here.
No NAS or real broker account was accessed.

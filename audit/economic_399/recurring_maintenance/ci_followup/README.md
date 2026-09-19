# PR 413 inventory-bound CI follow-up

GitHub run 35466451656, job 105959553378, tested merge
`450e6070386552af8998dfdcbebebaf773c1d4cf` (head `6aacb0d2`).
It reported one failed assertion and 305 passing cases. The guard refused
before deletion as required; the test incorrectly included receipt fixture
acquisition in its four-read budget. Linux enumeration can put three bases
before bookkeeping entries, exposing that extra setup read.

Acquire the receipt before instrumentation, and exercise both base-first and
bookkeeping-first enumeration explicitly. Each retention call still permits
only one selected-base read plus at most three inventory metadata reads, and
must refuse with the inventory-limit reason before journaling or deletion.
Production policy/code is unchanged. The inventory guard-removal mutant uses
the base-first case; it still fails. No economic oracle or golden was changed.

Validation in offline `sentinel-test:ci`:

```
python audit/economic_399/recurring_maintenance/run_local.py regression
# 371 passed in 260.39s
python audit/economic_399/recurring_maintenance/run_local.py mutations
# all 15 mutants KILLED
```

Counts overlap earlier campaigns. Raw logs are retained byte-for-byte in
`raw-logs.zip`; `raw-log-SHA256SUMS.json` binds each archive member to the original
committed bytes. Current changed-source and package hashes remain beside this
file. The earlier results.zip and its source hashes
remain unchanged historical evidence. NAS/provider/certification gates remain
open. This repairs validation portability, not an economic calculation defect.

The subsequent operator job (run 35467141288, job 105962065156) passed its
tests but failed `git diff --check HEAD^ HEAD` because the loose raw logs
contained CRLF and trailing spaces. Archive packaging preserves those exact
bytes without weakening the whitespace check or rewriting evidence. Validate
both `git diff --check HEAD^ HEAD` and the complete PR diff before delivery.

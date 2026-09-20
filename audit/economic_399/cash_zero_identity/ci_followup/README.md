# PR #424 legacy zero-cursor CI fixture repair

GitHub run 35526742726, job 106120850855 failed four legacy cursor cases.
Their MagicMock returned the aggregate cash-total row `(0, False)` for every
SQL query, including the newly added zero-identity lookup. That malformed row
correctly refused as contradictory evidence. The previous test never exercised
persistence or the real replay cursor.

Replace that mock with isolated PostgreSQL, seed the documented legacy v2/v3
cursor, replay both REST/SSE intervals at unchanged and later time boundaries,
and assert the persisted cursor and retained zero identity. Production code and
provider capabilities are unchanged. This makes the fixture stronger; it does
not relax the correction guard or change an economic oracle.

```
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_alpaca_simulation_review_regressions.py tests/sentinel/test_alpaca_simulation_durability.py
# 51 passed in 38.62s
```

Syntax parsing passed. Exact logs and their hashes are retained beside this file.
Required GitHub CI must rerun. Provider and NAS gates remain unresolved.

## Main-lane timeout at 6ac2805f

Run `35536913292`, main job `106147896599`, passed **4,957 general tests in
1,293.23 seconds** and reached 79% of the rolling partition before the
45-minute job budget cancelled it. The exact-head and synthetic-merge aggregates
correctly refused the cancelled dependency. No economic assertion failure was
reported in the completed portion; the unfinished portion is not a pass.

Apply the same documented budget correction as #425: 75 minutes for
`sentinel-main` alone, with every other lane retaining 45 minutes. The test
selection, two processes, JUnit merge, assertions and required dependency gates
stay unchanged. Current-main base `48f88fd4f3957c0dfc264e2eef2e35ecd753c9c1` is
already an ancestor of reviewed PR head `6ac2805f3a645c9c7a59a455c2ff6cbfd21e9a19`.
This remains PR-only delivery; no merge or NAS/broker access occurs.

```sh
python -m pytest tests/scripts/test_sentinel_ci_parallel_evidence.py -q -p no:cacheprovider
# 54 passed in 2.11 seconds, cached test image, network none, 512 MiB / 1 CPU
```

The executable workflow cases retain exact module conservation and propagate
either partition's failure. AST, Pyflakes and whitespace checks pass. The
production/Compose diff against the reviewed PR head is empty. No unrelated
economic suite was rerun. `timeout-evidence.zip` retains the raw cancelled
job/log (163,180 bytes); `timeout-SHA256SUMS.json` binds both members. Its SHA-256
is `88f4fdd6ed4a7ed01a54ef1f443f3dad416c93dcba2ee798d3c033ee48690e64`.
Fresh full GitHub CI remains required before merge.

## Integration with merged #421

Run 35529655970, job 106128025877 refused because the synthetic merge first parent differed from the event advertised base after main advanced. The fixture and economic tests did not cause this failure. Merge current main `e4c9b1439962af3353e7f0c0ec3d84aee1f0aeb7` without changing either guard. The same targeted command above passes **58 tests in 23.96 seconds** at integration commit `6042debb`. Exact CI and local output are retained in `main-integration-evidence.zip`. Required CI must rerun against this updated branch.

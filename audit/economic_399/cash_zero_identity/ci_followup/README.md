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

## Integration with merged #421

Run 35529655970, job 106128025877 refused because the synthetic merge first parent differed from the event advertised base after main advanced. The fixture and economic tests did not cause this failure. Merge current main `e4c9b1439962af3353e7f0c0ec3d84aee1f0aeb7` without changing either guard. The same targeted command above passes **58 tests in 23.96 seconds** at integration commit `6042debb`. Exact CI and local output are retained in `main-integration-evidence.zip`. Required CI must rerun against this updated branch.

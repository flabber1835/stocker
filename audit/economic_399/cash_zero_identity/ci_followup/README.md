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

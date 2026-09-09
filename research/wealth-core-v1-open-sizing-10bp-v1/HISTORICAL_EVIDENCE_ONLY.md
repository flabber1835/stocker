# Historical evidence only

This branch is no longer an active execution-harness authority.

The completed open-sizing experiment remains pinned to original evidence head:

`3dc74a8e54fdfe6e8368a8db3be0ecd127ee4689`

Do not use `run_open_sizing.py` from this branch for new experiments. Its whole-share close-admission rule predates the one-share affordability correction discovered in the Median-5 full-PIT replay.

The single active research execution harness is:

`research/median5-open-sizing-10bp-ex3-v1/canonical_execution_harness.py`

on branch:

`research/median5-open-sizing-10bp-ex3-v1`

Canonical whole-share close admission requires:

`cash_above_10bp_reserve >= close_price * (1 + COST)`

Share quantity remains determined only at the next valid open.

The workflow on this historical branch is intentionally retired and cannot run an economic replay.

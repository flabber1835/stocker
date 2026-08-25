# Sentinel Fastgate

**Strategy ID:** `sentinel-fastgate`  
**Version:** `1`  
**Status:** research candidate; not production activated or certified  
**Pinned base:** `main@722aa14ae0e452437b80425528ba30fcf133b029`

Sentinel Fastgate is the canonical name for the previously described narrow alpha-recovery candidate. The former labels `narrow candidate`, `D_narrow_combined`, and `FAST confirmation + externally owned provisional warning` are superseded by **Sentinel Fastgate**.

## Canonical source of truth

[`sentinel_fastgate_reference.py`](sentinel_fastgate_reference.py) is the single canonical source file for every behavior introduced by Sentinel Fastgate.

- SHA-256: `0acc3003c35de1901d9313c3cec7e27d949c53cf3183a1d6071501c241bd1c39`
- Strategy digest: `46310578a0d7001d23d452aabba87d167dfb6a1ed2dd0607cda6e0ee73a770bc`

The file implements the prior-only 252-session residual-correlation and co-distress confirmation algorithm, exact symbolic FAST branch handling, first-warning 55% ownership, persistence confirmation, post-LD-RC composition, state serialization, strategy identity, and dependency-blob verification.

No other Python file in this directory defines strategy behavior. [`backtest_harness.py`](backtest_harness.py) is evidence infrastructure only.

## Architecture boundary

```text
prior-only peer histories ending t-1
        -> Sentinel Fastgate confirmation
        -> unchanged authoritative native Sentinel
        -> unchanged authoritative Simplified Concordance LD-RC
        -> optional external 55% first-warning ceiling
        -> next-session-open execution
```

A first unconfirmed warning is invisible to native Sentinel and LD-RC, so clearing it cannot open or prolong an LD-RC recovery episode. Causal confirmation or a second consecutive warning passes the existing FAST signal into the unchanged native severe controller.

## Retained evidence

- [`RESULTS.md`](RESULTS.md) — 5/10/15/20-year results and verdict
- [`metrics_5_10_15_20.csv`](metrics_5_10_15_20.csv) — headline metrics
- [`factorial_attribution.csv`](factorial_attribution.csv) — confirmation/provisional 2x2 attribution
- [`episode_attribution.csv`](episode_attribution.csv) — changed-exposure episode attribution
- [`sentinel_fastgate_transitions.csv`](sentinel_fastgate_transitions.csv) — transition audit
- [`control_parity.json`](control_parity.json) — exact unchanged-control gate
- [`retained_confirmation_mapping.csv`](retained_confirmation_mapping.csv) — retained causal schedule mapping
- [`provenance.json`](provenance.json) — data lineage and limitations
- [`STRATEGY_IDENTITY.json`](STRATEGY_IDENTITY.json) — deterministic identity payload
- [`TEST_RESULTS.txt`](TEST_RESULTS.txt) and [`BACKTEST_STDOUT.txt`](BACKTEST_STDOUT.txt)
- [`SOURCE_MANIFEST.md`](SOURCE_MANIFEST.md) — hashes for all retained files

## Verification

```bash
python -m unittest -v test_sentinel_fastgate_reference.py
python backtest_harness.py
```

The harness refuses to publish candidate metrics unless the unchanged current arm reproduces native decisions, LD-RC decisions, effective allocations, and daily NAV within the retained exact tolerance.

## Promotion boundary

The source now specifies the dynamic signal end to end. The retained historical run still uses the previously calculated causal confirmation schedule mapped onto the authoritative tape. A fresh per-security point-in-time reconstruction must reproduce those decisions before production promotion.

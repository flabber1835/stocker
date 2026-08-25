# Sentinel Fastgate

**Strategy ID:** `sentinel-fastgate`  
**Version:** `1`  
**Status:** research candidate; not production activated or certified  
**Pinned base:** `main@722aa14ae0e452437b80425528ba30fcf133b029`

Sentinel Fastgate is the canonical name for the previously described narrow alpha-recovery candidate. The former labels `narrow candidate`, `D_narrow_combined`, and `FAST confirmation + externally owned provisional warning` are superseded by **Sentinel Fastgate**.

## Canonical source of truth

[`sentinel_fastgate_reference.py`](sentinel_fastgate_reference.py) is the single canonical source file for every decision rule introduced by Sentinel Fastgate.

- Git blob: `a1d4107ee552cba64373d896f49cebd3196087a5`
- Strategy digest: `7a18d1c66f221848ccdb327d1851c14e8d75f7c6d9a3fd51e390c6adef2d67b5`

The file defines the exact causal-snapshot thresholds and fusion, symbolic FAST branch classification, first-warning 55% ownership, persistence confirmation, post-LD-RC composition, state serialization, deterministic identity, and dependency-blob verification.

The raw per-security residual-correlation/co-distress feature builder is deliberately an upstream data adapter. Its histories must end before the decision session, and a fresh point-in-time reconstruction remains required before promotion.

## Architecture boundary

```text
causal peer/features snapshot ending before close t
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
- [`TEST_RESULTS.txt`](TEST_RESULTS.txt) — canonical source tests
- [`SOURCE_MANIFEST.md`](SOURCE_MANIFEST.md) — hashes for retained files

The original parity-gated replay harness remains preserved at immutable lineage commit `7c591211b463428a835c98af0ba597839d1b8aab`; this canonical branch contains the renamed outputs and the single source-of-truth Fastgate implementation.

## Verification

```bash
python -m unittest -v test_sentinel_fastgate_reference.py
```

## Promotion boundary

The source specifies the exact decision policy from a causal snapshot. The retained historical run uses the previously calculated causal confirmation schedule mapped onto the authoritative tape. A fresh per-security point-in-time reconstruction must reproduce those decisions before production promotion.

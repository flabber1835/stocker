# Sentinel Fastgate

**Strategy ID:** `sentinel-fastgate`  
**Version:** `1`  
**Status:** research candidate; not production activated or certified  
**Canonical branch:** `research/sentinel-fastgate-2026-08-24`  
**Pinned base:** `main@722aa14ae0e452437b80425528ba30fcf133b029`

**Sentinel Fastgate** is the canonical name for the strategy previously described as the narrow alpha-recovery candidate, `D_narrow_combined`, or “FAST confirmation + externally owned provisional warning.” Those names are retained only as historical lineage.

## Canonical source of truth

[`sentinel_fastgate_reference.py`](sentinel_fastgate_reference.py) is the single canonical Python reference for every behavior introduced by Sentinel Fastgate.

- SHA-256: `c60beab918b49ce0610445bb07d273d28d5e4b2fc3ddd702efe54ea251f12f54`
- Git blob: `486de36a6764b9bab3a3b1b424c9930c3f0b61c1`
- Strategy digest: `c1434409d8f91d8aa94405eccc20bf2f764479a9208a6030e60564999a281492`

The reference file implements:

1. validation that all market and held-security histories end before the decision session;
2. the prior 252-session, 120-observation SPY-beta residual calculation;
3. residual-correlation breadth voting at `0.145`, `0.150`, and `0.155`;
4. historical co-distress/Jaccard peer selection using the three closest prior peers;
5. exact symbolic FAST branch classification using authoritative minimum/maximum damaged breadth;
6. causal confirmation or second-session persistence before native FAST severe entry;
7. the externally owned first-warning 55% ceiling after unchanged LD-RC;
8. immediate provisional clearing, durable state serialization, deterministic identity, and dependency-blob verification.

The exact symbolic minimum/maximum damaged-breadth geometry remains an authoritative input. Fastgate requires it and fails closed; it does not replace that retained mechanism with an approximation.

## Deliberately unchanged dependencies

Fastgate does **not** copy or modify ordinary/slow stress, confirmed severe holding or recovery, the Sentinel 1.1 recovery ramp, the recent-leadership witness, the divergence latch, Simplified Concordance LD-RC, or portfolio accounting. Their exact Git blobs are pinned in the reference and in [`STRATEGY_IDENTITY.json`](STRATEGY_IDENTITY.json).

```text
held-security and SPY histories ending before t
        -> Fastgate residual/Jaccard confirmation
        -> unchanged authoritative native Sentinel
        -> unchanged authoritative Simplified Concordance LD-RC
        -> optional external 55% first-warning ceiling
        -> authoritative next-open execution/accounting
```

A first unconfirmed warning is invisible to native Sentinel and LD-RC. Therefore its disappearance cannot open or prolong an LD-RC recovery episode. A causally confirmed warning, or a second consecutive warning, is passed to the existing native FAST severe path.

## Verification

```bash
cd research/sentinel-fastgate
python -m unittest -v test_sentinel_fastgate_reference.py
```

The retained run completed **20 tests successfully**. It covers raw-history peer reconstruction, causal cutoff enforcement, exact-bound requirements, dynamic confirmation, first-warning ownership, persistence confirmation, immediate clear, unavailable-evidence withholding, LD-RC composition, state identity, and dependency failure behavior. See [`TEST_RESULTS.txt`](TEST_RESULTS.txt).

## Retained historical evidence

- [`RESULTS.md`](RESULTS.md) — 5/10/15/20-year results and verdict
- [`metrics_5_10_15_20.csv`](metrics_5_10_15_20.csv) — headline metrics
- [`factorial_attribution.csv`](factorial_attribution.csv) — confirmation/provisional 2×2 attribution
- [`episode_attribution.csv`](episode_attribution.csv) — changed-exposure episode attribution
- [`sentinel_fastgate_transitions.csv`](sentinel_fastgate_transitions.csv) — transition audit
- [`control_parity.json`](control_parity.json) — exact unchanged-control gate
- [`retained_confirmation_mapping.csv`](retained_confirmation_mapping.csv) — retained causal schedule mapping
- [`provenance.json`](provenance.json) — data lineage, scope, and limitations
- [`STRATEGY_IDENTITY.json`](STRATEGY_IDENTITY.json) — deterministic strategy identity
- [`SOURCE_MANIFEST.md`](SOURCE_MANIFEST.md) — source and evidence hashes

## Performance result retained under this name

Over the retained 20-year window ending July 31, 2026, Sentinel Fastgate produced:

- CAGR: `23.1327%`
- daily Sharpe: `1.2357`
- maximum drawdown: `-21.6958%`
- ending multiple: `64.1958x`

The unchanged authoritative strategy produced `22.6302%` CAGR, `1.2138` Sharpe, the same `-21.6958%` maximum drawdown, and `59.1543x` ending wealth.

## Promotion boundary

The canonical source now specifies the dynamic signal from raw aligned histories through the final Fastgate decision. The retained performance run, however, used the previously calculated causal confirmation schedule mapped onto the authoritative accounting tape. Before production promotion, a fresh point-in-time replay must feed the exact authoritative held-security histories through this source and reproduce the confirmation dates, daily decisions, and economics.

No file in this directory authorizes production activation.

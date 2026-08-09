# Sentinel 1.1 Faithful Reproduction Kit — what is stored here

Source archive: `docs/Sentinel_1_1_Faithful_Reproduction_Kit_NO_SHARADAR.zip`
(sha256 `096da33f74f3c049743dfd24cfdac2150baca2a7ce4f12d15514ca5eb1a5c3d4`,
21,846,183 bytes, received 2026-08-09). The zip is committed **verbatim** and is
the authoritative copy. Its own `00_README/SHA256SUMS.txt` verifies clean over
all seven bundled payloads (checked on ingest).

This directory holds only the **readable** subset, so the reproduction contract
and the recovered breadth semantics are greppable without unzipping 21 MB:

```text
00_README/                        extracted verbatim
04_EXACT_BREADTH_RECOVERY/        extracted verbatim
```

Two directories inside the kit are deliberately **not** re-extracted here:

```text
01_SENTINEL_FROZEN_HARNESS/Sentinel_1_1_Frozen_Harness_Handoff.zip
    byte-identical (sha256 c344dd14ee920985d65becf48c6317c484b20720cb223c22412fa7bf22f43993)
    to docs/Sentinel_1_1_Frozen_Harness_Handoff.zip, already in this repo and
    already extracted to docs/sentinel-handoff/. Re-storing it would duplicate
    9 MB and create a second copy that could drift from the first.

02_CERTIFIED_WEALTH_CORE/
    stocker_certified_wealth_core_v1.zip            (1.3 MB)
    stocker_certified_sharadar_symbolic_wealth_v1.zip (11.6 MB)
    Binary reproduction payloads with nothing to read at the tree level. They
    live inside the committed kit zip; unzip it to obtain them.
```

The raw Sharadar corpus is **not** in the kit by design. Expected SHA-256 values
for the omitted inputs are in `00_README/EXTERNAL_SHARADAR_SHA256SUMS.txt`;
verify your own copies against that file before treating any replay as
reference-equivalent.

## The reference result the kit is measured against

Window 2006-07-31 → 2026-07-31, Sentinel 1.1-RC (zero recovery gate):

```text
CAGR              22.25174847%
max drawdown     -21.94904567%
ending multiple    55.608018x
parent 1.0x       22.11974992% CAGR, -23.92559171% max DD, 54.419402x
```

These are the kit's own numbers, reproduced here for locating them. They have
**not** been re-derived in this repository, and nothing in Stocker computes them.

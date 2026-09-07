# Synthetic Market Lab v1 — Phase-1 Validation Report

## Reference identity

- Generator version: `1.0.0`
- Seed: `20260907`
- World ID: `6fb16f6764911274135926de7c4a78d36f83aa206a2d2bee19c468d1ab31b1a1`
- Configuration SHA-256: `c752a2ad067629c7582361625bb235883e0eebef34f0a02d9bb1c49c1c490563`
- Sessions: 5,040
- Companies: 200
- Dates: 2000-01-03 through 2019-04-26 on the deterministic weekday calendar

The canonical manifest and exact output hashes are in `reference_world/manifest.json`.

## Reference-world observations

The final world contains 708,555 security-day price rows and the same number of PIT universe rows. All 200 companies list; 86 later delist. Forty-eight experience bankruptcy and 38 are acquired. Terminal names remain in historical prices, universe snapshots, security-master history, actions, and ground truth.

Public reporting contains 11,671 filings: 8,808 quarterly and 2,863 annual, including 610 later restatements. Company-specific fiscal offsets create 4,447 distinct period-end dates. Ground truth contains 16,000 company-quarter observations.

All ten base macro regimes occur. Eighty-eight named shock arrivals occur across credit, energy, supply, geopolitical, liquidity, productivity, and bubble processes. Decaying shocks overlap; the reference world reaches seven simultaneously active shock types. Every modeled factor premium takes both positive and negative values during the world.

Mean daily economic log return is about 0.000006 and daily standard deviation about 4.53%. The 1st/99th percentiles are about -12.27%/+12.28%; the 0.1st/99.9th percentiles are about -23.62%/+23.28%. Raw closes range from $0.03 to about $35,185, with splits/reverse splits active. Spreads range from about 23.45 to 807.90 bps.

## Validator result

The full reference validator passes 23/23 checks: manifest hashes, zero positive causal lags, adapter ground-truth denial, causal action timing, PIT price/security identity, OHLC/liquidity invariants, IPO chronology, delisting chronology, retention of dead/bankrupt companies, no survivorship filtering, PIT universe membership, filing dates, forward-only revisions, heterogeneous quarterly/annual calendars, true/public accounting closure, split value reconciliation, dividend reconciliation, identity-change successors, and absence of latent fields in public schemas.

The isolated pytest suite passes 26 tests. Tests additionally prove macro prefix invariance under a longer future horizon, PIT retrieval around initial filings/restatements, current-state-only price-step inputs, byte-identical equal-seed replay, materially different different-seed histories, overlapping shocks, factor sign reversals, and adapter rejection of the ground-truth directory.

## Full reference replay proof

The complete 200-company, 20-year world was generated twice from the final configuration and seed. Both runs produced the same world ID, identical per-file records, and byte-identical `manifest.json`. Manifest SHA-256: `b56a65992bb1668a74651f37e65f54f5b2f37140910cff48b55f1f313842e34d`.

## PIT/no-forward-bias proof

Generation is a forward-only session loop with independent named RNG streams. The price step accepts current state vectors and lagged price/company state; it has no future-path argument. The machine-readable dependency graph rejects positive future lags. Public disclosures are immutable versioned events with filing dates, and the PIT reader returns only versions filed by the query date. Universe rows exist only while a public security identity is active. The adapter accepts only `public/` and rejects `ground_truth/`.

## Known limitations

Phase 1 uses a deterministic weekday calendar, not an exchange-holiday calendar. Daily bars include overnight/intraday structure but no order book, market impact, participation limits, halts, or execution slippage. Acquisitions terminate companies; detailed merger consideration and successor-company accounting are deferred. Spin-off lineage is reserved but not fully implemented. Macro variables remain hidden ground truth; public macro-release/vintage simulation is deferred.

The canonical reference was generated in the available environment with Python 3.13.5, NumPy 2.3.5, and Pydantic 2.13.4. The code follows the repository's Python 3.12 standard; byte certification on another interpreter requires replay because the manifest records interpreter identity.

## Phase gate

No strategy was run during generation, calibration, validation, replay, or adapter verification.

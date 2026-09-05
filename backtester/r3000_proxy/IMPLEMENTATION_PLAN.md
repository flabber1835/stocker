# IWB/IWM PIT Russell 3000 proxy — implementation plan

Corpus ID: `r3000-proxy-pit-2006-2026-v1`.

This is an IWB/IWM-derived Russell 3000 proxy and is not a licensed FTSE Russell constituent history.

## Existing authority reused

- Run 33820201471: 38 direct BlackRock/iShares product-data fund snapshots for 2007–2016 and 2018–2026, plus combined iShares Trust N-Q filings for 2006 and 2017.
- `backtester/expand_historical_authority_v4.py` and the V4 issuer-safe metadata lineage for strict-prior SEC authority and historical identity evidence.
- `backtester/historical_metadata_2007_closure.py` for exact source-ledger, evidence-hash, duplicate-assignment, and zero-unresolved closure patterns.
- `PIT input data/ACTIONS_PIT_ONLY.csv.gz` and `backtester/causal_terminal_terms.py` for causal corporate-action and terminal-event authority.
- Frozen canonical PIT price package referenced by `backtester/data/canonical-pit-20y.json` for historical episode/price existence validation.

## Stages

A. Source recovery: authenticate the seed run, preserve raw evidence byte-for-byte, parse 38 BlackRock snapshots, and parse 2006/2017 IWB/IWM common-stock schedules from N-Q. Emit source manifests and SHA256SUMS.

B. Identity closure: map each source holding to a historical security episode using contemporaneous CUSIP first, then V4 strict-prior SEC/security-class and historical ticker/action lineage. Emit a complete closure ledger. No fuzzy promotion.

C. Membership: build fund snapshots and causal intervals. Carry observations forward until superseded and truncate on proven terminal events.

D. Union: deterministic `normalized_security_id` union of IWB and IWM with overlap flags and geometry diagnostics, including a 2007 comparison to the separate 2,976-row historical Russell witness.

E. Certification: prove source provenance, declared effective/knowledge-date semantics, zero unresolved accepted equities, membership causality, terminal integrity, future-perturbation invariance, deterministic hashes, and consumer lookup integrity.

F. Reproducibility: fresh GitHub build from immutable upstream hashes must reproduce the corpus root digest byte-for-byte.

## PIT modes

`HISTORICAL_STATE_PROXY` reconstructs the ETF portfolios at each holdings effective date from authenticated archival evidence. This is the default Wealth Core research corpus mode.

`INFORMATION_AVAILABLE_PROXY` requires authenticated publication availability no later than the model decision. SEC N-Q evidence becomes available on filing date. Historical BlackRock product-data snapshots currently lack independently authenticated original publication timestamps, so this mode remains separately gated until that authority is established.

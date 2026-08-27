# Sentinel identity refresh before SEP CDC

## Status

Accepted for the YHNAU identity-refresh deadlock fix.

## Problem

Routine `daily()` currently reconciles the Sharadar SEP `lastupdated` stream before the ordinary daily generation refreshes TICKERS. A mutation whose session lies beyond a stale local listing interval is therefore rejected even when current Sharadar TICKERS safely extends the same `(permaticker,ticker)` identity. The rejection prevents the daily TICKERS refresh that would remove the interval gap, creating a deterministic liveness cycle.

The existing historical-identity guard also clips listing intervals to the global published SEP horizon. That treats an ordinary `lastpricedate` extension for a security whose own latest bar is older than the global frontier as a historical rewrite.

## Decision

1. Routine daily preparation publishes its fully source-stable daily generation before routine SEP key-set and CDC reconciliation.
2. The daily generation continues to use the exact unpublished TICKERS candidate resolver only for SEP rows in that same generation. It must satisfy the existing source-stability, structural TICKERS, domain, publication and historical-identity checks before becoming authority.
3. After daily publication, SEP key-set reconciliation and CDC run against the refreshed published resolver. The CDC cursor remains advanceable only after the correction generation it names is published.
4. A failed pre-existing `sep_mutations` generation is still retried before a new daily run, because its live historical rows must be superseded by the operation that owns their complete replay contract. An identity interval-gap refusal occurs before opening that mutation run, so this recovery exception does not recreate the observed cycle.
5. Historical identity safety is evaluated per identity rather than by requiring every listing bound to be unchanged inside the global market horizon. For an existing `(permaticker,ticker)` pair, `firstpricedate` cannot change and `lastpricedate` cannot move backward; a forward-only `lastpricedate` extension is allowed. Previously published pairs cannot disappear. A genuinely new pair is allowed only when its first session is after the published SEP frontier. Existing structural TICKERS overlap/ambiguity checks remain fail-closed.
6. The read-only GO preflight may classify an `IDENTITY_INTERVAL_GAP` as `LOCAL_IDENTITY_REFRESH_REQUIRED` only after a second, GET-only current TICKERS observation is stable, structurally valid, complete under the production TICKERS source membrane, historically safe, and resolves every otherwise-valid pending mutation row. Unknown, reused, ambiguous, structurally invalid, unstable, or historically rewriting candidates remain refusals.

## Invariants

- No ticker-string fallback is introduced.
- No historical bar may be re-keyed by metadata-only publication.
- No SEP mutation cursor may advance under unpublished identity.
- A failed daily publication leaves the prior resolver authoritative and CDC untouched.
- A failed CDC publication leaves its watermark unchanged and retryable.
- TICKERS negative-space, source-stability, same-day immutability, WAL/publication, exact-runtime and broker-separation boundaries remain unchanged.

## Why not validate CDC under unpublished identity?

The daily path already has a transactionally coherent same-run TICKERS candidate resolver for its own SEP rows. Extending that unpublished authority into historical CDC would create a new cross-generation dependency and additional recovery states. Publishing the already-validated daily identity first breaks the cycle while keeping CDC dependent only on published identity, which is the simpler financial boundary.

# Sentinel identity refresh before SEP CDC

## Status

Accepted for the YHNAU identity-refresh deadlock fix.

## Problem

Routine `daily()` currently reconciles the Sharadar SEP `lastupdated` stream before the ordinary daily generation refreshes TICKERS. A mutation whose session lies beyond a stale local listing interval is therefore rejected even when current Sharadar TICKERS safely extends the same `(permaticker,ticker)` identity. The rejection prevents the daily TICKERS refresh that would remove the interval gap, creating a deterministic liveness cycle.

The existing historical-identity guard also clips listing intervals to the global published SEP horizon. That treats an ordinary `lastpricedate` extension for a security whose own latest bar is older than the global frontier as a historical rewrite.

## Decision

1. Before a production daily run opens, observe the current complete TICKERS source twice through the production source membrane and require structural validity, metadata completeness, complete-key proof, source stability, and routine historical-identity safety.
2. Construct a resolver from the published projection plus that exact current TICKERS candidate. Validate the already-known pending SEP `lastupdated` rows through yesterday against it using the canonical CDC envelope, duplicate-key checks, double source observation, permanent identity, and positive raw-close checks. This step is read-only against the corpus and cannot move a cursor.
3. Pin that exact proven TICKERS candidate as the first TICKERS observation inside the ordinary daily generation. The existing protected-SEP coherence bracket then re-observes live TICKERS after SEP; if source identity changed during preparation, daily refuses before publication.
4. The daily generation still writes TICKERS and SEP in one `IngestRun` and resolves its own SEP rows with `load_resolver(include_run_id=...)`. It must satisfy the existing source, domain, publication and historical-identity checks before becoming authority.
5. Only after successful daily publication do routine SEP key-set reconciliation and actual SEP CDC run. They consume the refreshed published resolver. A correction publication precedes its CDC watermark advancement exactly as before.
6. A failed pre-existing `sep_mutations` generation is still retried before a new daily run, because its live historical rows must be superseded by the operation that owns their complete replay contract. An identity interval-gap refusal occurs before opening that mutation run, so this recovery exception does not recreate the observed cycle.
7. Historical identity safety is evaluated per identity rather than by requiring every listing bound to be unchanged inside the global market horizon. For an existing `(permaticker,ticker)` pair, `firstpricedate` cannot change and `lastpricedate` cannot move backward; a forward-only `lastpricedate` extension is allowed. Previously published pairs cannot disappear. A genuinely new pair is allowed only when its first session is after the published SEP frontier. Existing structural TICKERS overlap/ambiguity checks remain fail-closed.
8. The read-only GO preflight may classify a locally missing single identity or `IDENTITY_INTERVAL_GAP` as `LOCAL_IDENTITY_REFRESH_REQUIRED` only after current TICKERS passes the same source/history checks and resolves every otherwise-valid pending mutation row. Reused, ambiguous, structurally invalid, unstable, or historically rewriting candidates remain refusals.

## Invariants

- No ticker-string fallback is introduced.
- No historical bar may be re-keyed by metadata-only publication.
- Prepublication CDC work is validation only; it cannot create a correction run or advance the watermark.
- No SEP mutation cursor may advance under unpublished identity.
- A failed daily publication leaves the prior resolver authoritative and routine CDC untouched.
- A failed CDC publication leaves its watermark unchanged and retryable.
- If the process dies after daily publication but before maintenance completes, readiness remains FAIL because the SEP watermark and recent complete proof do not cover the new published decision frontier.
- TICKERS negative-space, source-stability, same-day immutability, WAL/publication, exact-runtime and broker-separation boundaries remain unchanged.

## Why this shape

Publishing identity before any examination of pending mutations would break the liveness cycle but create an avoidable failure window: a deterministic historical ambiguity could be discovered only after daily publication. Using the exact proven current TICKERS candidate for a read-only prepublication CDC proof removes that window without granting unpublished identity mutation authority. Actual historical correction and cursor movement still happen only after the identity generation has published.

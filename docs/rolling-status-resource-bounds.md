# Rolling status input memory

Step 1 review on main `e3dfb033d25ed68e5e1f6d2386285afabc62e801`
traces `verified_shadow_status` through `rolling_runtime._current` to
`rolling_go_inputs.validate` and `cold_start_inputs`. Although `_current` discards
the material, it constructs every security's 252-session warmup plus frontier.
The panel has a 512 MiB limit. A named SQL cursor bounds transfer batches but
does not bound this retained Python material. Full-universe qualification is
still open; a synthetic scale measurement must not be called deployed proof.

## Decision before implementation

For callers requiring only current-input readiness, add an explicit compact
assessment reader. Retain per-session counts and per-domain positive counts,
the required benchmark window and current reference metadata; discard each
equity bar after accounting for it. No price history, strategy state, book or
cached authority is created. The canonical strategy input path continues to
materialize its required warmup without changing its economic behavior.

Both readers reuse the same snapshot setup, dated bar-to-reference mapping,
benchmark-axis validation and terminal/distribution checks. The compact path
still performs the existing full sealed-content hash verification on every
call, under the caller's repeatable-read publication pin. It preserves every
readiness clause and threshold: source-final frontier, defensive domains,
population versus the last 20 warmup sessions, frontier/warmup domain coverage,
and issuer evidence. The selected strategy request and publication chain checks
remain in the common admission path. A late corrupt row must refuse the whole
operation; a streamed prefix is never a readiness result.

Use compact assessment in `rolling_runtime._current`, which only needs the
binding and report. Keep the existing material-returning `validate` contract
for callers that consume actual strategy inputs. No SQL schema, persistent
verdict, capability flag or existing signed identity is rewritten. Changed
source identity must be accepted through the existing source/version boundary.

Acceptance must compare readiness values with independent SQL counts, prove
that the production status caller cannot allocate the full warmup, and refuse
late payload corruption, stale frontier and conflicting reference identities.
Remove the streaming route and full-content guard separately to verify that
their falsifiers fail. Existing materialized-input and rolling runtime
regressions must remain green without changing golden economic results.

Memory for price observations becomes proportional to session counts and the
cursor batch rather than sessions times securities. Reference/action evidence
still scales with its retained corpus, and verification remains a full-window
scan: this does not close latency, concurrent panel requests, reference history,
complete status/checkpoint memory, or NAS qualification gates by itself.

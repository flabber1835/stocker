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

## Follow-through on report-only callers

Further production tracing at `b36fb1a63b56868bb1aa301b13df6d6ced6226a7`
found the same discarded material in operational assessment/readiness, execution
readiness, acquisition verification and the initial admission check in runtime
advance (including idempotent retries). Route these consumers through compact
assessment as well. `assessment` must still return failed readiness clauses;
the other admission consumers must still refuse them. Preserve their existing
transaction, publication pin, clock and strategy request checks.

Keep materialization in actual strategy initialization/continuation, strategy
warmup certification and database-health certification that derives a warmup
identity. Those callers consume the material rather than discard it; their
complete resource qualification remains separate. Test the production report-only
entrypoints with materialization forbidden, including first publication and an
already-committed runtime retry. Removing each route must fail its acceptance
test. No shared cached verdict or weakened integrity scan is introduced.

The first-publication acceptance also exposed an inner discarded warmup in
`operational_snapshot.validate`, before coordinator verification. Use the same
compact reader there for full content/reference/action closure. The resulting
DATA_ONLY proof, owner checks and backup requirement remain unchanged; the
reader does not promote the candidate or grant strategy authority. Mutate this
inner route separately from the outer coordinator check.

Historical recovery also discards the material at its pre-transition and
post-commit receipt gates. Permit compact validation explicitly for these two
callers while preserving the material-returning default API. Both must still
verify authenticated dated availability and use the selected historical frontier;
neither may substitute the current clock frontier or grant prospective authority.
The actual transition continues to obtain canonical inputs from continuity.
Exercise new recovery and trailing-candidate restart, with each route separately
restored to materialization by a falsifier.

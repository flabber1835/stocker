# Partial native-fill notional integrity

Verified main/reviewed failing source:
`8212a55335500b4bbb81853572019d9eb4443724` (owner-merged #408, including #407).
Branch `codex/economic-fill-review`; delivery through a PR targeting `main`.
No NAS or real broker accounts. Existing golden and audit packages are unchanged.

## Finding and economic oracle

P2 consumer integrity, `sentinel/execution/fill_integrity.py:49`:
partial history checked total shares but deferred notional comparison until
all cumulative shares were represented. The actual reconciler accepted two
shares at $600 ($1,200) for an order reporting ten filled shares averaging $100
($1,000). It returned RUNNING and retained the contradictory fill/normal alert.
Two shares at $500 also passed, leaving zero dollars for eight positive-price
fills. Reproduction: **2 failed, 1 valid positive passed in 6.02 s**.

The independent oracle solves for the missing shares' implied average price:
`(order gross - observed native gross) / missing filled shares`. It must be
strictly positive under the existing positive-quantity/positive-price contract.
The fix uses exact rational products and applies to both the incoming set and
the retained union before observation, fills, alerts or recovery watermark can
be published. Existing exact full-history equality remains required.

Restart acceptance starts with 3 shares at $200 ($600). A later response of 2
shares at $200 or $300 is plausible by itself, but together exhausts/exceeds the
entire $1,000. Repeated new SQL connections refuse it without changing accepted
rows or observation count. Subsequent coherent history of 3@$200, 2@$100, 5@$40
converges to exactly 10 shares/$1,000 and three distinct notifications. Rejected
payloads remain diagnostic evidence; previously accepted IDs are never rewritten.

The tests reuse the existing explicitly local candidate-parser fixture and
mark the supplied history incomplete. They do not promote production capability
flags, use empty responses as finality or establish a provider guarantee.
No historical strategy-return discrepancy is attributed to this finding.

## Commands and retained results

Run from repository root with host Python
`C:/Users/mbron/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
The runner prints the complete Docker/pytest command in each retained log.

```text
python audit/economic_399/partial_fill_notional/run_local.py regression
python audit/economic_399/partial_fill_notional/run_local.py mutations
python tools/validate_test_responsibility.py --base 8212a55335500b4bbb81853572019d9eb4443724 --output ownership.json
git diff --check HEAD^ HEAD
git diff --check origin/main HEAD
```

- Before fix: `python -m pytest tests/sentinel/test_native_fill_acceptance.py::test_partial_native_notional_leaves_positive_economics_for_missing_shares -q --tb=short -p no:cacheprovider`: **2 failed, 1 passed**.
- Focused native acceptance/progression modules: **35 passed in 19.38 s**.
- Broader parser, reconciliation, contract and fill-interval regression:
  **250 passed in 60.13 s**, without skips or xfails.
- **4 falsifiers killed**: removed partial-notional guard, relaxed positive
  residual, rounded Decimal multiplication, and bypassed durable-union caller.
  All selected cases pass unmodified. Mutation failures occur at behavioral
  assertions, not test collection or infrastructure errors.
- Five Python files parse; pyflakes has zero findings. **479 owned test modules,
  zero unowned**. No unexpected skips or xfails are accepted.

Offline image `sentinel-test:ci`, digest
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`:
Python 3.12.13, PostgreSQL 17.11. Current source is copied from a read-only mount
to disposable storage with network disabled and `.env` excluded. The original
failing run, final output and falsifier traces are in `results.zip`.
`source-provenance.json` records Git-LF source hashes; `SHA256SUMS.json` binds
this package. Fresh exact-image/PG16 CI remains required.

## Provider review and unresolved gates

Reviewed 2026-09-19: Alpaca's [Activity SSE guide](https://docs.alpaca.markets/us/docs/activity-sse)
distinguishes publication `event_id`, stable economic `ref_id`, execution time
and `previous_id` correction links. Its migration table states availability of
activities booked after February 11, 2026; older account coverage must not be
assumed. The [Trading SSE reference](https://docs.alpaca.markets/us/reference/subscribetoactivitiessse)
requires a lower cursor with `until_id` and documents dropped-event/internal-error
comments. The existing parser rejects those errors. These pages do not supply
an accepted fixed-close finality or cumulative-average rounding contract for
this installation. Establish the earliest accessible event and bootstrap cutover
for the exact Trading account independently of the guide's legacy migration table.

F19 remains open for native authority and reversal/replacement accounting.
C1/F6 remains open for an exhaustive account cash producer, classification,
corrections and fixed-close finality. C3 remains open for predecessor interval
completeness and durable command preimages; takeover fencing remains intact.
The user’s 20-year PIT corpus has not been made locally available, so full replay
and economic-delta analysis remain data-dependent per the existing ledger.
Recurring backup maintenance and other resource gates also remain open.

## NAS handoff — not executed

Prerequisites: owner-reviewed merge, green exact-head CI, accepted image hashes
and PostgreSQL 16, and an isolated disposable clone without broker credentials
or network. Preserve all prior attempts and golden inputs.

1. Run the two campaigns above using the accepted test image; retain source and
   image hashes, server version, complete commands and raw results. Pass requires
   every selected test and all four falsifiers, without unexpected skips/xfails.
2. In that isolated clone, use the existing test
   `test_partial_native_union_refuses_impossible_notional_and_recovers_after_restart`
   under the accepted PostgreSQL version. Retain before/after fill rows, command
   and observation identities, refusal diagnostics and outbox rows. Invalid
   partial unions must publish no new accepted economics; coherent later history
   must retain ten shares/$1,000, original IDs and exactly three ordinary alerts.
3. Qualify physical restore separately using the existing production restore
   harness and accepted media. Connection restart here is not crash-durability
   or NAS filesystem evidence. Missing predecessor activity remains fenced.
4. Before any separately authorized account qualification, obtain the accepted
   account/interval completeness, correction/bust, timestamp and rounding
   contracts. Record exact provider inputs and independent expected cash/fill
   economics. Capability flags must stay disabled while those gates are absent.

This closes one locally testable consumer gap. Step 1 and economic certification
are not complete.

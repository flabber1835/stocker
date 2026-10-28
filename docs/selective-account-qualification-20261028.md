# Selective-account qualification: bounded prototype

The owner said "Do it" after the proposed accounting-and-identity qualification.
This authorizes a small isolated prototype, representative qualification cases,
read-only historical identity binding, measured runtime and a go/no-go report.
It does not authorize a full P2 backtest, parameter search, production change,
broker/database call or local financial replay/container. Use the existing
research branch and PR542. Verified main is bbcb728a972f483c9f76f2b0db2599b2134ab1bb;
the research branch incorporated it with a preserving merge before implementation.
That checkout update is not a PAPER installation.

## Accounting decision, before implementation

Persistent quantities and the retained scalar sleeve are different models.
For a 55% stock / 45% flat defensive allocation, starting at100, a stock move
1 to1.2 then to0.96 yields scalar NAV111 then98.79. Holding55shares and45cash
instead yields111 then97.8. There are no trades or costs during those two days.
The exact inequality cannot be removed by a neutral mask or an identity exclusion.
The hosted proof must call the actual frozen canonical scalar account and retain
its output, alongside an independent exact holding calculation.

Therefore record MODEL_CHANGED relative to the old scalar benchmark. Define a
matched neutral holding account H0 and the identical account with scripted local
allocation events HQ for qualification only. Neither is claimed to reproduce
the17.63% historical reference. No full-horizon H0, HQ or P2 returns are computed.
P2's classifier/latch is not run: scripted trim/restoration cases test the account
operation, not whether the strategy generates profitable signals.

This is the explicit matched-control definition requested by the owner; it is
not a hidden replacement of the prior benchmark. A later performance trial must
freeze the neutral account model, reconcile its model gap and define its own
matched baseline before evaluating the actual selective strategy.

## Minimal account and boundaries

Implement a private research funded-account ledger, not a second Wealth Core.
It has no stock selection, ranking, stop, cooldown or broker code. Core remains
the sole ownership/signal authority. Frozen Pydantic schemas carry Decimal cash,
positions, quantities, claims, intents, source identities and an event chain.
State changes are atomic; a refusal leaves the predecessor unchanged.

Continuing quantities are carried between events; marks do not rebalance.
Trades use explicitly typed raw-open prices at the committed execution session,
strictly after the signal session. Whole-share BUYs clip to cash including10bp
cost. A SELL cannot exceed actual holdings. Local trims/restorations are ordinary
funded-account trades; routing to/from a defensive instrument is a separate
trade with its own single fee, not an invented interest credit. No redistribution
into other stocks. Partial fills and quantity drift do not change the Core trace.

Splits transform quantities without P&L or fees and must agree with the actual
frozen canonical split helper. Unsupported exact fractions refuse rather than
round. Cash dividends accrue on actual funded ex-date quantity, persist through
a sale, and settle once on/after the stated payment session. Cash mergers pay
actual funded quantity once without a fictitious market-trade fee. Actual frozen
Core cash/quantity helpers and terminal/ledger cases serve as hosted oracles;
they are never replaced or patched. The prototype does not qualify every action
type, protected broker orders, spreads/slippage or current PAPER execution.
The prototype keeps exact Decimal monetary results. Frozen legacy helper floats
are compared with an explicitly retained1e-10dollar bound on these small synthetic
cases; this is not an economic-field exclusion or a portfolio-wide tolerance.

An unchanged/disabled scripted layer must produce identical account states,
events and chains in H0 and HQ on the same basis. A new local event changes only
the named episode; restoration is cash-clipped and cannot resurrect an exited
Core episode. Duplicate event IDs, stale or same-close fills, missing prices,
wrong security/episode IDs, early dividend payments and oversells refuse.
Restart restores the exact account/state hash and event chain, then its suffix
must equal uninterrupted execution. No reset of unsent events or recovered tails.

## Identity binding, not ticker matching

The actual frozen breadth builder iterates sorted canonical episode slots.
Bind its saved holding observations to the sorted HOLD_UNCHANGED/CLOSE_POSITION
operations at the same close, checking ticker and age only as corroboration.
Derive age independently from the exact filled-entry row index on the contiguous
source session axis. Review-day HOLD records can omit an explicit age field;
that omission is not a missing canonical age and must not cause a ticker fallback.
Permanent SID and slot come from operations, original signal and actual opening
quantity from committed retry FILLED records. Preserve origin through continuing
episodes and supported conversion/split events in the original ledger.

Reconstruct quantities read-only from the committed original ledger; do not run
Core decisions. Check aggregate security quantity at every close and actual
per-slot quantities/lineage at retained checkpoints available in the original
account. Duplicate security episodes must remain separate; do not collapse them
with a dict keyed only by SID. In particular, the actual2020TDOC conversion has
multiple concurrent episodes. If a per-lot allocation is not uniquely supported
by retained events, refuse or explicitly mark the missing coverage; never join
on ticker, infer a signal date from price or assign a split to the wrong lot.

No price series or full funded-history account is replayed during this identity
audit. Preserve a row/source-bound identity chain and all coverage/ambiguity
counts. Existing baseline file/prefix/source review is admitted by exact hashes;
do not repeat completed repairs/launchers.

## Hosted qualification and budget

One20minute GitHub-hosted workflow, one offline pinned-image worker, at most
180seconds processing. Source/inputs read-only, disjoint private output,
1CPU/2GiB/noSwap/non-root/no-network fences. Reuse the existing authenticated
encrypted input/runtime release. The separate key remains only in outer
orchestration; no plaintext financial evidence or key in public logs/artifacts.
New evidence is AES-GCM encrypted in the same research Actions channel for7days.
Only status/identity/hash metadata is public. No financial trial or optimizer is
dispatched. Unknown stop exports diagnostics only, never a financial snapshot.

Run actual frozen helper/oracle and prototype cases for unchanged holdings,
partial trim, restoration with cash clipping, dividends through a sale, split,
cash merger and serialized restart. Include malformed and forbidden operations,
guard-removal falsifiers, disabled-layer equality and account-model mismatch.
The qualification must retain concrete case evidence, not just a test count.
Measure identity parsing/binding and synthetic-account processing separately;
microbenchmarks are not proof of full-history replay throughput.

Local work is limited to static/pure validation, schemas and read-only inspection.
Actual canonical/account qualification runs only on the hosted worker. No local
strategy/account replay or container, shared service or production source change.
If input/runtime/stop/model gates refuse, preserve evidence and report that scope;
no automatic rerun or financial extension is granted by this prototype request.

## Review and disposition

Authenticate exact run/head/request/receipt/cipher length+SHA/GCM/inventory and
actual stopped/fenced worker before interpreting output. Independently inspect
the counterexample, case identities, cash/quantity/claim equations, restart chain,
identity coverage and runtime. Preserve negative results and unsupported actions.
Report separate verdicts for (1) old scalar equivalence, (2) matched-account
prototype, (3) historical identity coverage and (4) readiness for a later full
comparison. Passing component cases alone never certifies P2 or selects a
production replacement. PAPER, broker/database, protected results, PR541 and
shared Docker/WSL/services/pagefile remain untouched.

## Qualification-harness refusal and correction

Run40699456818/head53c23600 passed staging and139static tests; its exact
stopped1/noOOM artifact12820403511 is authenticated and preserved. It actually
proved the scalar/holding counterexample, then refused in the dividend harness:
the harness compared the bound receivable_total method with0 instead of calling
it. This predicate is always false; it is not evidence of an account defect.
The remaining cases and historical identity audit were not admitted as passed.

Correct only the method invocation, retain the actual oracle cash/claim values,
and persist each successful case prefix before later assertions. Add an AST
regression that fails with the original method/property mistake. Keep the
predeclared1e-10dollar legacy-float bound; exact Decimal account results remain.
The next source-bound request names the original refused run. Repeating these
small synthetic qualification fixtures under the repaired harness is necessary
to finish the owner's requested prototype; it is not a historical funded replay,
P2 trial, parameter change, GitHub rerun-attempt2 or financial extension.
No duplicate writer exists and the original artifact/failed status remains.

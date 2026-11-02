# Diagnostic unresolved spin-off entitlements

This research-only continuation resumes P06 and P07 from their own independently
admitted diagnostic checkpoints. It does not resume a financial replay or settle
an entitlement. The frozen financial inputs, canonical Core algorithm, original
checkpoints, committed prefixes, recovered tails and prior drivers remain intact.

The first affected source events are TFCF on 2019-03-21 for P06 and PPLI on
2021-05-25 for P07. Their current diagnostic predecessors remain, respectively,
270 transitions through 2019-02-28 and 463 through 2021-04-30. The actual strict
financial P07 predecessor is distinct; diagnostic state cannot enter that path.

## Complete-set preflight and deferral

`sentinel.core.spinoffs.apply_supported_entitlements` validates all supplied
events before posting any receipt, liquidation or reference-basis change. The
diagnostic adapter preserves that atomic boundary. If one held leg has the
source codec's unresolved policy and absent quantitative terms, the entire
supplied held set is deferred, including otherwise reviewed sibling legs and
other held-parent groups. Unheld events remain inert under the canonical rule.
There is no partial application. A complete supported set uses the original
function without approximation.

A source-hash-bound AST projection retains the canonical preflight, including
typed source, held identity, parent ticker, duplicate-child, known ratio, bars,
price, fractional cash-in-lieu and aggregate reference-scale guards. It records
a genuinely absent, source-typed child contract instead of refusing immediately,
and records the absent-identity validation obligation described below, so later
supplied legs are still validated. It stops before the first mutation. Invalid supplied quantitative
terms, a different policy, parent/child identity equality and malformed source
fields remain refusals. Missing terms do not become zero, a guessed ratio or a
synthetic price. A second canonical single-event probe validates each unresolved
leg's original refusal; the full canonical set is also probed on deep copies.

The original full-set call must reproduce the exact child-ownership refusal on
the actual hosted state before the first affected candidate transition. Probe
state and ledger must be unchanged; otherwise no deferral is permitted. This is
also checked for every later deferred set. Any other original exception remains
a refusal. The candidate proves the complete state, ledger, slots, shares,
cash, source lots and input event bytes equal their pre-call values. It returns
no financial audit rows and emits an explicit unresolved-entitlement event.

## Evidence and persistence

Each event binds frozen source-function identity, canonical input identity,
publication hash, immutable prior-state hash, all supplied source events, every
held known and unknown leg, parent/child identifiers and tickers, held episode
facts and held/pending/leadership roles. The unresolved claim has no child
quantity, cash proceeds or allocated basis. Existing parent ownership remains
visible; this does not state that no child entitlement exists or that retained
prices are economically complete.

The existing tainted event chain carries the unresolved claim across subsequent
checkpoints. An immutable per-use proof is written only after the surrounding
canonical diagnostic transition returns and confirms no spin-off receipt,
liquidation or child-lot/basis settlement was introduced. Ordinary canonical
trades may still change holdings later in that transition; the no-mutation
claim applies to the entitlement hook, not to unrelated legitimate operations.
An interrupted or refused transition retains its unsent event tail and cannot
be adopted as a committed predecessor. Unknown workers never expose mutable
snapshots. These proofs and events are encrypted within the existing seven-day
AES-GCM export with its separate key; no financial payload or key is public.

## Unknown child identity is an unresolved relationship

The frozen P07 input contains distinct `spinoff` and `spinoffdividend` source
rows for PPLI on 2021-05-25. The original codec supplies no child identity for
either row. Its original missing-contract refusal occurs before a later
`(session, parent, None)` duplicate-key check. `None` is not an established
economic child identity, so diagnostic continuation retains both raw source
legs with their individual hashes and explicitly records their relationship as
unresolved. It does not assert two entitlements, deduplicate them, combine their
values or select one value as consideration.

The projected preflight therefore records an indeterminate-identity relation
only when every implicated leg has the original absent contract, every child
identity is absent and every source-row hash is distinct. Repeated identical
source evidence still refuses. Duplicate known-child identities retain the
original refusal, including when their source-row hashes differ. All later
known-leg validation remains mandatory. This is an explicit deferred validation
obligation and never a uniqueness certificate or financial-admission proof.

## Source spin-off cash proxies remain unvalued

The exact PPLI 2021-05-25 observation also carries the native
`spinoffdividend` value in `dividend_per_share`. Continuing past the spin-off
hook must not let ordinary dividend accrual misstate that proxy as settled
cash. A scoped diagnostic ledger-accrual hook therefore defers precisely the
source-proven proxy while leaving the published observation and every price
untouched. It returns no receivable or cash event; it never injects a zero into
the financial input. The unvalued claim records the raw source value as evidence,
not as legal consideration or a child valuation.

The registry reads the exact retained `actions.csv.gz` member (5,322,055 bytes,
SHA256 `ec6f1d96c0beed8bf4baba45a55cc56a881f001d27456b9630471d69e2d46139`).
It retains individual codec-compatible row hashes and their source multiplicity,
without making unrelated duplicate source rows a global admission obligation.
Every affected unresolved row must occur exactly once. The registry checks every unresolved
typed event against its native row. A proxy deferral requires exactly one native
spin-off-dividend row for the affected held parent/date, no separate ordinary
dividend row, and exact equality of the actual parent-bar dividend and source
value under the frozen original binary64 parser. No quantization, subtraction,
sum of ambiguous legs or approximate equality is permitted. Missing or combined
cash evidence refuses. All raw values and quotes remain inside encrypted
evidence; public request metadata contains hashes.

The hook checks every expected parent-episode accrual call, binds its original
shares and raw source value, and proves the complete ledger unchanged. Ordinary
dividends and previously earned receivables follow their original paths. The
first actual canonical transition and each later use must prove that no
current-source proxy accrual, payment or receivable was created. A failure after
an unresolved claim remains an unsent tail, never a committed successor.

## Shared exact suffix integration

The suffix workflows use the shared exact-predecessor engine and versioned
retained-anchor writer for P03/P05/P06/P07, one separate hosted VM per arm with
at most four concurrent arms. The first frozen request selects P03/P05; the
separate spin-off successor request selects only P06/P07 so their additional
no-settlement qualification does not delay the independent anchor-only suffixes.
It reuses the frozen job body through an explicit source-bound namespace;
entrypoint, request and selected-arm bindings name the new successor. P06/P07 install this context adapter
around the continued diagnostic context. They restore their own committed
diagnostic runtime and event chain, retain full original journals and recovered
tails, and traverse every subsequent canonical session. They never restart from
their original strict parent or adopt the old uncommitted tail as state.

Source, frozen inputs, old financial parent and previous diagnostic artifacts
are read-only. Actual cryptographic admission precedes restore; workers retain
the existing disk-headroom gates, two-CPU/eight-GiB/no-swap/offline fences and
stopped/error receipts. No local canonical financial transition, production
execution, broker/account route, PAPER change, parameter change or financial
result is authorized by this adapter. Hosted first-use proofs remain necessary
after pure source/typed/stub tests, including guard-removal falsifiers.

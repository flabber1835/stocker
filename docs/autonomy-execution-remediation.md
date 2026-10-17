# Autonomous execution remediation

Decision: 2026-10-17, before implementation. Broker observations own the actual
account; Wealth Core and Sentinel retain independent intended holdings and
exposure. These repairs grant no live transport capability or new authority.
They preserve account binding, durable command identity, UNKNOWN recovery,
published source authentication, and the existing paper execution membrane.

## Provider identity continuity

The source-bound Alpaca security resolver will expose the current native asset
UUID for each canonical identity from the already authenticated reference and
source bundles. Position reconciliation must compare the current position to
that exact current UUID. Historical commands retain the exact UUID originally
admitted for their order; multiple historical UUIDs alone cannot invalidate the
book after an authenticated name-change continuation. Exact order reconciliation
continues to reject a changed UUID under an existing command identity. A broker
without this authenticated source mapping retains the previous strict identity
check. No symbol-only UUID replacement or inferred continuity is permitted.

## Available purchase funds

The shared pure `contract.available_purchase_cash` calculation requires fresh
account evidence with usable, nonnegative cash and buying power and multiplier
one. Its available funds are the lower of those amounts. This is a conservative
paper purchase budget; it does not prove that cash is settled or that all native
reservations are represented. Alpaca multiplier one is limited margin and can
permit reuse of unsettled proceeds. The quote and fixed quantity must fit the
paper budget before submit.
Insufficient funds use the existing typed, command-bound no-transport deferral,
so another independently fundable leg may proceed. Deferred purchases are never
queued outside their existing session window; later-session intent is owned by
the ordinary next canonical plan. The live transport fence remains closed until
broker-native settlement and reservation evidence is qualified as described in
[live trading readiness](live-trading-readiness.md). This does not resize a
transported command or infer an unexplained flow.

## Native fills and serialized cumulative averages

Native activity identity, fill quantities and fill prices remain exact. A broker
cumulative average is a finite decimal serialization of their weighted mean;
that mean may be nonterminating. For an explicitly fractional decimal average,
compare exact native gross to the interval represented by its last decimal
place, using half a unit in that place per filled share. An integer or positive
exponent declares no fractional precision and retains exact gross equality.
Equality at an explicit fractional rounding boundary is admitted;
larger disagreement is contradictory. Do not round or alter native cash amounts,
fill quantities, event identity, or durable command economics. Exact gross
equality still passes without applying any interval. Tests must cover a recurring
mean, an out-of-interval price contradiction and fractional quantities.
For incomplete native coverage, known gross must leave strictly positive
notional below that same interval's upper bound. Comparing a partial subtotal
to the rounded midpoint can falsely refuse a very small missing fractional
execution; it does not establish the actual missing execution's cash amount.

## Evidence verification resource bounds

Preserve every original observation and its existing authenticated representation.
Replace the lifetime JSON fetch with bounded, ordered keyset pages through one
captured upper sequence. Every page receives the same semantic/digest checks as
before; no historical row is skipped, and a concurrent append is verified by the
next invocation. The page count, peak resident rows and full-scrub behavior are
qualified with retained evidence and tampering fixtures.
The scan also pins the account name and establishment boundary. Each page must
retain that exact binding, and the binding is checked again at completion;
concurrent rebinds or disappearance of the captured range refuse the scrub.

New observations use a compact `broker-observation-witness/v5` storage payload in
the existing `broker-observation:v4:<sequence>` logical key namespace. It retains
the exact sequence, account, observation start/time, recovery boundary,
completeness and canonical payload SHA-256. The primary observation and its
separate provenance already reconstruct every canonical position, order and
exact lookup; their independently stored digest and this separate immutable
witness must both agree with that reconstruction. Missing/tampered witnesses,
partial restores and mutation of any economic representation continue to refuse.
Legacy v4 full payloads remain readable and are never rewritten. The Alpaca
recovery reader uses the same per-row verifier to reconstruct either format.
This removes the third full economics copy for new rows without deleting audit
history, changing the database schema, or trusting a self-reported hash alone.

This repair introduces no trusted process cache or durable verified-prefix
checkpoint. Such a checkpoint requires a separately proved authenticated range,
immutable-prefix/catalog guarantee and restart/restore behavior. Total full-scrub
CPU work and historical command reconstruction remain linear in retained history;
the delivered page bound is not a claim that these costs have been eliminated.

## Compatibility and qualification

The retained re-genesis reader must accept the exact current journal provenance
shape, including exact-order evidence, while validating it rather than ignoring
additional fields. Existing two-field historical provenance remains readable.
This repairs a retained compatibility path and does not authorize re-genesis.

Add targeted regressions and demonstrate that their relevant assertions fail on
the pre-repair implementation. Run directly affected execution/paper tests and
static checks. Record source identities and measured resource results; simulator
or fake-transport qualification is not native broker, NAS, or live acceptance.

## Resource measurements and remaining qualification

The synthetic decoded-observation measurement calls the production keyset
reader with 16 KiB rows and verifies identical consumed sequence totals. At
4,096 rows, eager decoding peaked at 67,744,258 traced Python bytes; the bounded
reader peaked at 2,152,029 bytes, a 96.8% reduction, fetching at most 128 rows.
At 1,024 rows the bounded reader remained at the same approximately 2.15 MB
peak. This measures decoded-row memory, not PostgreSQL/NAS memory or a native
end-to-end latency benchmark. Both traversals remain linear in row count;
short synthetic timings do not establish a meaningful CPU speedup.

For a canonical fixture containing 14 positions and no orders, the former third
full JSON payload is 1,316 UTF-8 bytes and the new witness is 338 bytes, a 74.3%
reduction of that representation. Primary observations, provenance, indexes,
WAL, retained legacy rows and backups remain; this is not a 74.3% reduction of
the entire database or a reason to remove original evidence.

Still required before live activation: qualify native cumulative-average
serialization/rounding semantics and complete broker-native financial activity,
settlement and reservation evidence against retained provider responses. The
fractional interval is an explicit paper interpretation, not proof of the
provider's live rounding contract. Native capability flags remain unchanged.
No verified-prefix checkpoint or bounded active-command replay has been
introduced: preserving historical identity and fill recovery takes priority
until an authenticated, account/range/schema-bound recovery proof is available.

## Execution acceptance record

Verified implementation base: `118b7c15249e47bd7ea79a23ecbc58b6dc947741`.
The final directly affected execution set passed **393 tests in 132.25 seconds**
inside `sentinel-stable-dashboard-test:da06a9ee`, with `--network none`,
`--read-only`, a temporary `/tmp`, the feature worktree mounted read-only at
`/review`, `PYTHONDONTWRITEBYTECODE=1`, and
`PYTHONPATH=/review:/review/shared`:

```text
python -m pytest -q -p no:cacheprovider --tb=short
  tests/sentinel/test_autonomy_execution_remediation.py
  tests/sentinel/test_observation_witness_storage.py
  tests/sentinel/test_alpaca_boundary_overlay.py
  tests/sentinel/test_dependency_recovery.py
  tests/sentinel/test_native_fill_progression.py
  tests/sentinel/test_native_fill_acceptance.py
  tests/sentinel/test_trial_fill_interval_proof.py
  tests/sentinel/test_trial_fill_interval_evidence.py
  tests/sentinel/test_regular_quote_submission.py
  tests/sentinel/test_dual_regenesis_handover.py
  tests/sentinel/test_journal_and_reconcile.py
  tests/sentinel/test_guarded_execution_broker.py
  tests/sentinel/test_automation_runtime.py
```

The initial six regression cases produced five failures on the pre-repair
implementation: current UUID authority, fresh reserved buying power, both
recurring-average quantities and current re-genesis provenance. The existing
out-of-interval contradiction already passed and remains enforced. Seven
separate disposable mutation runs then produced the expected failing assertion
when bypassing available buying power, permitting arbitrary average disagreement,
removing UUID conflict checks, eagerly materializing all history, bypassing
observation verification, restoring midpoint-only partial-fill checks, or
removing the final pinned-binding check. No mutation was written to repository
source. AST parsing passed for all 13 changed Python files, and `git diff --check`
passed. Existing golden fixtures and native capability flags were not re-pinned.

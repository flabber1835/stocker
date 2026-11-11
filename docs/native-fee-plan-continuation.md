# Native debit fees and immutable execution plans

## Decision and scope

The owner authorizes a local execution-policy correction after the November 10
opening attempt. A recognized, fully explained native debit fee is an execution
expense. It does not, by itself, invalidate the canonical holdings decision or
require retiring its immutable execution plan. There is no cents threshold.
This changes PAPER execution policy; it is not a claim of economic equivalence
with the former universal changed-activity retirement rule.

Only new, strictly negative native `FEE` rows whose retained detail is exactly
`INTERNAL/FEE` may earn this exception. All rows since the plan boundary must
qualify. Credits, non-fee rows, mixed event sets, missing native identities,
changed prior rows, incomplete or corrupt history and unexplained cash retain
the existing refusal/reconciliation/retirement rules. A zero net change does not
prove an unchanged event set. Zero-valued structural events retain their existing
separate share-unit/action guards and confer no fee authority.

Wealth Core, the controller, shadow cash and historical decisions are unchanged.
No superseded plan is resurrected, and this patch issues no broker operation.
Unknown broker outcomes still require reconciliation before any new mutation.

## Immutable membership boundary

The existing v3 baseline contains a cumulative total and a last native cash ID.
Neither is a membership proof: offsetting events can preserve the total, and
native reference IDs are not an append sequence. Business dates and database
insertion timestamps must not be used to infer the missing interval.

Newly created baselines use `broker-cash-plan/v4`. In the same existing writer
transaction, the baseline retains the exact account-qualified nonzero native
ledger membership and a SHA-256 commitment to each row's native ID, business
session, exact rational amount and complete classification detail. This lives
inside the one immutable baseline instead of adding a separately owned cursor
or a new physical table. Capture requires agreement with the current durable
Activity-SSE cursor, exact ledger total and retained last native cash ID.

Existing v1-v3 baselines remain readable and immutable. They cannot acquire v4
membership retroactively and therefore cannot earn the fee exception. Re-reading
or retrying baseline creation returns its original representation only when its
original account, session, cursor and amount still agree; it never reanchors it.

At every v4 cash admission the canonical cash owner checks the same accepted account and
identity scheme, nonregressing capture time, the actual current durable cursor,
and the current ledger. Every original member must remain byte-economic equal;
every new nonzero member must be a strictly negative `INTERNAL/FEE`. The new
members' exact sum must equal the baseline-to-current total delta, and the new
last cash ID must name one of those members. An unchanged total and last ID do
not skip this check: edited/deleted original members or offsetting added rows
must not hide behind the old tuple. Without added members both original total
and last ID must remain unchanged. Missing or contradictory membership
is negative evidence, not permission to infer an expense.

## Money and recovery boundaries

The fee exception additionally requires exact equality between fresh actual cash
and immutable plan cash plus durable fills plus native activity delta. It cannot
borrow the pre-existing generic cash discrepancy tolerance. A fee does not grant
cash, increase a target, change a quantity, change a plan fingerprint or rewrite
its baseline. The cash check reports whether changed activity still requires
plan retirement; an admitted fee-only delta reports no retirement requirement.
Recovery still requires its complete, clean, quiescent settled-account bracket.

New activity-backed protected funding uses `sentinel.protected-buy-funding/3`.
Its typed native boundary retains the original activity tuple and exact native
membership when that one immutable funding basis is earned. The older /1
activity-backed and /2 no-activity variants remain readable without promotion.
The original funding cash, policy, projection, maximum promises and observation
are not replaced. Plan membership alone is insufficient here: a fee already
present at funding time must not disappear and be replaced by another fee.

For /3 the canonical funding owner validates its original members on every
admission, even when its activity hash is unchanged. A changed hash may continue
only when its independently preserved funding boundary proves exclusively new
debit fees, and the canonical plan-cash owner independently proves plan-v4 fee
continuity and the exact current plan/fill/activity cash equation. The funding
owner invokes that proof itself using the current durable plan and account;
there is no caller-provided override, supplied proof boolean or invented broker
observation. Current cursor time, account and source scheme remain required.
An old /1 basis cannot be silently upgraded after fees arrive.

One funding admission owns one current native-ledger read. The funding owner
loads the actual persisted funding and plan boundaries under its existing
writer lock. The broker-cash owner reads the current durable cursor and native
ledger once, then evaluates both immutable memberships against that same owned
value. The cash owner retains the one exact plan/fill/native cash equation.
No caller supplies a permission verdict or substitutes a membership proof;
the canonical funding owner selects and checks the persisted boundaries itself.
This reuse is local to that one admission. It does not cache across callbacks,
current observations, transactions or later BUY attempts. Fresh account and
cursor admission, original proof clocks and every monetary guard remain.
The funding owner also loads the actual account-scoped command journal once
under that same writer scope. The shared cash equation filters those rows to
the exact current plan; original promises and other-plan/UNKNOWN refusal use
the same complete account-scoped rows. Neither public submission nor cohort
admission accepts caller-supplied commands. A plan-scoped prefilter must never
hide an older unresolved obligation, and older-plan fills cannot be added to
the current immutable plan's baseline again.

Before every BUY the existing guarded transport still obtains fresh actual cash
and activity evidence, validates current authority and account permission, and
enforces fixed allocation, other live reservations, buying power, whole shares,
headroom and long-only/unlevered limits. If a fee makes the immutable obligation
unaffordable, existing funding refusal/defer behavior applies; the plan is not
silently resized or financed. Exposure selection and security selection never
read this broker evidence.

## Qualification and source identity

Use real private PostgreSQL and accepted Activity-SSE fixtures to cover restart,
multiple fees, exact fee replay, old and empty baselines, preserved plan bytes,
prior membership edits/deletions, unknown and mixed classifications, credits,
offsetting events, cursor/account/scheme/clock drift, missing membership and
insufficient fresh cash/reservations. Executed omission falsifiers must detect
removal of the negative-fee predicate, original-member binding and exact cash
equation. Existing cash-lag, immutable-baseline and native-credit tests remain.

The changed execution modules require actual new source-history commitments.
They must not be hidden by an equivalence mask or rewriting historical function
witnesses. The source handover owner records the exact new hashes and any current
execution-policy function commitments separately; historical fixtures retain
their original scope.

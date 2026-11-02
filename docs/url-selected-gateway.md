# URL-selected operational gateway

Decision before implementation: expose neutral preparation, current-plan,
execution and read-only recovery operations selected by the canonical Alpaca
origin. PAPER delegates to its existing public gateway and retains its durable
bytes and administrative command restrictions. LIVE uses the same canonical
strategy state, plan builder, projection, reconciliation, journal, executor and
guarded broker. It does not create another Wealth Core book or infer strategy
state from the account.

## Canonical LIVE inputs and identity

A LIVE deployment must already have its exact `alpaca-live` account binding and
an authenticated current canonical shadow. The shadow worker's enable flag
selects that worker's role only; the LIVE consumer reads the configured shadow
identity/capital even when its own broker-capable service disables the worker.
The actual verified chain is required, independently of that flag. Preparation reads that state and its
cursor, checks the current strategy, pinned publication, latest closed exchange
session and rollout, then calls the existing `build_execution_plan`. It does
not form a new book, replay historical broker trades, liquidate another account
or silently replace a PAPER binding. Existing current-plan economics are
immutable; restart revalidates and reuses the same plan.

The shared immutable `dual_plan_authority` sizing proof is account-bound data,
not PAPER permission. LIVE reuses that proof with its distinct binding and a
fully verified canonical shadow result. It never accepts a PAPER post-gap
regenesis approval: a nonzero shadow segment remains refused pending a separate
LIVE origin review. Shadow verification remains read-only and retains its
existing source/runtime compatibility gates.

## Fresh financial boundary

Every LIVE broker operation retains the existing guarded composition and fresh
database connection callbacks. They validate exact binding, current runtime and
source, enrolled LIVE certificate, rollout, publication/frontier, exchange clock
and operation grant. Automated calls also revalidate their current durable
control generation, kill switch, leader lease and cycle; manual execution has
exact account, plan and effective-session confirmation. Mutations require the
real enabled backup policy and its current proof, never a local PAPER exemption.
The global emergency kill switch also fences manual LIVE mutations. Its default
engaged state requires the explicit qualified LIVE activation/release path;
a manual grant cannot bypass it or grant unattended operation.
The backup runtime policy and archive guard branch on the exact URL before
considering any owner-PAPER exemption. LIVE ignores those exemption flags,
requires the separately selected real backup authority and verifies its actual
restore chain. The same rule applies to native restart/restore increase fences;
the distinct LIVE namespace cannot skip those fences.
After the HTTP client's final asynchronous entry, the single-use transport
permit invokes the same synchronous fresh-database authority check immediately
before the actual request. A kill, lease/control change, source change or
revocation during client entry therefore refuses the request.

The canonical shared source/action and plan-authority checks remain mandatory.
Strict native reconciliation is required; the informational PAPER reporting
exception cannot become LIVE completeness or recovery evidence. Unsupported
native actions or corrections stay refused rather than becoming a fabricated
position or cash adjustment.

LIVE execution resolves and records the existing protected target projection,
then calls the same durable executor. Its LIVE policy loads the original
writer-locked SEND_PENDING command, the full retained commitment set, fresh
account and complete order/position observations, and authenticated prior-close
references from that immutable projection. Fresh observations must agree with
the durable command economics and expected held book. This read does not run a
second reconciliation on the current unsent SEND_PENDING command.

Optional native funding comes from `SENTINEL_LIVE_FUNDING_CERTIFICATE_PATH` and
the explicitly configured public LIVE trust enrollment. A qualified bounded
source contract (`sentinel.live-native-funding-contract/1`, at most 31 days)
permits the runtime to derive fresh evidence automatically from exact allowlisted
native account fields. It requires independent provider/settlement acceptance;
ordinary account fields have no implicit funding authority. Short-lived signed
native receipts remain supported. The public file and scoped enrollment are
reread, and signature, subject, native observation hashes, original interval and
revocations are verified at the actual BUY boundary. An absent file defers BUYs;
malformed, stale or contradictory evidence
does not authorize spending. No ordinary cash/settled label, completed page or
caller balance substitutes for that proof. SELLs retain long-only owned-quantity
limits. The low-level adapter accepts a mutation only within the canonical
wrapper's single-use, exact-request permit.

Stock BUYs additionally use the existing canonical issuer admission engine and
retained source evidence. LIVE selects a distinct policy digest and account
namespace, requiring an explicit `enroll-live-issuer-policy` transition under its
current signed execution authority while the kill switch remains engaged.
Enrollment accepts only an empty native book, never PAPER grandfathered episodes.
Absent enrollment or current issuer evidence defers stock BUYs. PAPER policy
digests, evidence and command bytes remain unchanged; the T-bill sleeve retains
its existing exemption from stock issuer checks.

Read-only recovery uses the same account namespace, reconciliation and journal;
it cannot submit a new order or reinterpret UNKNOWN as absent/failed. It is
available without selecting a new plan or changing the canonical shadow.

## Operator and service integration

Neutral CLI operations live in the authorized executable-capability surface:
`prepare-trading-plan`, `current-trading-plan`, `execute-trading-plan`, and
`recover-trading-account`. The URL is the only mode selector. Matching credentials,
an explicitly provisioned matching account, separate LIVE trust/authority and
current qualified evidence remain prerequisites. PAPER-named administrative
commands stay PAPER-only.

The existing automation service routes prepare/recover/execute to the neutral
gateway by URL while preserving its scheduler, control, lease and durable-cycle
semantics. Selecting LIVE cannot reuse owner-PAPER financial exemptions,
informational paper history or an old PAPER control binding. First LIVE binding
and activation remain explicit reviewed operations, with no deployment or
broker access performed by this PR.

Offline tests cover URL dispatch, wrong-environment binding, unavailable shadow,
missing authority and funding, stale context, original command reservations,
PAPER regression behavior and the absence of accidental live transport. Native
provider acceptance, actual opening timing, economic qualification and an
authorized live pilot remain external evidence gates.

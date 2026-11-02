# URL-selected PAPER and LIVE execution

Owner request: implement the remaining live-execution coding in a separate PR,
with the Alpaca trading URL selecting PAPER or LIVE. This is a reviewed code
and design change, not permission to change the installed PAPER account,
collect live credentials, deploy, or submit real-money orders.

## Selection and durable separation

Reuse `TradingEndpoint.parse`: the exact HTTPS paper origin selects
`ALPACA_PAPER`; the exact HTTPS live origin selects `ALPACA_LIVE`. No second
boolean, import-string plugin, hostname substring, proxy, or fallback selects
the environment. Unknown origins refuse before credentials or transport.

Keep existing PAPER binding, plan, certificate and command representations
byte-compatible. Its durable broker namespace remains `alpaca`. LIVE uses the
distinct durable broker namespace `alpaca-live`, and a versioned command subject
which includes the canonical environment and trading origin. The native adapter
reports the selected namespace. Identical account UUIDs in different environments
must not match. A URL edit never rewrites a binding, adopts another account,
rekeys an UNKNOWN command, liquidates a book, or resets the canonical shadow.
An existing database bound to the other environment refuses and requires an
explicitly provisioned matching deployment; credentials alone do not migrate it.

Wealth Core and Sentinel retain their existing single canonical implementation
and broker-free inputs. Environment selection belongs exclusively to execution.
Existing administrative takeover/liquidation commands remain explicitly PAPER
operations. Ordinary neutral operational entry points select the matching
execution path from the URL.

## LIVE authority and financial limits

PAPER authority, observation leases, local owner-PAPER exemptions, adapter
qualification and historical source receipts are never LIVE authority. LIVE has
a separate signed certificate schema and validation path, exact environment,
origin, deployment, account and takeover subject, explicit expiry, and explicit
capital, per-order, daily BUY commitment and protected-price limits. There are
no permissive defaults. Enrollment and issuer trust are deliberate; no private
issuer key or live credential belongs in source control.

Use the existing guarded execution membrane, durable plan and command journal.
Revalidate the selected subject and live authority at reads and immediately
before mutation. Revocation, stale account evidence, a missing lease, a kill
switch, changed account or missing qualification refuses. Retain original
command identity, quantities, prices, DAY terms and reservations across UNKNOWN,
lost responses and restarts. Long-only and unlevered guards remain mandatory.

## Native funding and accounting

LIVE BUYs require independently authenticated, current native settlement and
reservation acceptance bound to the exact selected subject. Ordinary cash,
buying power, multiplier one, terminal fills, completed activity pagination and
PAPER receipts do not establish settled money. Neither a caller's `NATIVE`
label nor a well-formed digest proves provider provenance or finality.

The live funding boundary subtracts durable open and UNKNOWN commitments,
enforces the original order terms and daily/capital limits with exact Decimal
economics, and defers BUYs when evidence is missing, stale or inconsistent.
Do not reuse the paper plan-cash fallback or immediately recycle sale proceeds.
The isolated simulation/accounting candidates retain their original claims;
unsupported native corrections, busts and corporate actions remain quarantined
until their provider semantics and durable integration are independently accepted.

## Delivery and qualification

The normal operator mode setting is `ALPACA_BASE_URL`, with the matching account
credentials and separately enrolled authority. A status/refusal must identify
the selected environment and the specific missing gate without exposing secrets.
Changing the URL selects the environment; it does not manufacture qualification.

This PR implements and tests software behavior offline. Actual-account provider
acceptance, original-clock execution timing, current economic evidence, qualified
recovery and a separately authorized limited-capital pilot remain distinct
evidence gates. An unqualified installation stays fail-closed; no green unit
test or file inventory is relabelled as live certification. The installed PAPER
deployment and its current authority are unchanged by this development work.

Use targeted tests and behavioral guard-removal falsifiers for URL lookalikes,
same-UUID cross-environment binding, PAPER certificate replay, legacy PAPER
command hashes, stale/revoked LIVE authority, capital/order/daily limits,
unsettled sale proceeds, UNKNOWN reservations and lost-response recovery.
No protected backtest, Wealth Core change, full-suite run, live API call,
deployment, or real-money pilot is part of implementation verification.

## Mutation composition

The existing exact `GuardedExecutionBroker` remains the only ordinary mutation
membrane. LIVE composition adds a canonical order policy that loads the original
durable command, fresh account/positions and retained commitments. It verifies
signed live authority and, for BUYs, independently signed native funding evidence.
PAPER manual/attended grants cannot be used as LIVE grants.

Only after those checks may the wrapper scope a short-lived, single-operation
transport permit. A permit names the concrete adapter instance, operation and
complete original submit tuple (client key, instrument, side, quantity and order
terms), or the exact owned cancel ID. Context-local scope prevents concurrent
tasks from borrowing permits. The adapter rechecks authority at every HTTP site
and refuses a LIVE mutation outside the matching scope. A policy refusal occurs
before transport and retains the existing proven-unsent recovery semantics;
transport uncertainty never acquires such a proof.
After asynchronous HTTP-client entry, the permit consumer synchronously repeats
current authority/control/lease checks and funding acceptance, checks that the
certificate and funding receipt still match those assessed, and rechecks the
earliest evidence expiry and regular opening window. No intervening await may
separate these final checks from the broker mutation request.
Permit lifetime is capped at 30 seconds, never later than the independently
observed account, funding or certificate expiry. This uses the same financial
freshness bound while allowing the complete synchronous source verification to
finish; it does not extend any evidence's own lifetime.

## Monitoring and deployment wiring

GET-only account/fill collection selects the same URL and durable namespace as
execution. LIVE collection independently verifies the current public LIVE READ
certificate and exact bound account around each request; its facade exposes no
submit, cancel or account-closing operation. Notification sending remains free
of broker credentials. Existing PAPER notification and performance history keeps
its original financial scope rather than being relabelled as LIVE evidence.

The LIVE monitoring facade constructs a private read-only adapter, restricts its
GET routes to account, bounded open orders, one exact native order UUID and its
bounded FILL activities, and exposes only the collectors' account/parser methods.
Each HTTP GET independently opens and closes a fresh database connection to load
the current owned LIVE binding, runtime/strategy identity, rollout and public
READ authority immediately before dispatch and again after its response. The
initial exact subject and certificate must remain unchanged across that request;
native account UUID responses must match that subject. A captured certificate
context never substitutes for fresh ownership. Collection additionally brackets
all account/order/activity work with matching native account observations and a
fresh durable-binding comparison before publishing evidence. Injected plain
readers cannot bypass the LIVE facade; PAPER retains its existing reader seam.

LIVE account polling is enabled by exact URL selection, independently of the
local-owner PAPER exemption. FILL polling retains its explicit notification
boundary. LIVE-only fill payloads carry the actual environment, origin and
durable broker namespace; existing PAPER payloads retain their original bytes.
Account evidence already stores that namespace. Display-only PAPER reservation
proofs remain PAPER-specific and grant no LIVE settlement or trading authority.

Compose forwards the selected URL and public authority/settlement paths to the
roles that need them, mounting the public authority directory read-only. It
never mounts issuer private keys. The dashboard shows a separate explicit
selected-environment label, and its cache subject includes that URL so a mode
change cannot reuse a prior environment's cached account facts. Historical
PAPER-specific verification and performance claims retain their PAPER labels.

## Versioned LIVE certificate boundary

The new `sentinel.live_execution_certificate/1` envelope signs its schema,
Ed25519 algorithm, key identity and complete claims using canonical JSON.
Only separately enrolled `LIVE_EXECUTION` roots qualify; no root is enrolled
by default and PAPER trust-root records are not accepted as LIVE roots.
Certificate and key revocation, issuer validity, current runtime bindings,
the exact LIVE subject and the requested READ/SUBMIT/CANCEL/AUTOMATION operation are
rechecked for every admission. Issuance and enrollment remain external reviewed
operations, never a URL side effect.

Claims contain explicit capital, order, daily BUY commitment and protected-price
limits, a validity interval of at most one day, and signed references for native
settlement, native reservations, accounting, recovery, opening timing, strategy
economics and pilot authorization. These references are accepted only through
the explicitly enrolled reviewer signature; hashes supplied without that
signature grant nothing. Native funding observations additionally require their
separate `LIVE_SETTLEMENT` signer and current exact-account evidence.

The runtime comparison binds `runtime_image_digest`, `sentinel_source_sha256`,
`runtime_identity_sha256`, `strategy_identity_sha256` and
`execution_config_sha256` computed by the caller from the actual deployment.
Mutable trust/revocation providers are read anew rather than cached in an
adapter admission. The raw broker mutation permit remains a separate guarded
membrane requirement; a valid certificate alone is not an order command.

The production loader requires explicit absolute `SENTINEL_LIVE_CERTIFICATE_PATH`
and `SENTINEL_LIVE_TRUST_ROOTS_PATH` public files. Missing files/enrollment refuse
before adapter construction. The enrollment schema is
`sentinel.live-trust-enrollment/1`, with bounded exact LIVE-scoped public-root
records and certificate revocation digests. Certificate bytes, public enrollment
and revocations are reread rather than cached permissions. No private key or
broker credential is read by this loader.

The loader first requires the existing durable `alpaca-live` binding. It derives
the expected subject and current source/image/strategy identities independently
of certificate claims. Its execution configuration digest binds the exact URL,
public enrollment, protected-order policy, automation configuration and durable
rollout mode/version. The rollout's certificate digest is checked separately
for CONTROLLER mode to avoid a recursive certificate hash. Existing publication,
kill-switch, control-generation and lease checks remain separate requirements
of the canonical guarded membrane.
The admission's context provider rereads the durable binding and rollout at
each validation, so an adapter cannot retain a withdrawn subject or rollout
configuration. This also allows certificate rotation to compare against the
current configuration without retaining its creation-time snapshot.

## Explicit LIVE account provisioning and activation

A fresh LIVE deployment uses an attended `BIND_EMPTY_LIVE` operation with a
separate `sentinel.live_administrative_certificate/1` envelope and separately
enrolled `LIVE_ADMIN` root. This short-lived authority permits only GET account
and empty-book checks plus recording the named first binding; it cannot submit,
cancel or activate execution. Exact deployment/account confirmations and an
explicit empty-live-account confirmation are mandatory. The operation requires
an unbound database, disabled and killed control, no lease, no financial history
or prior ownership. Two stable GET-only account/orders/positions observations
must show the exact active, unlevered, empty account before the existing writer
lock commits ownership evidence and `alpaca-live` binding together. Existing
bindings and ambiguous/nonempty books refuse; no takeover or liquidation is
inferred. The binding and recorded administrative certificate digest prevent
ordinary replay. Restored-host external fencing remains the existing separate
operating obligation.

The bootstrap certificate is supplied through the explicit public
`SENTINEL_LIVE_PROVISIONING_CERTIFICATE_PATH` and the same scoped public enrollment
file. Its validity is at most one hour; PAPER and execution certificates cannot
authorize it. It does not alter the canonical shadow or grant settled funds.
Subsequent LIVE automation activation requires qualified LIVE execution
authority, exact real-money/account/deployment confirmations and the existing
control binding. It deliberately leaves the kill switch engaged. Releasing that
kill is a second confirmed operation with fresh exact authority and configuration;
neither operation changes the durable rollout or places an order.

Unattended operation requires the separate signed `AUTOMATION` permission in
addition to READ/SUBMIT/CANCEL and the actual automation configuration identity.
A manual execution certificate cannot be promoted to unattended use by an
activation confirmation, a URL change or a configuration hash alone.
Neutral manual and service entry points independently compute the same actual
automation configuration fingerprint when no explicit fingerprint is supplied;
that identity comparison is separate from the signed AUTOMATION permission.
The signed execution configuration also binds the actual LIVE issuer-admission
policy digest selected from the durable `alpaca-live` subject. Administrative
provisioning uses the same independently computed configuration context; a
PAPER issuer policy or caller-supplied policy digest grants no LIVE identity.

The final LIVE transport check also reruns the existing synchronous issuer
admission callback for the exact original command. The task-local permit records
the identity of a refusal raised by that check before HTTP. Only that exact
permit-issued refusal may receive the membrane's existing single-use unsent
journal proof. An arbitrary inner adapter exception, including a lookalike
pre-transport exception, cannot establish that an order was never sent.

## Normal operation after enrollment

`ALPACA_BASE_URL=https://paper-api.alpaca.markets` selects simulated trading;
`ALPACA_BASE_URL=https://api.alpaca.markets` selects real-money trading. The
matching Alpaca credentials are supplied through the existing private
environment. There is no second enable-LIVE switch. The same automation service
and neutral `prepare-trading-plan`, `current-trading-plan`,
`execute-trading-plan`, and `recover-trading-account` commands select the
appropriate gateway. `config/sentinel-trading.env.example` shows the URL and
public artifact paths accepted by the Compose overlay.

Enrollment is a separate, one-time deployment operation. Keep each environment's
database, binding and journal together: a URL change cannot convert the current
PAPER binding into a LIVE account, overwrite a journal, or import PAPER balances.
A new LIVE deployment must complete the explicit empty-account binding, issuer
enrollment and qualified authority/activation process described above. Once
both environments are qualified, select the matching deployment environment and
URL; missing or mismatched configuration refuses clearly. Merely editing the
currently installed laptop's URL does not complete this first-time enrollment.

## Closed retained-source successor

Retained source compatibility adds one complete, sealed successor from reviewed
main revision `71b7c2a113dca8882f4cbf7a03d79f771e383092`. Its 422-file Python
source closure is
`85f353c936459255c048aedc366272ca4c6f3053f654a006da61a42af2688352`.
The new descriptor records every predecessor and candidate Python file and the
normalized checker identity. It authenticates the existing structural profile
and its complete predecessor map without changing any historical profile,
checker, financial golden or witness. Missing, extra, unknown or changed files
prevent the entire comparison edge; individual files gain no new allowance.

Only the complete exact candidate may use that predecessor map for historical
comparison. An exact predecessor manifest uses this new edge directly; older
manifests continue through the already sealed structural comparison. Actual
runtime source, image, strategy, certificate and configuration identities remain
the actual executable identities. A backed-owner PAPER scope retains its fresh
mode and account requirements and binds its current-file proof to actual bytes.
The descriptor's authority effect is exactly `NONE`: source compatibility grants
no broker, financial, LIVE, activation, backup or deployment permission. Its final
map is sealed only after all runtime Python changes are stable.

After merging the independently reviewed backup disk isolation release, the
new URL descriptor uses schema `sentinel.url-selected-trading-transition/2`.
It pins main's existing structural profile
`12e5447817a8f583e2dbf57acfb7af857d0155f4600a2fff4bdef8d748aa429f`
without changing that profile or its checker. It also retains the exact prior
421-file main snapshot `403617ec3df4ba0950a989fa140038802f7e7b6e`, with canonical
closure `d83a9932ae32e0d87adde8691fcc36a7a8c1d93658f2c0ce954a211363918691`,
as a second direct predecessor. Only an entire exact final candidate may use
either entire predecessor map; unknown combinations gain no allowance. The
ordinary comparison uses the new main snapshot before the unchanged structural
comparison to the original financial baseline. This preserves both published
source histories while retaining the separately qualified strict LIVE backup
requirements and main's exclusively PAPER continuity policy.

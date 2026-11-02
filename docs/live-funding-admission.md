# LIVE funding admission

This implements the native-funding boundary in [URL-selected execution](url-selected-trading.md).
The execution membrane revalidates the exact signed LIVE account authority for
every request. A URL, an account response, or a caller's provenance flag does not
establish settled funds.

A separate, canonical Ed25519 `sentinel.live-funding-observation/1` envelope
binds the full execution subject, effective session, original observation clock,
expiry, exact typed account and position snapshot digests, native evidence digest,
settled cash, provider reservations, and complete current long/short valuations.
Its settlement, reservation and accounting contract references must equal the
separately reviewed references in current LIVE authority. Issuers require explicit
`LIVE_SETTLEMENT` enrollment; execution/PAPER keys are not settlement enrollment.
No issuer, accepted native collector or credential is enabled by this change.
Enrollment requires the independent actual-provider qualification recorded by the
referenced contracts; signing a generated fixture does not qualify a provider.

An observation is valid for at most thirty seconds and must match independently
collected current account and position evidence. Missing or expired funding defers
BUYs. Changed subjects, signatures, observations or contract references refuse.
The assessment carries the earliest authority, account and funding expiry. The
execution membrane must check that expiry again at its final no-await transport
boundary, so intervening authority work cannot extend an observation's lifetime.
The signed valuations supply capital evidence; no caller-supplied completeness
boolean or unverified market-value dictionary substitutes for that source.

Every nonterminal durable BUY reserves its original whole-share quantity times
its immutable limit, including PLANNED, SEND_PENDING and UNKNOWN commands. The
provider reservation total is added conservatively, without assuming overlap or
releasing a journal promise from a balance. Daily commitment counts original BUY
promises made on the effective exchange day and every older unresolved promise.
Even a same-day confirmed cancellation does not replenish the daily commitment
limit. Positive terminal state can release only the separate outstanding promise.
Fresh settled cash remains bounded by actual cash and buying power; sale proceeds
never enlarge the signed settled amount by local arithmetic. Limits and all
arithmetic use exact Decimal inputs and Fraction accumulation.

Protected BUYs require immutable whole-share LIMIT/DAY terms and an authenticated
preceding closed-session reference, capped by both the signed premium and the
existing maximum of 100 basis points. Original per-order, total capital and daily
BUY commitment limits apply before transport. A repeated key must preserve every
original economic term; contradictory snapshots refuse rather than being merged.
The prior RAW price and canonical share-unit factor are compared as exact
Fractions. A 3:2 action must not force a rounded Decimal reference into the gate.

The public funding file is selected explicitly by
`SENTINEL_LIVE_FUNDING_CERTIFICATE_PATH`. Absence selects no funding authority;
it does not select another trading environment. Its public issuer records and
revocations use the existing `SENTINEL_LIVE_TRUST_ROOTS_PATH` enrollment format,
with independent `LIVE_SETTLEMENT` key scopes. Read bounded files afresh at each
assessment, reading each enrollment/revocation generation as one object. No
private signing key or account credential is read by this loader.

## Automatic collection after native qualification

The same public funding path may instead contain a separately signed
`sentinel.live-native-funding-contract/1`. This is the unattended consumption
path: an explicitly enrolled settlement issuer accepts exact account-specific
field semantics and a fixed `ALPACA_ACCOUNT_DECIMAL_FIELDS_V1` parser profile
for `GET /v2/account`, with the original independent qualification references.
The contract lasts at most 31 days; every derived observation lasts at most
thirty seconds. There is no per-order signing key or local issuer.

The broker port carries immutable typed `NativeFundingFacts` only in LIVE mode.
It binds the actual origin, account, USD currency, observation clock, ordinary
typed financial snapshot digest, and a finite allowlist of exact native Decimal
fields. The production consumer never branches on the audit raw dictionary.
Missing fields or unaccepted semantics defer; a field name never proves its
settlement meaning. No native field mapping or issuer is enrolled by default.

The signed contract explicitly names accepted settled-cash and provider-spendable
fields from that allowlist. The derived settled ceiling is the lesser of those
accepted values, still bounded by current actual cash and buying power. Its
reservation contract accepts the provider buying-power/spendable ceiling plus
the complete independently reconciled owned order set and all durable promises.
No sale value is locally credited. A source whose fields cannot establish these
semantics cannot be qualified through this profile; it remains refused rather
than inferring a settlement date or treating a multiplier as proof.

Complete fresh native positions, immutable journal identity, native long/short
valuations, and bracketed account reads remain mandatory. A changed extra funding
field between bracket reads invalidates the observation even when ordinary cash
and buying power did not change. Source contracts, enrollment and revocations are
reloaded at each assessment; signed receipt files remain a compatible alternative.
The fixed cash-only source profile also requires the native account identity
`equity = cash + long_market_value` with zero short value. A contradictory or
incomplete valuation cannot lower the capital charge or imply settled funds.
Actual provider/account acceptance and a valid independent qualification remain
external prerequisites; software fixtures exercise the consumer without proving
that an Alpaca field has the required real-world semantics.

SELL reductions retain their existing execution/authority/timing safeguards and
are bounded by current complete long holdings less other unresolved SELL
remainders. BUY funding, premium and capital restrictions do not prevent a valid
reduction. A short position, malformed or stale account, changed native instrument,
or overlapping unknown SELL cannot authorize an oversell. This module neither
contacts a broker nor creates plans, commands, accounting adjustments or authority.

Tests use separately scoped generated keys and explicitly synthetic receipts to
exercise the acceptance consumer. They do not claim native settlement, account
qualification, real execution, provider finality or successful financial recovery.

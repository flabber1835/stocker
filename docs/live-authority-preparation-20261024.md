# Offline preparation of live account restrictions

Decision: 2026-10-24, before implementation. This extends the owner's authorized
live preparation. It does not enable live trading or change the running PAPER
installation. Backups, archives and restore operations remain prohibited.

## Restriction arithmetic is separate from authority

Add a pure execution-layer candidate, not a new execution engine or account book.
It accepts typed caller-supplied simulation inputs and returns a restriction
assessment. Reuse the canonical `ExecutionSubject`, endpoint parser,
`FundingEvidence`/`assess_live_funding` and exact Decimal arithmetic. It reads no
environment, files, database, configuration or network. No production caller,
transport, policy selector, admission profile or authority issuer imports it.

The proposed policy binds one exact LIVE subject: native account UUID, trading
origin, environment, deployment and takeover epoch. All evidence, original command
terms and fills must match it. A PAPER subject cannot match, even when the account
UUID is identical. Policy issue/expiry clocks must be aware, ordered and no more
than one day apart. The caller supplies positive capital, per-order and daily BUY
commitment limits; there are no default capital allocations or permissions.

The candidate can describe whether a simulated BUY fits these limits. Its actual
spendable amount is always zero, order authority always NONE, live transport
always false, and native settlement always NOT_PROVEN. A user-supplied policy,
hash, native-looking record or boolean cannot change these constants. The existing
funding assessor rejects NATIVE evidence until actual settlement and reservation
semantics have been separately qualified. Candidate eligibility is never a
production grant, provider guarantee or live readiness certificate.

## Commitments, partial fills and uncertainty

Use durable-shaped original BUY command keys, whole-share quantity and fixed
positive limit terms. A bounded list of exact native-shaped fill identities
contains Decimal quantity and price, execution time and the exact subject.
Duplicate identical fills count once; changed payloads or a reused fill identity
on another command refuse. Quantity cannot exceed the original command and price
cannot exceed its limit. Corrections/busts are not inferred by this policy
candidate and remain the accounting owner's separate concern.

Each command contributes actual fill cost on the policy's UTC trading date plus
its remaining whole/fractional quantity times the original limit. OPEN and UNKNOWN
outcomes both retain that full remaining reservation. A caller's canceled/expired
label is insufficient evidence for releasing uncertain money, so this candidate
has no terminal-unfilled release path. A fully filled command has zero remaining
reservation. Positive terminal release and the exchange-calendar day boundary
remain separate required production integration decisions.

For a new BUY, compare its full worst-case principal with the per-order limit,
the simulated funding assessment, remaining capital after current long position
value and existing reservations, and the daily limit after actual fills plus
remaining commitments. Repeating an already-known identical command contributes
no second reservation or daily charge; changed original terms refuse. Existing
committed orders already over a limit defer even a duplicate request. Reserves in
funding evidence must cover the command-derived reservations; unexplained extra
reserves remain conservatively reserved. Existing short value, margin, negative
positions, stale/future observations and mismatched policy clocks defer. Exact
fractions implement sums/products so ambient Decimal precision cannot loosen a
limit. Bound list sizes and numeric encodings before arithmetic.

This is BUY-only restriction preparation. It does not select securities, decide
strategy exits, liquidate corporate-action receipts, value a received security,
interpret broker action terms, authorize SELLs or feed broker state into Wealth
Core/Sentinel. Unpriced corporate-action positions cannot be declared worth zero
to fit the capital limit: the supplied position valuation must explicitly cover
all held securities, otherwise the assessment defers.

## Qualification and deferred acceptance

Offline tests exercise exact subjects/origins, policy lifetime, stale evidence,
margin/short refusals, capital/order/daily bounds, missing settlement, reserves,
partial fills, UNKNOWN outcomes, duplicate/recovered commands, changed fill
identities, fractional fills, Decimal-context independence and authority constants.
Guard-removal falsifiers must demonstrate behavioral failure when the subject or
capital boundary is bypassed. No test calls the broker or changes current PAPER
permissions. Actual API access, native settlement/completeness, reviewed durable
live authority and limited-capital activation remain unproven.

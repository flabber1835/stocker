# P01 CELG cash, BMY shares and tradeable CVR

Design recorded before new code, 2026-11-02. The candidate now includes typed
facts, a source-only successor renderer, a closed hosted synthetic component,
independent right-flow accounting and an unexecuted hosted qualifier. No future P01 checkpoint
has been selected for this action, no financial input is admitted and no
financial job is dispatched. Own438 remains the separately selected financial
authority until another actual checkpoint is independently admitted.

## Retained evidence and clocks

The retained CELG [completion 8-K, Items 2.01 and 3.01](https://www.sec.gov/Archives/edgar/data/816284/000110465919065939/tm1923405d1_8k.htm)
and [BMY completion 8-K](https://www.sec.gov/Archives/edgar/data/14272/000114036119021048/form8k.htm)
state consideration of $50 cash, one BMY common share and one tradeable new
contingent value right for each eligible CELG common share. Completion was
November 20, 2019; CELG suspension was requested before the November 21 market
opening. Preserve November 20 trading. The new right's primary symbol BMYRT
is distinct from older Celgene rights CELGZ/CELGRT. The conditional $9 possible
payout is not merger cash and is not anticipated.

Retained authenticated Alpaca raw SIP daily response
`fbbd4ee52eadf5e8498c2ab3135b9b368b35a5f9354941a06307468b96e24769`
contains provider symbol BMY.RT on November 21 with raw open 2.30 and raw
close 2.25. Its compressed source hash is
`17358d350e627caa2eda430fbad850a4f13e68f6db689428bcb270ae876aa455`.
Any future financial adapter must authenticate those privately retained bytes and the exact date, raw
adjustment/SIP/as-of query, legal-symbol/provider-symbol mapping and unique
quote before use. It does not requery the provider. BMY opening and closing
prices in a financial continuation must come from that continuation's actual
source-bound canonical publication; the side quote does not replace them.

Frozen identities are CELG `11651249425833422` and BMY
`578964201416671255`, issuer `SEC_CIK:14272` for delivered BMY. The retained
evidence does not provide a permanent canonical SID for the new right. Do not
invent one or add the right to alpha-eligible metadata. A typed entitlement
identity records issuer CIK, the 2019 acquisition-contract source, legal symbol
BMYRT and provider symbol BMY.RT. A future ledger may carry `security_id=None`
only with that complete validated identity in its typed detail.

## Three economic legs, two valuation domains

Let `q` be exact aggregate CELG shares across source episodes, `Q` the canonical
holder-level BMY delivery, `R` the right entitlement, `P` actual BMY event raw
open, and `O=2.30` the source-bound right raw open. Legal cash is `50*q`.
The selected scope requires `R=q` to be integral. Fractional rights have no
admitted settlement rule and refuse; no truncation or assumed cash in lieu.
The existing canonical BMY holder allocation remains authoritative and must
be checked for exact quantity conservation and representability before any
mutation. Unsupported allocations refuse.

Gross opening package value is `50*q + Q*P + R*O`, before right-sale fees.
Continuing BMY references use
`raw_multiplier = q*P / gross_package`. Signal entry and peak use that
multiplier times the independently authenticated BMY/CELG signal-to-raw basis
ratio. Slots, age, review status and existing pending exits continue. The right
is received and liquidated using the existing involuntary-child-at-open policy
and canonical `exit_proceeds`/`traded_cash` fee primitive. Its gross proceeds,
10-basis-point fee and net cash are separate ledger facts. Legal merger cash
remains 50 per CELG; 52.30 is never written as a merger cash term.

The leadership sensor uses the immutable closing entitlement value
`50 + BMY_raw_close + 2.25`, transformed by its owned source basis. It does not
read the liquidation result, fees, held quantity or realized exposure. Changing
right-sale costs must not change that sensor. Opening valuation cannot use
the right's close, and the sensor cannot use the right's open.

## Canonical capability boundary and selected source successor

The old single-delivered-security `TerminalTerms` and its reference helper do
not represent this package. Canonical `EventType` has no merger-right receipt
or liquidation values. `Ledger.from_dict` decodes every event through
`EventType(...)`; the existing spin-off evaluator requires reviewed child
identity/opening bars and rebases its surviving parent. Reusing
`SPINOFF_RECEIPT`/`SPINOFF_LIQUIDATION` would falsely label this legal event and
would not establish reporting/accounting support. That option is rejected.

The selected future implementation is an explicit research source successor:
retain every old515 physical source byte and source manifest; build a separate
successor containing typed multi-leg action terms and
`MERGER_RIGHT_RECEIPT`/`MERGER_RIGHT_LIQUIDATION` event types. Its canonical
ledger parser, report decoder, share-flow reconstruction and independent
accounting review must validate the right's typed identity, exact receipt/sale
quantity, opening quote, gross proceeds, fees, net cash and zero residual
right position. Merely adding enum strings is insufficient. Reuse the actual
canonical Ledger.post, holder entitlement/allocation, conversion continuation,
share precision and traded-cash primitives. Do not introduce another book or
rewrite historical entries. This is a declared new action capability, not a
price repair or a claim of unchanged financial source semantics.

The successor must bind an actual admitted own P01 predecessor before the first
affected session. Source-successor and input-adoption events, original input
archive, full financial/correlation journal prefixes, original checkpoint gzip,
recovered tails and all original source evidence must survive. Qualification
state never supplies the predecessor. Its synthetic origin cannot authorize a
financial replay. Do not bind an unknown future CELG checkpoint to own438.

## Required hosted qualification before integration

First qualify the component on explicitly synthetic states using the exact
canonical primitives in the successor. Include held and multiple-source
episodes, unheld and leadership-only cases, once-only repetition, pending
orders, separate signal bases, fees/cash/quantity/entry/peak assertions, missing
or wrong quote/date/legal identity, ambiguous quote, fractional rights,
nonrepresentable BMY allocation and late component failure before mutation.
Show that removing each new guard admits its falsifier. Full actual ledger
roundtrip, restart, share-flow and accounting reconstruction must pass with
the new event types; old event bytes must roundtrip unchanged. Compare the
independent closing sensor with hand-derived exact values, including a cost
change that leaves the sensor unchanged.

Only then may a source-bound hosted qualification use P01's actual next admitted
checkpoint and unmodified source quotes/windows to reproduce the original
refusal and compare the complete package. No unsupported right is skipped.
All ordinary stopped-worker/resource/crypto/prefix/accounting gates apply.
The present pure facts/math preparation is not that qualification and does not
provide a runnable financial integration or performance result.

## Component implementation decision, 2026-11-02

The first successor adds a versioned `MergerRightTerms` subclass for the complete
CELG package. Its ordinary cash-and-stock kind retains legal cash 50 and ratio
one; the new mandatory schema, right identity and source-quote fields distinguish
the additional right. It never encodes the right as an increased cash term.
Legacy terminal records retain their exact original shape and parser path.
The ledger gains the two explicit merger-right event types and strict per-event
and complete receipt/liquidation-pair validation. A right has no invented SID:
`security_id=None` is accepted only with the complete typed legal identity.

Use the existing canonical holder allocation and conversion operation on one
detached preflight copy of the caller's canonical book and ledger. The existing
conversion carries slots, pending-exit transformation results, age and references;
only its reference-scale dispatch recognizes the additional gross right value.
Validate exact delivered allocations, all right legs, canonical sale funding,
complete ledger roundtrip and unchanged original ledger prefix before committing
the prepared state and ledger to that same caller. A late component failure
therefore cannot partially mutate the caller. This copy is transaction-local;
there is no second persisted book or alternative strategy transition.

The source renderer verifies all515 predecessor source hashes and appends narrow
dispatch extensions to terminal handling, ledger decoding and leadership terminal
values, plus one new capability module. It writes a disjoint source successor
and retains both complete manifests; it never edits the frozen tree. Reports
carry a distinct merger-right section, with gross receipt, liquidation, fees,
net cash and zero residual units. The existing final-report stock sort never
receives a null-SID right. Independent accounting first reconstructs this separate
typed right flow, then invokes the unchanged ordinary cash/share reconciliation.

The synthetic leadership extension reads only prior owned basis, the synthetic delivered BMY
closing bar and the separately typed synthetic right close. A future financial
extension requires authenticated market quotes. It does not read the liquidation
events, holdings, fees or sale result. A source-only renderer and pure/stub tests
can be prepared locally; actual canonical primitives execute only in a hosted
synthetic component qualifier. No source bridge, input adoption, financial worker
or actual-predecessor receipt is selected until the future own P01 boundary and
component proofs have been independently admitted.

Legal completion on November20 and the first retained tradable right quote on
November21 are distinct clocks. The preparation's `economic_session=2019-11-21`
is only a candidate first-tradable component clock. It does not authorize moving
the native November20 action or using a November21 quote in a November20 decision
or valuation. The initial component source is restricted to hosted synthetic
qualification at the November21 open. It contains no financial overlay that
removes the November20 placeholder. Actual financial use requires separate
source-backed recognition-clock admission and the then-actual own pre-event
roles. If legal recognition requires a November20 right before an admitted
November20 mark exists, that unpriced claim must remain unresolved and refuse;
there is no one-day omission, zero mark or backdated tradability assumption.

The subsequent retained primary clock review strengthens that candidate daily
market boundary. The [issuer's filed completion release](https://www.sec.gov/Archives/edgar/data/14272/000114036119021048/ex99_1.htm)
identifies CELG's cessation at the November20 trading close and the newly issued
BMY shares/right beginning trading November21. [Nasdaq ECA2019-65](https://nasdaqtrader.com/TraderNews.aspx?id=ECA2019-65)
corroborates the last trading and suspension sessions. This supports investigating
the November21 market-session component without asserting a statutory legal
effective hour. Terms and entitlement identity may be prepared preopen; the
first opening print is usable only in its opening execution/valuation domain,
and its closing print only in the postclose sensor domain. The [OCC notice](https://infomemo.theocc.com/infomemos?number=46027)
corroborates the November21 adjustment and reports new-right CUSIP110122157;
that identifier is not an invented canonical SID. Its OCC/NSCC allocation is
not a portfolio basis or market valuation rule and is not used.

## Single hosted synthetic qualification sequence

The component-only workflow uses one disposable Ubuntu24.04 VM and one offline
2CPU/8GiB/no-swap/read-only-root worker. After checkout and locked metadata
dependencies, the separately qualified ephemeral-runner capacity helper runs
before encrypted input/runtime staging. Its actual source/run-bound PREPARED
receipt is required; the ordinary 12GiB initial and 10GiB preworker disk gates
and 10GiB available-memory gate remain. No local/shared cleanup is added.

The published synthetic job contains no actual Alpaca response or capture
receipt. Every parent/BMY/right price in that matrix is an explicit synthetic
fixture, including right open2.30 and close2.25. The component's typed quote
carries `SYNTHETIC_COMPONENT_FIXTURE` authority and no provider-response hash,
feed claim or observed timestamp. Retained actual quote hashes may be referenced
as private future-admission evidence; that evidence is neither transferred nor
authenticated by this job. The raw response and capture receipt remain private.

Before fetching the source parent or launching a worker, execute an actual
marker encryption/authentication/decryption under the distinct
`campaign-p01-celg-synthetic-component` export scope. Reuse own438 only to
authenticate the immutable source binding and variant parameters. Build its
original515 physical files unchanged, verify the complete binding, then render
the disjoint516-file successor. Its canonical financial identity subset grows
from223 to224 files. Both complete maps and the exact three original-module
prefixes must be verified before any successor code import.

The synthetic worker receives only the successor source, frozen inputs, driver
and disjoint output. It receives no `/old` book mount. All positions and prices
are expressly toy fixtures. The original own438 checkpoint is never restored by this
worker, and no source bridge, input adoption or finance worker is present.

Budget900seconds for the worker,35minutes for orchestration and65minutes for
the job. Bound the capacity step to5minutes and staging to8minutes, retaining
headroom for checkout, dependencies and encrypted upload. Write the positive canonical
case/ledger/state/report/accounting proof before proceeding through the ten
negative cases, and write each completed case independently. Durable public
phase and actual stop receipts contain only allowlisted nonfinancial metadata.
After a proven stop, encrypt all complete/partial private proofs with the
existing separate key and seven-day Actions retention. An unknown worker stop
never authorizes a mutable snapshot. Parent/export/source failures remain
explicit and cannot trigger a blind rerun. Root alone publishes the request.

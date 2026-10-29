# Bounded Alpaca/OpenFIGI controller fit

## Frozen design before numerical fitting

The owner authorized proceeding after explicitly acknowledging that parameter
optimization is historical fitting. This is one finite parameter family of the
existing Owned55 controller, not another return forecaster or a production change.
Use research branch `codex/capital-risk-research` and PR 542 only. Verified main
base: `bbcb728a972f483c9f76f2b0db2599b2134ab1bb`; initial research head:
`6bace0dc09efc8ea462df26854e82fae04ef3e9d`.

Keep canonical Wealth Core selection, admissions, holdings, stops, reviews,
cooldowns, native Sentinel and champion recovery unchanged. Compute that canonical
history once. The one-way architecture permits the final Owned55 parameter
variants to consume that same history without changing Core or parent decisions.
Each variant still owns its complete formation/controller and funded-account state.

Exhaust all 108 combinations:

| Existing Owned55 parameter | Registered values |
|---|---|
| entry damaged breadth | 0.50, 0.63, 0.75, 0.88 |
| entry confirmation closes | 1, 3, 5 |
| recovery confirmation closes | 3, 5, 8 |
| active exposure ceiling | 0.25, 0.55, 0.75 |

The existing 0.88/5/8/0.55 setting is included. All other predicates stay fixed.
These are deliberately limited numerical bounds, not a claim that this is the
best architecture or that continuous global optimality has been established.
New parameters have distinct private research identities. Never override a
production module, relax a source guard or relabel a checkpoint.

## Sources and history

Use only Alpaca bars/actions and anonymous free OpenFIGI mapping. Freeze the
whole retained 2026-10-03 Alpaca feed roster before fetching new prices, then
recheck exact asset ID/ticker/catalog identity and the production mapping contract.
Do not substitute the old 56-stock sample. Exclude unsupported/currently absent
identities explicitly, without replacing them based on performance.

Acquire 2023-04-03 through 2026-10-27 daily raw/split stock prices, and raw/all
SPY/BIL references, plus the corporate-action history needed to interpret them.
Use the canonical feature, eligibility, action and identity rules. Do not infer
split terms or use total-return stock prices for signals. Unsupported economic
actions or an unidentifiable owned instrument must refuse, preserve evidence and
prevent an admitted performance result rather than become a skipped trade.

The retained/current cohort and current metadata are survivor-conditioned.
Revised historical provider bars are not publication-time archives. Report these
as known-history limitations, not unseen validation. Current mappings do not
establish historical membership. No paid or additional vendor is introduced.

Each book has its own fresh 299-feature/126-formation history before the first
measured session, 2025-01-02. Train/select on 2025 target sessions only. The
subsequent 2026-01-02..2026-10-27 period is a locked chronological diagnostic,
not a fresh holdout. Selection code cannot consume its candidate return metrics.
Baseline and candidate use the same capital (50,000), timing and measurement anchor.

## Account and objective

Use a separately identified persistent-quantity research account: whole-share
BUYs, ordered cash funding, actual raw marking, exact action entitlements and
explicit fees. The historical fill model is idealized next-published-raw-open
execution. It is not production's 09:31 protected LIMIT/DAY order outcome.
Never compare its level to a differently modeled legacy baseline to claim gain.
The baseline must be reproduced under this same source/execution/account contract
before candidate scores are admitted. Stock/account fees must not duplicate
shadow rotation fees. BIL treatment must be explicit and independently checked.

The selected first account reference is the existing qualified persistent-stock
prototype with its declared defensive cash-factor proxy, now fed only by Alpaca
SPY/BIL adjusted references. Cash compounds by same-publication BIL all-adjusted
open/previous-close and close/open factors, with no second BIL dividend payment
or separate BIL shares. This is a modeled defensive sleeve, not bank cash or the
production ETF/order ledger. Retain its exact-fraction accounting and documented
rounding bound. The old date-bound 2008 runtime remains unchanged: a new versioned
adapter owns the 2025 origin and must separately qualify its initial projection.
It starts with 50,000 immediately before the first funded 2025-01-02 open, uses
the last formation close's known intent, skips any unfunded preceding overnight
return, and includes first-day trades/costs in reported performance. The baseline
and every variant use that same anchor. A variant owns its own exposure/account
state throughout formation and training. This model cannot be described as
reproducing protected PAPER fills.

Fit the growth/drawdown frontier on 2025. Report maximum attainable net growth
within the finite class at drawdown budgets equal to 0.50, 0.75 and 1.00 times
the matched baseline's training drawdown. Keep at most three distinct frontier
points, plus any strict joint improvement selected by maximum growth, with
deterministic ties by less turnover then profile ID. Lock the selection before
calculating selected 2026 returns. Preserve all 108 training outcomes, including
ties, no-treatment cases and refusals. A no-treatment setting cannot be evidence
of efficacy. Do not require improvement in every subperiod to report full-period
joint improvement; report stability separately.

## Bounded execution

Market-only acquisition can run privately on the existing host, reading only the
two named provider keys from the exact existing provider configuration. It may
call only asset catalog, market bars/actions and free mapping. It starts no
container, replay, database or service. Gzip raw replies; retain hashes, request
receipts and complete pagination. Bound request bytes, disk, elapsed time and
retries. No secrets in output.

Resource amendment before capture: observed host free space is only about
700 MB. Do not retain a broad plaintext capture on that disk. The collector may
instead send length-bounded binary response frames to a private Windows parent.
That parent streams an AES-GCM sealed archive into at most one 16 MiB temporary
ciphertext chunk, uploads each chunk to the existing approved encrypted research
release, verifies the server's exact size/SHA256, then removes only that exact
new spool file. No recursive or protected-file cleanup. Alpaca keys remain only
in the collector process and are never part of frames, payloads or cloud secrets.
The encryption key remains separately DPAPI-protected locally and in the already
approved research secret. There is no unencrypted financial cloud payload.

The stream's final manifest is necessarily last. A dedicated receiver must first
authenticate the complete ciphertext/GCM, then check every archive member and
the final inventory before exposing any inputs to a worker. The old first-
manifest extractor is not silently relaxed. Incomplete captures retain explicit
failed metadata and can never be admitted as complete financial inputs.

All canonical Core/account execution is on isolated GitHub-hosted compute. Source
and inputs are read only, outputs disjoint, network disabled in the financial
worker. Existing approved research encryption/key separation applies; no plaintext
market or financial payloads in public logs/artifacts. No local financial replay.

Before a full financial run, qualify actual input/source identity and feature
equivalence, then time the first five real formation transitions as a retained
prefix of this baseline. Use that measurement to bound the remaining runtime;
do not restart it as a new warmup. The initial processing ceiling is 3,600 seconds
within a 90-minute hosted job. Do not launch a knowingly over-budget full replay.
Stop/export receipts must be written inside the driver's finally block, including
on timeout. UNKNOWN workers never produce financial snapshots.

Reuse completed proofs where their source/model scope still matches. New work
needs only relevant input, baseline, accounting and continuation gates, not old
backup/restore campaigns. Preserve all prefixes and exact next-session adjacency.

PAPER, broker financial endpoints, production databases, main, deployment, shared
Docker/WSL/services/pagefile and protected historical evidence remain untouched.
No merge, promotion, PR 541 activity, new forecast fit or automatic expansion to
another rule family is part of this protocol.

## Input adapter and staged admission

The hosted input adapter owns a distinct immutable research publication, not a
production database or GO receipt. It verifies captured raw response hashes and
pagination before constructing packed, date-indexed price arrays. Every date's
eligible tail is determined from information no later than that date using the
existing `admissible_history` price/action rules. No future action removes a
security from an earlier universe. Current asset identities and mappings remain
an explicitly retrospective cohort limitation.

Reuse canonical `alpaca_bar`, `_vendor`, `feature`, `WindowFeatures`, `Formation`
and `advance_session`. Qualify the packed current-window feature assembly against
the uncached canonical `compile_rows` on actual broad inputs before admitting
financial transitions, and at subsequent boundary samples. Each publication
commits its actual date, source manifest, protected historical economics and
feature material. Formation uses its canonical same-version proof; measured
sessions use strictly increasing current-window versions. No financial kernel,
config guard or serialized source identity is patched.

Structural events without supported terms reset an unowned candidate's history
only from their dated occurrence onward. An affected protected dependency, an
unknown economic date, or an unavailable owned price refuses with its exact
predecessor. Cash dividends and explicit forward/reverse splits use the canonical
normalization and settlement model. This first adapter does not manufacture
merger/spinoff proceeds or silently reinterpret unsupported terms. BIL split-only
corroboration is a separately bound market-only supplement before admission.

The first hosted stage authenticates inputs/runtime, qualifies the new input
adapter, and advances the canonical baseline's first five actual formation
transitions. It preserves its warmup origin, checkpoints, append-only journals
and exact prefix commitments. A measured throughput refusal is a saved incomplete
baseline, not an optimization result. Only a complete admitted Core trace may
feed the 108 private controller/account trajectories. Their selection and
accounting qualification remain separate gates; an input/timing success alone
does not mean a performance candidate was evaluated.

The new canonical worker has its own exact selector and resource contract:
8 GiB memory with no swap, two CPUs, 64 PIDs, read-only root/source/inputs,
no network, no added capabilities, no new privileges and no credential
environment. It does not broaden the older two-GiB worker selectors. It records
and fsyncs the exact stopped identity inside `finally` before timeout propagation.
Full stopped evidence and a separate bounded encrypted summary are exported;
the small local disk must not force downloading a large full archive. A separate
stopped-evidence review is still required before numerical interpretation.

The stopped-baseline reviewer is a separate offline process with the financial
output mounted read only. It checks append-only journal framing/chains, every
retained canonical checkpoint and controller state, source price preimages,
ledger cash/share/claim movements and raw close marking. It replays only the
small registered controller leaves from recorded source observations; it does
not create another Core or advance an account. This gate may admit a preserved
partial prefix for continuation while explicitly refusing a complete-run or
performance claim. A complete reviewed Core input trace still is not a funded
account result.

## Market-capture TLS recovery, before any financial origin

The first collector stopped after 1,321 replies on a TLS read error not covered
by its transport retries. Its 188,579,876-byte ciphertext is complete/GCM-sealed
and server-hash verified, but its manifest is FAILED and its capture INCOMPLETE.
Never relabel it COMPLETE. No financial job began.

A separate price-suffix collector may reuse only that exact authenticated
prefix. It re-requests the last completed page and requires its exact raw
SHA256/length before learning the next page token; a changed predecessor refuses.
That corroboration is explicitly marked and cannot count as a second price page.
It then acquires only remaining frozen-query pages/groups and benchmark replies,
with bounded TLS retries and 900 seconds of additional acquisition time. Completed
classification/actions/raw-price requests are not repeated. The original source,
failure, receipts, payload and encryption inventory stay immutable.

The receiver has a separately selected failed-prefix scope; its ordinary
COMPLETE-only extractor remains strict by default. Complete financial input
admission requires both full GCM/inventories, the exact successor binding and
predecessor corroboration, complete combined pagination/query-plan coverage and
all source price/action checks. A composite dataset digest binds both captures,
the BIL supplement, the roster and unchanged protocol. It does not claim atomic
provider publication or publication-time history.

The first suffix attempt correctly refused a changed wire SHA with equal byte
length. Before any relaxation, independently authenticate both complete encrypted
archives and inventories and compare the actual entire JSON values, preserving
array order and scalar types. A two-pass streaming verifier first authenticates
without parsing, then extracts only the required preimage into bounded memory;
it creates no broad local plaintext archive. Only a proven JSON object-order
difference may support a separately documented successor rule. Any changed
number, field, list order or continuation token still refuses. The original
byte-exact refusal remains evidence and is never relabelled as a pass.

Actual comparison passed: the two full authenticated preimages have identical
typed JSON values, ordered arrays and next-page token; only object serialization
order changed. Capture 002 remains a failed byte-exact attempt and serves only
as an authenticated corroboration witness. The next suffix uses that already
proved cursor, rather than repeatedly requesting an order-unstable JSON page.
Hosted admission must independently recompute the equality from both ciphertexts
and bind the witness into the composite dataset before any financial origin.
The second attempt's literal transport/manifest status is `INCOMPLETE` (exit 1),
not `FAILED`; preserve those exact bytes and the underlying refusal. Its explicit
witness extractor scope requires that literal status and grants no financial
admission by itself. The first TLS prefix remains literally `FAILED`.

## Scoped unresolved action inputs

The first two hosted attempts stopped during input interpretation, before any
financial origin or journal record. Their exact evidence is retained. The
research adapter must carry the production parser's unsupported split and
pending-cash facts instead of treating every unrelated bad record as a global
input-load exception. Equal duplicate split facts are one event, not multiplied
entitlements. Unsupported dated structural events retain the existing causal
unowned-history reset and protected-dependency refusal.

An unresolved cash distribution does not change split-only signal history.
Retain its exact source record and reason. If its ex-date is a trustworthy XNYS
session, refuse when a held dependency spans that event; never invent its rate.
If timing itself is invalid/unknown, refuse any held or queued opening dependency
on that instrument. This is a whole-run refusal, not a silent alternative stock
selection or a shifted dividend date. Unrelated, unowned cash records cannot
create or remove cash. These input limits and all blocked cases remain reportable.

The owner requested checks only when they add value. Reuse the completed unchanged
controller component proof. Run only changed input-behavior tests for these fixes;
retain source/input admission and actual accounting checks that prevent invalid
performance conclusions. Do not repeat unchanged audit campaigns.

## Funded account calculation and exact work sharing

The new 2025 adapter reuses the existing qualified `holding_account` operations
and persistent-stock fill/factor routines; it never calls the old 2008-bound
`Runtime.advance`. At the first funded open it projects the last formation
close's known Core holdings and pending orders onto its own 50,000, excludes
already queued exits and includes first-day whole-share fills/fees. Current
close prices cannot size that morning's trades. Subsequent unchanged exposure
keeps quantities; exposure changes resize from the prior close's canonical Core
weights. New Core entries retain unpooled NAV/20 funding. Sells precede buys,
cash clips positive buys and no short/leverage is introduced.

Each registered controller owns its formation state and full causal target
sequence. Identical training target sequences imply identical funded economic
inputs under this deterministic model. They may share one immutable calculation,
with separate profile/lineage wrappers and an exact equality certificate. This
shares computation only: each variant retains its own 50,000 and no capital or
cash is pooled. Preserve all 108 score rows and ties. Internal controller states
can differ and remain separate for later continuation. Only target sequences
through the training cutoff may define these groups; no 2026 metric or target
can influence training selection. Do not merge paths merely because their final
NAVs happen to agree.

## Measured input-assembly continuation

Baseline 003 completed and independently reviewed its first five formation closes
through 2024-07-10, all three retained checkpoints and the complete journal with
zero tails. Measured ordinary transitions took about 28 seconds; the original
whole-run projection exceeded seven hours. Do not restart that origin or extend
the slow path unchanged.

Optimize storage extraction only: obtain paired raw/split rows and feature
vectors by packed array slices instead of millions of repeated per-row NumPy
lookups. The canonical admission and feature functions remain unchanged. Before
advancing the exact saved suffix, compare complete old/new `PublishedSession`
preimages under the same retained state/date/version, and measure the faster
path. Preserve the original comparison and checkpoint proofs; do not repeat
unchanged component campaigns or monthly full-window compiler comparisons.

The continuation preserves the original canonical FormationPlan, origin source
commitment, state, all old checkpoint files and journal prefix. A separate
execution-source commitment records the changed research orchestration. Canonical
Core/controller source and frozen data must be byte-identical; no strategy state
or historical identity is relabelled. Current-source canonical restore precedes
the next adjacent session. Any uncommitted tail is preserved separately before
recovery and cannot become a skipped session or duplicate committed row.

Use measured bounded suffix batches (at most 300 transitions and 3,600 seconds
per worker) to finish the same registered date axis. A batch stop is an explicit
partial prefix, not a complete trial or performance result. Preserve and resume
its own exact state. This scheduling amendment changes no dates, capital, grid,
selection rule, provider prices, action facts or financial transition.

## Sparse factual identity amendment: PNM to TXNM

The exact suffix stopped before August 5, 2024 because its action interpreter
reset TXNM's history for a name change. Its August 2 predecessor has 22 reviewed
formation closes, five immutable checkpoints and zero journal tails. TXNM is a
protected controller reference here, not a held or pending Core position.

The frozen Alpaca record identifies PNM to TXNM on August 5 with equal old/new
CUSIPs. The issuer's [8-K, Item 8.01](https://www.sec.gov/Archives/edgar/data/1108426/000110842624000082/pnm-20240805.htm)
and [Exhibit 99.1](https://www.sec.gov/Archives/edgar/data/1108426/000110842624000082/txnm08052024ex991.htm)
establish unchanged common-stock identity and outstanding shareholder interests.
The change of authorized share ceiling is not a split of outstanding holdings.
The complete frozen provider archive was authenticated before extracting this
record; no new price acquisition or inferred adjustment is needed.

Admit one explicit research input-interpretation amendment, not a general rename
exemption or a production parser change. Its hash-only descriptor binds this
exact action-record digest, raw-response digest, original capture/protocol,
permanent-ID digest and the exact own August 2 file/outer/inner/state/input/source
and journal predecessor. The actual record must have equal valid CUSIPs, distinct
old/new symbols, the bound date, a unique current target listing and no conflicting
structural event. All other unsupported events retain their ordinary refusal.
Remove only this record's dated history reset. Never change any provider row,
security ID, share, price, cash, controller state or prior committed frame.

Preserve the original dataset and FormationPlan commitments. A separate input
interpretation digest binds the amendment into every new publication. The scalar
and packed assemblers compare against this same explicitly amended normalized
basis; that equality proves storage equivalence, not factual correctness of the
amendment. Factual admission is separate and records the issuer evidence and
exact predecessor proof. Current-source canonical restore, all old checkpoints,
all journal prefixes and exact next-session adjacency remain required. Later
suffixes must prove that this bound anchor remains in their own retained lineage.
No warmup restart, arbitrary action suppression or production installation is
authorized. Keep the initial refusal and negative findings intact.

## Frozen name-fact registry after the second observed identity refusal

The next reviewed suffix passed the TXNM event and stopped at UCBI to UCB on
August 6. Its August 5 state has 23 formation closes and no measured returns.
The issuer's [July 26 8-K](https://www.sec.gov/Archives/edgar/data/857855/000085785524000051/ucbi-20240726.htm)
and [current investor facts](https://ir.ucbi.com/resources/investor-faqs?mobile=1)
corroborate continued common-stock listing under the new symbol and unchanged
CUSIP. This is the same source-compatibility class as the preceding refusal.

Supersede the single-event-only research scope with a frozen, hash-enumerated
registry of future non-economic name facts from the already authenticated Alpaca
capture. Freeze it before any measured-return comparison. This changes research
source interpretation, never production or numerical controller rules. Admit
only well-formed `name_changes` with equal valid old/new CUSIPs, a unique current
listing and permanent ID, exact raw-response/record commitments, an XNYS process
date after the new exact August 5 anchor, and no conflicting structural event.
Malformed, colliding or conflicting facts keep their original reset/refusal.
The previously issuer-verified TXNM descriptor is retained as an explicit legacy
component; no other past reset may be removed retrospectively.

The frozen Alpaca event is the primary market-data evidence for registry members,
using its [documented fields](https://docs.alpaca.markets/us/v1.1/reference/corporateactions-1).
This is not a claim that every member received separate issuer/SEC research.
Preserve that distinction, the accepted/rejected metadata inventory and provider
truth limitations in the result. No price continuity may manufacture identity,
and no future performance or holdings select registry membership. The ordinary
raw/split corroboration, protected-history, canonical transition and independent
accounting checks remain in force after exact reset interpretation.

Bind the registry and every legacy component into the new publication's input
interpretation digest. Preserve the exact own August 5 checkpoint, input, source,
all historical prefixes and earlier interpretation commitments. The source
extension defines the research baseline used by all 108 variants; its results
cannot certify the installed PAPER source parser. This bounded source capability
avoids one workflow failure per ticker alias while retaining refusals for actual
economic conversions and ambiguous identities.

## Split predecessor at the rolling-window boundary

The reviewed August 14 prefix has 30 formation closes. On August 15 its next
300-session window starts June 7, 2023, exactly on GNLN's recorded reverse split.
The unmodified canonical admission function rejects that 300-row input as
`split_predecessor_missing`. The authenticated raw/split capture contains June 6;
passing those same actual 301 paired observations and recorded split terms to
the same canonical function succeeds. No financial transition was used for this
diagnosis and no ratio, price or date was inferred.

For source admission only, supply the single adjacent captured predecessor when
the first requested window session has a recorded split and both predecessor
price domains actually exist. Run the ordinary canonical admission function on
that context and clip the returned admission start to the requested window.
Keep the feature/strategy window exactly 300 sessions. A missing predecessor,
conflicting adjustment, gap or unsupported action retains the ordinary refusal.
This source capability changes neither stock selection rules nor split economics.

Bind the explicit context-policy identifier into future input interpretations;
retain every old publication and the exact own August 14 predecessor. For the
scalar/packed comparison use this same qualified admission contract on both
sides, while retaining the scalar reference's feature-vector/publication assembly.
That comparison establishes storage equivalence. The actual 300/301 source
comparison and focused missing/conflicting-predecessor tests establish the new
admission boundary separately. This is research source interpretation, with no
PAPER parser installation or production certification.

## Funded fitting execution and evidence

Consume only an authenticated stopped canonical trace with an actual independent
review covering the entire period being scored. Training needs every 2025 close;
the later diagnostic needs the complete registered 2026 axis. Verify defensive
and SPY inputs independently against the frozen benchmark response preimages.
Do not derive returns by scaling old scalar-book returns. Use the persistent
quantity operations, actual whole-share fills, cash clipping, explicit stock
fees and recorded claims. Each of the 108 profiles owns its own 50,000 origin.

Keep each Core opening's original signal/slot identity, including carried orders.
Verify its source NAV/20 budget against that original source close. The funded
account sizes its next-open allocation from the latest available prior close;
it cannot use the executing session's close. Carried origin identity and current
allocation-decision date are distinct. An unsupported operation remains a refusal.

Four hosted component cases cover the new funded-open origin, fees, separate
overnight/intraday defensive factors and exact serialized continuation. Existing
financial primitives retain their earlier qualification; no new Core decision
engine is introduced. Local checks use hand-valued geometry only.

Write compressed event, daily-account and checkpoint-archive journals per profile.
Each close commits only after its complete buffered event set, daily frame and
checkpoint are durable. The archive retains every typed checkpoint and raw-prefix
commitment; the current checkpoint additionally commits the archive prefix.
Resume each exact own checkpoint and preserve old compressed journals, recovered
uncommitted bytes and origin receipts. Never recreate a funded origin, conceal
partial output or use a different profile's checkpoint. A processing bound is an
explicit partial prefix. Unknown worker outcomes cannot produce a financial export.

A separate stopped worker independently recomputes account events, quantities,
cash, claims, raw-open fills, fees, factors, daily NAV, every checkpoint and all
historical journal prefixes. Derive growth and drawdown from that reviewed path.
Retain 108 score rows, including ties and refusals. Lock the preregistered training
selection only after this review, before reading selected 2026 account results.
Continue only the baseline and locked shortlist into 2026 from their own exact
training checkpoints. All stages remain bounded isolated GitHub jobs; no local
account replay, production operation or parameter retuning is implied.

## Stock-merger recipient versus converted security

The next reviewed prefix reaches October 31, 2024 / 85 formation closes. The
November 1 refusal names CLSK, the acquirer in the frozen GRDI stock-merger
record. The issuer's [closing 8-K](https://www.sec.gov/Archives/edgar/data/827876/000119312524248156/d863782d8k.htm)
identifies GRDI common shares as the converted property and CLSK shares as newly
issued consideration. Existing CLSK shares receive no mechanical conversion.
Dilution and market-price changes remain in actual prices. The provider date and
truncated ratio differ from the issuer's terms; retain that discrepancy and do
not use it to settle any acquiree position.

Freeze a separate future-event role registry before measured-return evaluation.
For exact well-formed `stock_mergers` with distinct acquirer/acquiree symbols and
valid distinct CUSIPs, positive finite rate fields, a uniquely bound current
acquirer listing, and no conflicting structural event, remove only the
acquirer's exact reset. Preserve the acquiree reset and every economic-action
refusal. Do not create shares, cash, conversions, prices or broker mappings.
Other merger kinds and malformed or ambiguous records remain unchanged.

Bind the registry to the own October 31 file/inner/state/input/source/journal
anchor and immutable provider response preimages. Retain the earlier name
registry and split-context policy independently. This extends only research
source role interpretation. All ordinary price corroboration, protected-history,
Core financial, checkpoint and prefix checks remain. Registry membership is
metadata-driven; separate issuer research covers the observed CLSK example,
not every future entry. The provider-truth and current-cohort limits remain.

## Factual identity failure and corrected initialization

The original source trial is factually invalid for parameter fitting. A
contaminated identity reached retained path-dependent controller state;
the exact membership and checkpoint proof remain in the private evidence.
Authenticated CLBR responses
include hundreds of observations before Colombier III's August 15, 2025
inception; 258 full raw records in the used July 2024–July 2025 interval match
PEW exactly. The former Colombier II became PEW, whereas current CLBR is
Colombier III. Their current FIGIs and legal issuers differ. See Colombier III's
[inception filing](https://www.sec.gov/Archives/edgar/data/2091024/000121390026089080/ea0301143-10q_colombier3.htm)
and [separate-trading announcement](https://www.sec.gov/Archives/edgar/data/2091024/000121390026034101/ea028302001-8k_colomb3.htm).

The earlier accounting and restore proofs remain valid conditional on their
actual inputs. They do not prove that those inputs describe the right issuer.
Preserve all original trials, checkpoints, journals and capture bytes with an
explicit factual-validity refusal. Do not score that trace or continue its
contaminated state as though the missing identity were merely a buyer role.

The owner's instruction to carry this same study through results includes
necessary research data corrections. A distinct corrected-input trial must
initialize fresh canonical formation; no state is copied, edited or relabelled
from the invalid trial. This is a new dataset/source-policy identity, not an
economic rule change. Keep the 108 settings, dates, capital, costs and selection
protocol unchanged. PAPER remains untouched.

Before that new origin, freeze a metadata-only temporal identity policy. Use
source-record and current FIGI bindings to distinguish true same-issue aliases,
current stale/reused ticker identities, and changed-CUSIP successor securities.
Do not admit a successor's price history before its supported issue boundary.
CLBR III's common-share boundary is March 27, 2026; PEW's successor boundary is
July 16, 2025. Unknown reused-issuer boundaries must quarantine that current ID,
not invent an IPO date. Same-issue duplicate current IDs must not receive two
universe votes. A collision screen is evidence for quarantine, not authority to
merge issuers or synthesize prices. No return, drawdown, holdings or candidate
score determines membership.

Rebuild source facts as initial metadata interpretation, bound to the original
capture and complete policy before formation. Valid same-CUSIP names and
acquirer-only facts retain their exact record/preimage guards. Initial source
facts have no predecessor financial identity; never borrow hard-bound anchors
from the invalid trial. Genuine economic conversions and unsupported terms
retain their ordinary refusals. The corrected current-cohort history still is
not a point-in-time market-universe archive or unseen out-of-sample evidence.

## Bounded funded workflow contract

Use a distinct `alpaca-funded-request.json` trigger, separate from the Core
suffix trigger. Each request binds the actual reviewed Core artifact, encrypted
inventory and required end date; later requests also bind the exact own funded
artifact. A training request cannot start before the complete 2025 source is
independently admitted. The diagnostic request additionally pins the actual
training selection file and complete 2026 source. Continue the same accounts.

The funded worker receives no credentials and only read-only source, market,
Core and predecessor mounts, plus its private writable output. Preserve the
8 GiB / 2 CPU / no-swap / no-network fences. Bound processing to 3,000 seconds
with 120 seconds for closure; the host wait is 3,120 seconds. A separate stopped
review worker has 900 seconds. The entire workflow remains bounded to 90 minutes.
Durable inspections precede exceptions and exports. An unknown reviewer is not
archived; an independently proven stopped financial writer may still be retained.

The model identity includes financial implementation files, the frozen canonical
source closure and runtime image, numerical protocol, dataset and the exact
source prefix through the training cutoff. It excludes the
later diagnostic suffix from the training identity, while admission still checks
the entire supplied source chain. Orchestration/reviewer fixes do not relabel
financial state. Freeze financial implementation before the first funded origin.
Only unchanged component qualifications may be reused on exact continuations.

For event equations reuse the existing independent cash/share/claim checker.
Additionally derive defensive rounding using integer quotient/remainder and
ties-to-even, independently of the financial Decimal calculation. Reconstruct
every prior-close target separately, check complete action/order coverage,
all raw marks, every checkpoint against its actual daily prefix, and every
historical journal commitment. Preserve tails outside the economic path.

An additional funded treatment means an actual positive fill sequence differs
from baseline on the same date, with a positive fill on at least one side.
Avoiding a baseline fill counts; merely changing its diagnostic cause does not.
A changed signal without a differing positive
fill is insufficient. Lock selection only when all 108 accounts have complete
reviewed training paths. Incomplete processing remains a prefix, not a score.
Use the same gross SPY adjusted-open anchor for every comparison; disclose that
SPY excludes stock trading fees, while funded accounts charge 10 basis points.

## Cash-acquisition buyer role

The independently reviewed prefix now contains all 126 formation closes and 37
measured closes through February 26, 2025. The next protected-history refusal
is IBM as the buyer in its HashiCorp acquisition. HashiCorp's
[closing 8-K](https://www.sec.gov/Archives/edgar/data/1720671/000119312525037910/d898526d8k.htm)
identifies HashiCorp shares as the canceled property receiving cash. IBM's
existing shares are not converted by that event. IBM is a controller reference,
not a held or queued Core position at this boundary.

Extend the same exact role-classification contract to well-formed cash mergers:
distinct buyer/target symbols and valid distinct CUSIPs, positive finite cash
rate, exact current buyer ID, dated frozen raw preimage, and no conflicting
buyer structural event. Remove only the buyer's exact reset. Do not settle the
target, grant cash, alter prices or remove its guard. Freeze future metadata
membership without holdings/return selection. Preserve all rejected facts.

Use a new role-registry version bound to this own February 26 checkpoint and
all source/input/journal identities. Embed the previous stock-role registry
unchanged, and revalidate its original October 31 anchor in the retained prefix.
Keep both predecessor identities and old publications. All facts except the
observed issuer-backed case retain the stated provider-evidence limitation.

# Alpaca stock merger continuity for a retained controller witness

Decision: 2026-11-23. The November 23 source publication retained two prior
Median-5 selections as controller witnesses, but did not publish their merger
terms or a usable current-price bridge. Neither identity was a Wealth Core
holding or pending instruction. A missing witness return prevented the next
canonical decision; the dashboard reported the refusal. The action-page hashes
in that publication do not prove the full merger records later returned by a
fresh provider read. No return or plan may be derived from those later records
while reading the older publication.

Alpaca describes stock mergers as delivery of the acquirer's shares and
separates them from name changes. Its corporate-actions endpoint exposes the
two symbols/CUSIPs and rates, but `data_quality=all` can return early incomplete
records and Alpaca makes no guarantee that an action is available promptly.
Its historical-bar `asof` symbol mapping can also become available only the
day *after* a symbol change. The source must use complete acquired action
terms and the retained earlier publication, not infer a conversion from `asof`
bars or a later asset listing. See [mandatory corporate actions](https://docs.alpaca.markets/us/docs/mandatory-corporate-actions),
[corporate actions API](https://docs.alpaca.markets/us/reference/corporateactions-1),
and [market data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).

## Source-bound conversion

The rolling Alpaca/OpenFIGI source will publish a versioned, immutable stock
merger conversion separately from ordinary same-identity name-change bindings
and ordinary listing references. Each conversion binds one prior admitted
permanent identity and provider UUID, the prior published snapshot, one dated
Alpaca `stock_mergers` record and its complete terms digest, the old and new
symbols and distinct CUSIPs, a uniquely classified active successor and its
current provider UUID/permanent identity, and the exchange ratio
`acquirer_rate / acquiree_rate`. Both rates must be finite and positive. The
quotient must have an exact terminating decimal representation accepted by the
existing terminal-terms schema; a repeating quotient remains unavailable
rather than being rounded into a fabricated exchange ratio. The
prior UUID/symbol comes from an authenticated earlier dated publication; the
current UUID/symbol comes from the active classified inventory. Alpaca's asset
projection does not retain CUSIP, so the two CUSIPs are action-record facts,
not an independently verified UUID-to-CUSIP mapping. Duplicate, conflicting,
unmatched, future or incomplete role/term evidence refuses conversion. An
unsupported conversion for an unprotected candidate stays in the existing
per-symbol action quarantine; it does not refuse the whole market snapshot.
If that old identity is protected by the book or controller, the ordinary
missing-input guard still refuses its transition. A
matching ticker, price path or broker position never establishes identity.

The same-symbol old-UUID to new-UUID case and a disappearing acquiree may each
convert into the same successor. The old identity ends; the successor does not
inherit its history or canonical ID. A source-proven successor may use its
actual event-day raw/signal bar as a fresh one-day history, while pre-merger
same-symbol bars stay outside the successor series. An unchanged acquirer
retains its existing history. No synthetic bar, flat return or ratio is used.

The producer retains the exact conversion projection and original terms hash
in a new paired source/reference schema and rechecks it during corroboration.
The normalization and source policy advance together; older published schemas
remain readable as historical evidence but cannot satisfy fresh GO acquisition.
The current strategy's economic-source digest advances with the merger reader;
the previous signed digest remains a historical baseline. Tests that pin the
current digest must identify the reviewed successor and retain their mutation
falsifiers rather than relabeling historical authority.
The reviewed current strategy digest is
`421a1697353ced9bdb0efba82150e900265c8f1bb7e296dbb7f6423b40a6cc81`;
the old local PAPER exception still names
`caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095`.
The merger-conversion origin lookup for a correction skips every same-session
publication, returning to the preceding dated identity source even when the
current same-session tip already uses `/4`. The correction predecessor remains
that exact current tip. Publication and source hashes bind the corrected input;
neither old prices nor old reference rows are edited.

## Late provider evidence at the close

Acquisition may begin at the exact exchange close. Neither that instant nor two
equal corporate-action responses proves that Alpaca has finished publishing
actions. Alpaca documents no action-completeness watermark or guaranteed
creation time. A fixed post-close delay is therefore not a source-finality
proof. The November 23 acquisition began 56 seconds after the close, passed
source validation and published about 13 minutes after the close; its later
missing-anchor refusal does not establish an early-acquisition cause.

The producer reobserves assets and actions before certifying an unresolved
current-session identity change: a former symbol with a new provider UUID and
no complete bound name-change or merger, including an observed merger whose
terms are incomplete. A typed action wait, when used for an in-flight job, is
durable, uses the original acquisition job deadline, and makes a fresh action
and asset observation on retry. It cannot reuse a retained empty action part.
The bounded candidate quarantine below permits a complete market publication
when supported identity evidence remains unavailable; it does not resolve an
identity needed by the retained book or controller.
Ordinary inactive listings and unrelated absent former symbols must not block
the entire market source merely because a merger is possible. Missing current
benchmark bars are pending only when the absent membership is the just-closed
session; malformed, duplicate and historical coverage remain refusals.

The controller consumer separately recognizes a prior selected-only witness
whose authenticated old identity is absent or replaced in the current source
and has no complete merger conversion. It reports an explicit pending input,
leaving the book unchanged. This result may ask the broker-free orchestration
layer to reobserve Alpaca; it never supplies a return, changes the source's
market facts, reads broker state, or enters Wealth Core. An ordinary delisting
with no action may remain unresolved and cannot be guessed into a return.
The postpublication retry uses a distinct acquisition deadline bounded by the
following exchange open. It must actually fetch fresh actions and assets, not
reuse the published empty action part or repeatedly read the same snapshot.

After an already published `/4` source, a retry may append a same-session
`/4` to `/4` correction only if fresh, source-proven conversion terms strictly
extend the predecessor's conversion set. The old conversions must remain
byte-identical. The immutable edge names the exact prior publication, both
source snapshots, their strategy bindings and the correction time. An identical
reobservation creates no publication. Serial corrections must form one exact
verified chain of at most eight same-strategy publications; unrelated
same-session publications and a longer chain remain ambiguous. A
correction that still does not resolve the selected witness cannot produce a
plan. A consumed decision, competing edge, changed predecessor or old terms
refuses. Before the following open the unique tip may support prospective
planning after all ordinary gates; after the open
it supports current-information state recovery only, never a backdated plan or
broker command. Reobservation stops at the relevant market-time boundary and
retains an explicit pending or blocked reason if Alpaca has not supplied terms.

A missed-session reconstruction has a different, state-only same-session
successor when a previously published `/4` source cannot be used as dated
input. Its immutable request binds the retained preceding book session through
`cursor`, the selected strategy and the exact predecessor publication. After
the following open it may reacquire current Alpaca inputs and append a `/4` to
`/4` recovery publication even when its authenticated merger conversions are
unchanged. A distinct immutable recovery edge binds both publication and source
identities; the ordinary merger-correction extension rule still applies to a
retry without `cursor` and to newly discovered conversions. Recovery validates
the prior conversion set byte for byte, admits no removed or changed term, and
requires the existing current-information marker with false historical
availability and broker authority. The dated selector authenticates this edge
as part of its bounded same-session chain, then treats the after-open tip as
current information only. A consumed session, changed predecessor, unbound
cursor, or publication before the following open refuses. Reacquisition never
changes a prior receipt or asserts that its data existed at the missed open.

## Retired supersession evidence during current verification (2026-11-24)

After a same-session correction, the current publication and daily checkpoint
may both move to the successor. Ordinary retention may then retire an older
candidate and release its large source/reference payloads. The November 24
PAPER runtime advanced to version 28 but later refused shadow verification
because its recursive supersession check tried to load legally retired version
27 evidence. This is a current-status and next-open execution blocker, not a
reason to restore an old price path or treat a dashboard warning as authority.

The current tip must still pass its full candidate, source, reference, readiness,
publication and checkpoint checks. Each supersession edge is checked under the
existing eight-edge bound, exact version/session/timing/cursor/strategy rules
and signed publication-validation receipt chain. Each unretired side of a
historical edge still receives its full source/reference and conversion-term
checks. Only a side with a durable retirement tombstone may rely on the original
immutable edge, authenticated publications and receipts, and surviving manifest,
job, validation and binding metadata for the cross-generation relation whose
released source/reference bytes can no longer be read. The signed edge must still
match the exact predecessor publication digest, snapshot and source identities,
strategy bindings and correction kind. A missing, malformed, unsigned, changed
or mismatched receipt or edge refuses. Missing bytes without a retirement
tombstone also refuse. No later provider response, matching ticker or current
source payload may reconstruct or replace the old conversion terms.

This is read-only authentication of a previously admitted correction. It grants
no new strategy, controller, broker or LIVE authority and does not alter a
historical book, plan, order, checkpoint or signed receipt. A test must retire
the intermediate candidate after the successor checkpoint is committed, then
prove current shadow and plan verification continue; removing the tombstone,
changing an edge or receipt, or damaging the current tip must still refuse.

`operational_snapshot.py` is an economic input compiler. Its installed exact
SHA256 `2adb723c2dd51972540bb0f0009ff2fc8da3b6ffafc3621003d6f231ed50a4f1`
currently contributes the reviewed predecessor source identity
`25540d4a498868db32bdb7ed5326fb0115129ead3b1bc5aebdbe4917ad4a1b32`.
The retired-edge read repair changes only authentication of already admitted
historical metadata after lawful payload retirement; it must not change prices,
conversion economics, Wealth Core state, controller returns or executable plans.
After targeted equivalence and guard-removal falsifiers, pin only the final exact
new source SHA256 to that same predecessor contribution, with its exact declared
dependency set. Any different source byte or dependency change contributes its
actual identity or refuses admission. Renew the economic manifest's own hash for
that exact mapping. The existing strategy identity and signed PAPER certificate
may remain only when the exact source and dependency gates match; another edit
requires its own separately reviewed economic and financial authority.

The observed shadow supervisor `CRITICAL_LATCH` remains an incident fence.
Ordinary restart, a new image and alert acknowledgement do not clear it.
After this fix passes required CI, install the signed PAPER release with the
canonical installer in dual mode without automatic activation, leaving the
publisher and automation quiesced and execution fenced. Follow the existing
operator procedure in `autonomous-paper-readiness.md`: inspect the stopped
worker outcome and repaired underlying cause, then hash and durably archive
both the exact critical and pending marker bytes as incident evidence before
restart. Do not delete or overwrite them. Queue the separate supervised
activation only after that archive. The coordinator must authenticate the
corrected current shadow state, exact PAPER plan and existing financial and
backup gates before releasing execution; otherwise it remains fenced. No
canonical-state reset or broker bypass is allowed.

The recovery edge changes only after-open source admission. It changes no
normalization, book transition, controller return or plan economics. The exact
reviewed `operational_snapshot.py` successor bytes therefore retain the prior
`25540d4a498868db32bdb7ed5326fb0115129ead3b1bc5aebdbe4917ad4a1b32`
economic source contribution and the installed strategy identity. Both economic
source readers recognize only that exact successor; any other edit contributes
its actual digest. A byte-exact predecessor reconstruction and an admission
guard mutation witness qualify this narrow equivalence. This does not certify
the late source as dated or grant broker authority. The economic manifest's
self-hash is renewed for this exact reader change; its closed file and dependency
inventory and all older source pins remain unchanged.

The same-session correction admission checks the retained checkpoint's strategy
with the already reviewed `economic_migration.compatible` predicate. Its
`rolling_checkpoint.compatible_strategy` forwarding helper changes neither a
checkpoint read nor its signed value. The checkpoint source-basis reader may
recover the archived candidate only from the exact reviewed helper bytes in an
exactly pinned current module; it removes that helper and must reconstruct the
archived module byte for byte. A changed helper body or neighboring checkpoint
logic loses the historical economic-source equivalence. The close-cycle source
profile remains pinned to its original `alpaca_identity` bytes; the new
merger-capable identity module is authenticated by the current source seal, not
admitted as an unchanged close-cycle addition.

Qualification must falsify missing action on both first reads for a vanished
acquiree and a same-symbol new UUID, then show that a later complete record is
fetched afresh and the exact prior anchor is used once. It must also cover
incomplete terms, a valid name change, irrelevant delisting, no-change retry,
late close benchmark coverage, original deadline, restart, correction fork and
consumption, and the following-open cutoff. These software tests cannot prove
that an absent provider action will ever arrive or replace the separately
signed PAPER release qualification.

## Unresolved same-symbol candidate identity (2026-11-24)

A same-symbol provider UUID replacement without a complete supported identity
binding or conversion must not inherit the old security identity or price
history. It also must not stop an otherwise complete source publication because
the symbol is one of thousands of ordinary-equity candidates. The November 24 AEI
observation has this shape: Alpaca reports a November 23 reverse split with
changed CUSIP, but that split does not bind the replaced UUID to the old
canonical identity. No name-change or merger conversion is present. Its old
security occurs in the retained Median-5 `peer_keys` metadata cache, but not in
prior selected witnesses, Wealth Core holdings, reserved or pending paths. The
November 23 source assigned the new UUID to pre-split bars; the corrected
publication must remove that borrowed history. The cache is consulted only
for current held episodes and is not itself a price or controller-return
dependency.

The source, without reading controller state or broker data, records every
unresolved same-symbol UUID replacement as an identity break. A complete,
unique, dated Alpaca stock-split record may establish a conservative boundary
for a **new, independent** candidate series. Its symbol, distinct valid old and
new CUSIPs, directional positive share rates and economic date must be
unambiguous; the date must follow the last authenticated old-UUID session and
precede or equal the first new-UUID inventory observation. A conflicting
structural action or unsupported terms leaves the symbol quarantined. The
split record never binds the old and new UUIDs, applies a share conversion to
the new identity, or supplies the old identity's return.

The fresh-series floor is the later of the split's economic session and the
first source session that authenticated the new UUID. The new UUID may receive
only actual paired RAW/adjusted bars **strictly after** that floor. On or before
it the source publishes no listing or normalized bar for the changed symbol.
After it, ordinary contiguous-price, adjustment, classification, population
and eligibility checks apply to the new UUID as a new candidate. The split
term is not applied to a series whose first admitted bar follows the event.
Without a complete qualifying split, the source publishes no listing or bar
for either UUID until a separately reviewed source-proven release rule applies.

The immutable source evidence records a typed, unique row containing the
symbol, authenticated old provider UUID and origin snapshot/session, newly
observed provider UUID, first affected session, floor, and any qualifying
split's exact record ID, terms hash and economic date. A named additive `/4`
identity-break subpolicy and its content-addressed source payload bind those
rows; the paired `/4` reference shape and `/4` price normalization remain
unchanged.
Earlier `/4` publications without the additive field mean an empty quarantine,
and a resumed acquisition cannot reuse ACTIONS captured before this subpolicy.
The source rechecks the rows with fresh inventory and actions at corroboration.
Malformed, duplicate, conflicting or changed evidence refuses publication.

Every later publication carries the old identity, original observation and
floor forward, even if that symbol has no current reference row. A matching
ticker, the same newly observed UUID on a later day, an apparent price path,
or a temporary listing disappearance cannot remove the floor. Another UUID
change extends the break record and resets its observation floor; no unproven
bar from either prior UUID enters the new series. A previously authenticated
split record remains bound even if a later provider action response omits it;
changed or contradictory terms refuse. The ordinary selected-candidate count
includes identity breaks during exclusion, while the admitted count does not:
an identity break cannot reduce the denominator of the 95% coverage guard or
the 500-stock floor. Widespread provider identity changes still refuse.

A later source cannot treat a legacy `/3` Alpaca source and `/3` reference as
clean merely because its current UUID matches today's inventory. When that
dated predecessor lacks identity-break evidence and no authenticated
publication already exists for the target session, the producer checks its
immediately preceding authenticated dated source for same-symbol UUID
replacements. An unbound replacement requires a corrected publication for
the affected session before the next source can continue. During an
authenticated same-session correction, the producer compares with the latest
preceding dated publication and does not read that publication's older
predecessor: its evidence may have been legally retired. Existing correction
authorization and source checks still apply. The bounded check also does not
trigger when the latest dated predecessor is `/1` or `/2`, whose earlier
aggregates may have been legally retired. The producer does not infer a new
series floor from a `/3` predecessor that already published ambiguous history.

The consumer checks the immutable prior state against the resulting snapshot.
A missing selected Median-5 witness remains `SELECTED_IDENTITY_ACTION_PENDING`;
a held, reserved or pending Wealth Core identity remains subject to its
existing anchor, mark and action guards. Neither path advances the book, creates
a plan or sends a broker command from missing identity evidence. Cached
`peer_keys` for an unheld, unselected security remain untouched and do not make
it a protected return dependency. Only the execution layer observes the PAPER
account; LIVE remains forbidden.

An identity break without a qualifying split has no automatic time-based
release. Its quarantine persists until a separately reviewed source-proven
rule establishes a safe new-series floor or a supported continuity binding.
No old bar is assigned to the new identity. A split ratio, changed CUSIP,
symbol or price resemblance alone does not authorize an old-to-new bridge or
a late correction outside the existing authenticated rules. The original
publications and failed attempts remain immutable.

Qualification must cover a complete split with no event-day or older bar under
the new UUID, its first valid later bar and eventual 127-close eligibility; a
missing, future, duplicate or conflicting split staying quarantined; and an
unrelated candidate allowing a normal decision. A selected witness and each
owned dependency must refuse without book or broker mutation. Cover next-day
and restart carry-forward, repeated or disappearing UUIDs, persistent
quarantine even after the original price window rolls away, source/reference
collision, tampered identity evidence, retained old ACTIONS, and mass UUID
churn crossing the 95% floor. Deliberately remove the floor, exclusion and
carry-forward guards and show the tests fail. The new source-history seal
and signed PAPER authority must be qualified before prospective activation.

## Canonical daily transition

Only a prior Median-5 selection that is absent from every Wealth Core held,
reserved and pending path may use the controller conversion. Before the
transition, require a unique source-bound event effective on this decision
session, its authenticated prior snapshot, the exact prior signal/raw anchor,
and the successor's positive current raw close in the selected publication.
Read the old anchor from the checkpoint-bound previous publication and compare
it with the authenticated retained feed anchor. This narrow bridge is supplied
to the existing signal-basis reconciliation. Every other protected identity
still requires its anchor in the current snapshot. Missing or contradictory
terms, identity, anchor, split basis or delivered close leave the prior book
unchanged and name the unmet input.

The existing terminal-return calculation uses the fractional notional unit,
exchange ratio and successor raw close. Median-5 records the actual return and
then removes the terminal selection under its existing rule. Wealth Core's
book and its selection rules remain unchanged; a merger affecting a held or
pending identity stays under its existing unsupported-action refusal. The
execution layer alone reconciles broker shares and no controller conversion is
an order, target-share or broker-position instruction.

The pinned economic compiler dependency map remains immutable. Merger-specific
calendar interpretation, typed terminal construction and checkpoint strategy
compatibility stay behind the compiler modules that already own those
dependencies. A new cross-boundary import is not accepted merely to make a
test pass.

## Correcting a published session

A current same-session publication under the superseded source policy is not
silently promoted. A fresh acquisition may append a corrected publication
only under a distinct policy and immutable supersession edge naming the exact
older publication version, snapshot and source schema, the same decision
session, and the new candidate and source schema. The edge is admitted only
while the old publication has not produced a canonical checkpoint. The old
publication, receipt and failed attempts remain immutable. Competing edges,
changed predecessors, unrelated strategy or consumed old publications refuse.
The edge binds the older acquisition's authenticated job strategy hash and
the corrected acquisition's selected current strategy hash. Those hashes may
differ because this reviewed controller input semantics change alters the
source identity. The retained book must be compatible with the selected
strategy under the existing economic predicate; an older data-only job may
have run under an admitted executable before the next canonical transition.
This check does not authorize runtime admission or replace its exact
historical source and migration gates.

Before the following open, an unambiguous corrected edge can replace the older
publication for *prospective* daily planning if every ordinary runtime, source,
backup and timing check passes. Dated missed-session reconstruction selects the
unique verified supersession tip only when it was published before that open;
unrelated multiple eligible publications remain ambiguous. Once the open has
passed, a corrected publication is current-information recovery only. It may
advance the preserved canonical state with a reconstruction receipt and no
historical execution plan or broker command. It never claims that the corrected
terms were available at the earlier close or restores a missed trading window.
The next fresh session must earn prospective authority normally.

## Qualification

Use generic, non-real ticker fixtures in isolated PostgreSQL. Cover a
same-symbol UUID replacement and a vanished acquiree converging on one
successor, a nonunit ratio that catches inversion, event-day successor price,
controller return/removal, unchanged held/pending book and restart. Falsify
missing, duplicate, future and conflicting terms or CUSIPs; missing successor
price; wrong prior anchor; old-history reuse; held/pending conversion; source
digest mismatch; publication fork, consumed predecessor, and a late correction
claiming dated authority. Prove that the guards fail when deliberately broken.
Before-open correction, after-open state-only recovery and lost acknowledgement
must preserve the same book/genesis and issue zero historical broker commands.

This design and PR do not install PAPER, release a kill switch, alter a broker
account or authorize LIVE. CI, reviewed merge, backed release qualification
and exact installed-source handover remain separate gates.
The standing PAPER certificate also binds the previous strategy identity.
Its narrow historical local exception does not authorize the merger reader's
new strategy digest. Before this code can produce a prospective PAPER plan,
the owner must issue and rotate a separately signed successor certificate
under the existing authority lifecycle, bound to the exact qualified runtime,
strategy, account and controller rollout. Installation by itself cannot pass
that gate. This PR leaves the old exception and certificate unchanged; see
[PAPER observation certificate rotation](sentinel-paper-observation.md).

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
`f763d3260766dffc7f14199bc5bf9ec8580bde3af2b1c4e5b0c21242ef329182`;
the old local PAPER exception still names
`caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095`.
The prior-publication lookup for a correction skips an older same-session
schema that omitted the merger, returning to the preceding dated identity
source. Publication and source hashes bind the corrected input; neither old
prices nor old reference rows are edited.

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

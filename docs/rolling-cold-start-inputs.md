# Snapshot-native cold-start inputs

Status: implementation slice of #384. This is the independent input adapter
needed before operational publication and GO cutover. It is neither a
legacy/new comparison nor permission to activate a private candidate. The
existing deployment, backup, signing and paper-only gates remain authoritative.

## Operational sequence and ownership

Fresh initialization must first inspect the existing durable state. Only a
behaviorally empty installation may initialize a new shadow. A missing cursor
beside decisions, genesis, plans or command evidence is partial state, not an
empty installation. Preserve it and refuse automatic reinitialization. Existing
state resumes from its verified checkpoint, including cash, positions, pending
instructions, feed anchors, peaks, cooldowns, controller memory and execution
identity. A rolling refresh never recreates those objects.

The operational publisher must allocate an ordinary monotonic corpus version
and bind it atomically to a sealed snapshot, its exact reference bundle,
validation receipt and producer/restore evidence. Candidate UUIDs, snapshot
hashes, preparation jobs and comparison versions cannot substitute for that
version. The eventual version-dispatched reader must obtain prices, metadata
and actions through that same binding. This PR implements input material only;
it does not allocate or invent an operational publication version.

GO must validate this publication's source-final target, current inputs and
durable state continuity before admitting a first decision. Initial canonical
warmup builds features without running historical portfolio transitions.
Current TICKERS is not historical decision metadata: use the canonical
prospective zero-capital witness and never manufacture historical witness
readiness. The first decision leaves opening intents pending, cash unspent and
executed positions empty. Execution consumes the separately admitted current
plan at the eligible next open under the existing cutoff, reconciliation,
authority and long-only guards.

Each daily preparation freezes a fresh source-final 300-XNYS-session target,
acquires and validates a private generation, and switches the publication only
after fencing/CAS and backup checks pass. Failure leaves the old publication
visible but cannot make it fresh. Advance missed strategy sessions once, in
order, using causally available references; never backdate newly fetched
metadata. Reconciliation and existing missed-open rules govern execution of
the latest plan. A cursor/dependency outside retained inputs explicitly refuses.

Restart admission still needs its own implementation: retain the exact genesis
warmup commitment and admitted checkpoint evidence, validate canonical
state/record/attestation chains, retain exact new decision input bundles, and
revalidate the overlapping current inputs plus live dependencies. Do not reload
expired original warmup prices, skip attestations, or reinterpret legacy
VERIFIED as the new bounded verification policy. No retention deletion is part
of this slice. Price rollover cannot delete reference/action history or state.

## Input adapter contract

The adapter names one sealed candidate and snapshot hash. It validates stored
content and the builder validation's snapshot binding before using that
candidate's reference bundle. The reference schema, calendar and normalization
semantics must be recognized. Alias-rejection evidence is taken from the same
builder validation used to normalize prices, not rediscovered from a truncated
price window or another generation.

Use the canonical TICKERS structural validator and dated SymbolProjection.
Resolve bar identities against that projection. Conflicting non-null category,
sector or issuer-family observations for a permanent security refuse instead
of selecting an arbitrary row. Select its current transport symbol with the
dated resolver; related-ticker parsing and issuer grouping remain canonical.
Keep full reference/action history. Source-row identities preserve distinct
ACTIONS siblings and deduplicate exact repeats.

Extract terminal row mapping from its database loader into one shared pure
function. The legacy loader and snapshot adapter use the same effective-session
mapping, source-row conservation and richest-term coalescing. An unresolved
terminal identity in the snapshot path refuses conservatively: the bounded
price window is insufficient evidence that an older security was never held.
Extract spin-off mapping similarly; missing child economics remain explicit
and never become fabricated cash or share deliveries.

The cold-start material reader scans this one bounded snapshot and selects the
exact 252 sessions preceding its final decision session. It includes the dated
SPY warmup history, adjacent BIL prices, full reference metadata and first-day
events. It exposes no historical metadata timeline. Every required warmup and
decision bar must retain its permanent identity; every priced identity must
have metadata. Day-one observations absent from warmup require proven listing
inception on that day; older returning securities require future anchor
admission rather than an assumed split basis.

The adapter returns material, not PublishedSession or a persisted shadow. It
does not assign data_version, write genesis, reset state, call a vendor, or
contact a broker. Operational composition must bind its admitted publication
version before passing material to the existing canonical kernel. These
boundaries prevent an input preparation test from becoming a GO shortcut.

Extracting the shared action mappers changes source files already included in
the production book-semantics fingerprint. Existing durable identities are not
rewritten or silently adopted; the existing mismatch refusal still applies.
This input slice must not be deployed as a way to repair partial prior state.
The admission/cutover slice must inspect and handle that state explicitly. The
new input module must join the production source identity before operational
composition begins using it; it currently has no production caller.

## Validation and outstanding acceptance

Use real PostgreSQL candidates with empty legacy market/reference/publication
tables. Verify the selected production champion's feature warmup and first
decision through the canonical kernel, with pending intents and no synthetic
fills. Test generations with different metadata/actions, weekend effective
dates, source siblings, ambiguous identities, unsupported schemas, mismatched
snapshot validation, price domains and missing cold-start dependencies. Run
guard-removal falsifiers and relevant ownership/domain tests.

Still required after this slice: operational publication receipts and dispatch;
fresh/partial-state admission; durable exact-input/checkpoint restart admission;
GO/daily scheduler composition; actual NAS state inspection, configuration and
connectivity validation; observed cold GO, paper activation/next open, restart
and subsequent daily refresh. No NAS or paper result is implied by local tests.

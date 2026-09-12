# Exceptional corporate-action adjudication

**Status: NORMATIVE — issue #364 finding A1 / issue #237 cash correction.**

Sharadar remains the ordinary corporate-action source. This contract covers the
exceptional case where a specific cash action is independently proven to be
wrong while Sharadar ACTIONS and SEP can agree with each other because both
carry the same stale upstream fact.

The first retained case is Thomson Reuters (`TRI`) effective 2026-05-04:
Sharadar retained `dividend=1.36`; Thomson Reuters published final terms on
2026-05-01 at 16:30 EDT stating US$1.435518 per participating common share.
Nasdaq's finalized corporate-action notice independently reports the same cash
amount and the 0.984560 share consolidation. The final issuer publication was
therefore available before the 2026-05-04 XNYS open.

## Authority boundary

A cash correction is accepted only through a reviewed immutable authority record.
The record is code-reviewed and commit-bound; the source row itself remains in
`sentinel_action_observations` and is never rewritten to manufacture agreement.

The persisted strategy source identity binds the adjudication resolver, reviewed
authority data, and v7 semantic migration modules. A change to any of those
sources invalidates the prior book's strategy identity under the existing
reconstruction contract.

Each authority record contains:

```text
schema / authority id
source ticker + effective XNYS session + source action
permanent security mapping resolved for that effective session
original Sharadar amount expected by the adjudication
final parsed cash amount and currency
primary source kind and URL
source publication timestamp
normalized source evidence text + SHA-256 content digest
corroborating source URLs
source-priority rule
complete authority-record SHA-256
```

The source evidence text is a bounded reviewed extract used only to make the
retained evidence self-verifying; the URL remains the external source identity.
Changing any parsed economics or provenance field changes the authority-record
digest.

## PIT rule

The effective session's XNYS open is the decision/execution boundary for a cash
action applied on that session. The independent source may override Sharadar only
when its publication timestamp is no later than that exact calendar-derived open.

```text
source_published_at <= XNYS.open(effective_session)
```

A late source is retained as evidence and has no authority over that historical
session. A malformed timestamp, non-session effective date, missing permanent
identity, or unavailable calendar fails closed.

## Conflict rule

The reviewed record names the exact Sharadar source action and stale amount it
was adjudicated against. Resolution is deterministic:

```text
observed Sharadar == reviewed stale amount   -> apply reviewed final amount
observed Sharadar == reviewed final amount   -> source has converged; no overlay
anything else                                -> refuse the flagged event
missing/duplicate matching source row        -> refuse the flagged event
invalid/missing/late authority evidence       -> refuse the flagged event
```

Other same-session distributions remain additive. The authority replaces only
the exact stale source component named by the record.

## Publication and audit

Every applied or source-converged adjudication is written as an append-only,
run-scoped audit observation containing the source and authority digests, exact
source/final decimal values, permanent security id, disposition, and provenance.
The observation becomes active evidence only when that ingest run publishes.

ACTIONS reconciliation owns semantic migration. A change to adjudication
semantics advances the ACTIONS reconciliation epoch and replays every retained
adjudicated event through the ordinary prior/effective/following-session
renormalization path before publication. No direct bar patch is permitted.

The resulting `sentinel_bars.dividend_per_share` is the only economic value that
continues downstream. Wealth Core ledger accrual, restart, state/economic
identity, historical replay, and production therefore consume the same resolved
bar value.

## TRI v1 evidence

Primary issuer source:

https://ir.thomsonreuters.com/news-releases/news-release-details/thomson-reuters-announces-cash-distribution-share-and-share

Publication timestamp: `2026-05-01T16:30:00-04:00`.

Normalized retained evidence text:

`Participating shareholders to receive cash distribution of US$1.435518 per common share`

SHA-256: `984deaf590f97905becab406a14eb66bce78db8275e66a7f0077202e27401d9d`.

Corroboration:

- SEC exhibit: https://www.sec.gov/Archives/edgar/data/1075124/000119312526201824/d139216dex991.htm
- Nasdaq finalized notice ECA2026-296: https://m.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-296

The issuer source has priority for the PIT correction because it published the
final transaction terms before the effective XNYS session. Later corroboration
confirms the parsed fact but cannot create earlier PIT authority.

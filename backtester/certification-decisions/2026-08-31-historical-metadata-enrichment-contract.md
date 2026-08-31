# Historical metadata enrichment contract

Date: 2026-08-31

## Objective

Reconstruct the best causally knowable historical state needed to answer:

> What would the production system have done in 2006?

The enrichment must improve historical metadata completeness without weakening strict point-in-time causality. It must not optimize strategy parameters or performance.

## Non-negotiable causal rules

1. A fact is economically usable only after evidence establishing that fact was publicly available.
2. SEC filing evidence is usable only when `filed < decision_session`. A filing on the decision session is treated as not yet known.
3. Current/future Sharadar TICKERS fields must not be used to backfill historical security type, sector, issuer, exchange, first/last listing date, related tickers, or permanent identity.
4. Trading activity proves that a quoted security existed on the price tape. It does not by itself prove that the instrument was common stock. Preferred stock, ADRs, ETFs/funds, warrants, units, rights, and other instruments can also trade.
5. Historical ticker identity must be tied to the contemporaneous security/issuer episode. Ticker reuse or issuer changes must not transfer later metadata backward.
6. Evidence learned later must never be backfilled to an earlier decision session.

## Security-type authority

Security type controls basic eligibility and is separate from sector classification.

Evidence is evaluated for the listed security class, not merely the issuer. Acceptable contemporaneous evidence includes SEC filing/header/cover-page evidence and other archived primary listing evidence with an independently auditable known date.

Classifications:

- `common`: confirmed common stock / ordinary-equity class that satisfies the production eligibility contract.
- `non_common`: confirmed instrument outside that contract.
- `unknown`: insufficient causal evidence.

A causally established classification may carry forward until contrary evidence, a security/issuer episode boundary, or another event invalidates that classification. Carry-forward is not permission to backfill before the evidence date.

Opening 2006 state must be seeded from evidence available before 2006 where possible. A security must not be forced to remain unknown in January 2006 merely because its next filing occurs later in 2006.

Unresolved security type remains fail-closed and ineligible.

## Issuer / CIK authority

Existing SEC Forms 3/4/5 ticker-to-CIK evidence beginning in 2006 is retained as causal evidence. The reconstruction must extend the opening-state evidence backward far enough to establish ticker-to-CIK mappings that were already public before 2006.

CIK changes define historical issuer/security episodes only when the change was causally knowable. No present-day ticker mapping may be substituted for missing historical evidence.

## SIC / sector authority

Sector does not control basic stock eligibility. It is used only where production/Sentinel consumes sector grouping.

The historical sector contract is:

`strict-prior ticker -> CIK -> strict-prior SEC SIC -> frozen FF12`

The existing SEC Financial Statement Data Sets SIC tape starts at 2009Q2 and is therefore incomplete for the 2006 objective. The reconstruction must add earlier causally dated SEC SIC evidence, including a pre-2006 opening seed where available.

A causally known SIC may carry forward until later causal evidence changes it. Missing SIC/sector remains a singleton unknown peer; it must never fall back to current Sharadar sector.

## Evidence precedence and conflicts

Primary, dated evidence is preferred. Every derived classification must retain enough provenance to identify its source, source date, issuer/security key, derivation rule, and source digest where available.

Conflicting evidence must fail closed or be explicitly adjudicated in a committed decision record. Silent precedence that changes an economically active historical classification is forbidden.

## Required 2006 validation

Before restarting the 20-year certification, produce and persist an auditable 2006 report containing at least:

- candidate-session observations and unique security episodes;
- ticker-to-CIK known/missing coverage;
- security-type common/non-common/unknown coverage;
- SIC/FF12 known/missing coverage;
- opening-state coverage on the first 2006 session;
- unresolved cases grouped by reason;
- old-versus-enriched eligible universe changes;
- old-versus-enriched ranking changes;
- old-versus-enriched trades/holdings changes;
- NAV/allocation impact;
- evidence-source and checksum manifest.

The 2006 result is not accepted merely because it is causal. Remaining unknowns must be quantified and assessed for whether they can materially change the intended historical simulation.

## GitHub provenance requirement

All material work must land on GitHub:

- reconstruction code and tests;
- workflows and environment/source pins;
- source manifests and SHA-256 checksums;
- coverage and validation reports;
- adjudication / reasoning decision records;
- deterministic generated evidence when practical to version directly.

Large immutable evidence/data artifacts that are impractical for normal Git storage must be produced/stored as GitHub Actions or package artifacts and referenced by committed pointer files containing the producing workflow/run, source commit, artifact/package identity, byte size where available, and cryptographic digest(s).

No economically material evidence, transformation rule, or adjudication may exist only in a chat transcript or transient local workspace.

## Existing evidence to preserve

The enrichment starts from the frozen causal-certification source `2a8b50b755b5b9ef6f36b686504ac491fd13ba5f` and preserves the existing canonical PIT/economic repairs. Existing SEC evidence under `research/sentinel-fastgate/pit-evidence/generated/` remains input evidence and must be checksum-verified rather than silently regenerated with different semantics.

The enrichment must not alter production strategy economics. Its only permitted economic changes are those caused by supplying more historically valid metadata to the already-defined production eligibility and sector-grouping contracts.

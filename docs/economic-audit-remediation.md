# Economic audit remediation

Normative follow-up to issue #364 A3–A6, based on
`main@71de95a69f3908b31aea10de0bc88e5638d0407f`.

## Paper performance

Alpaca paper is a transport/accounting experiment. A held cash distribution
starts a permanent account-scoped performance quarantine. The quarantine binds
the deployment, broker account, first affected session, canonical entitlement,
source-row identities, observed broker cash and activities. It never creates
broker cash or fills. Restart, a failed cycle, a later credited dividend, a
source correction, and a new takeover epoch cannot clear it for that account.
Raw account equity remains diagnostic; strategy P/L, returns and CAGR are
unavailable while quarantined. The independent canonical shadow remains the
strategy performance authority. A separate reviewed reconstruction is required
to establish any new economic account authority.

## In-kind distributions

`spinoffdividend` and `spinoff` denote in-kind child-security distributions.
Their value is retained source evidence and never enters the cash-dividend map.
The strategy policy is to require independently evidenced child ownership
before advancing an entitled parent holding. The typed event retains parent
and child permanent identities, effective session, source identity and vendor
value; a missing child-share ratio or audited child valuation refuses the
transition before accounting. The present ACTIONS schema supplies no complete
holder terms, so these events are explicitly unsupported for an entitled book.
No child disposal, cash substitution or parent reinvestment is inferred.
The execution membrane also fences these non-scalar events.

The next ACTIONS semantic epoch re-normalizes retained spin-off sessions through
ordinary ingestion to remove previously invented cash. Existing strategy source
identity rules require reconstruction when these interpretation rules change.

## Historical source mutations

Production continues forward only when the published historical mutation proof
permits it. Corpus writers retain the earliest affected date of actual changes
to normalized SEP fields, SFP reference fields and split repairs. Complete
ACTIONS publication compares added and removed source identities, including
target-side terminals and in-kind distributions. Source-retirement publication
also contributes its affected boundary. Unchanged writes and source-only
timestamp/provenance changes do not create an economic mutation.

Mutation observations are durable across failed ingest attempts. Every new
publication signs a cumulative, versioned mutation boundary into its existing
validation receipt. The canonical session kernel checks this proof before any
state transition: a mutation after the state's publication and at or before its
processed frontier requires explicit deterministic reconstruction. Missing,
malformed or discontinuous proof also refuses. A later publication cannot erase
an earlier outstanding reconstruction obligation. Fresh state formed under the
new publication may advance normally. Production never rewinds or relabels an
existing path-dependent state in place.

This detection boundary conservatively treats changed published numeric fields
as revisions, including an adjustment-level restatement. Proving an economically
equivalent historical rebase requires separate reviewed reconstruction evidence;
the source's new version alone cannot grant that authority.

## Combined cash and consolidation entitlement (B1)

Reviewed issuer cash terms declare their share basis and the simultaneous
new-shares-per-old-share ratio. TRI's May 4, 2026 participating-share terms are
USD 1.435518 per old share and 0.984560 new shares per old share, as stated in
the [final issuer filing](https://www.sec.gov/Archives/edgar/data/1075124/000119312526201824/d139216dex991.htm).
The immutable authority binds both terms and their source evidence. The
normalizer validates the consolidation and preserves ordinary vendor dividend
components separately from the issuer's raw old-share entitlement. It converts
the latter to cash per post-event share using exact rational arithmetic before
the single float boundary. Subsequent vendor adjustment rebases do not scale
the issuer cash term. The ledger's existing split-then-accrue ordering therefore
conserves the prior holding's cash entitlement, including fractional economic
share entitlements. Fractional-share cash-in-lieu remains a separate leg.

The v9 ACTIONS semantic epoch replays retained adjudicated events. Changed
publication economics and changed canonical implementation identity require
reconstruction of already-consumed history through the existing guards.

## Terminal proceeds availability (B2)

Terminal settlement declares OPEN or CLOSE availability. An executable print
also declares its phase; the waterfall can consume it only at that phase or
later. The canonical opening pass supplies the raw opening price. Exact
effective opening consideration remains available at OPEN. Grace-expiry and
orphan sweeps run at CLOSE. Settlement provenance retains the availability
phase across serialization. Opening NAV, cash and fills must be invariant to
a perturbation of only the same session's later terminal close.
An opening terms block with a usable closing print is reconsidered after
opening fills and aging, using the original prior-mark evidence. The resulting
cash and released slot become available at CLOSE. The session kernel commits
atomically, so restart replays both phases from the same prior envelope.

Acceptance uses independent arithmetic plus composed normalization, canonical
ledger, opening sizing, PostgreSQL publication, replay and restart regressions.
Historical held-event attribution and financial account reconciliation remain
separate evidence requirements for performance sign-off.

## Delivery procedure

Implementation and focused regression iterations remain local. One complete
feature-branch push and PR launch the normal required CI. Existing workflow
triggers and certification gates remain authoritative.

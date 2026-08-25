# Source-authority design for issues #257–#259

**Status:** adopted before implementation, 2026-08-24. This note supplements
`docs/sharadar-publication-authority.md` and narrows three publication boundaries.
It changes no strategy economics.

## 1. TICKERS structural authority (#257)

A complete and stable `table=SEP` TICKERS observation is not authoritative until
one shared validator proves its structure. The validator runs before the first
TICKERS fingerprint can be retained and therefore protects seed, daily,
full-reseed/identity rebuild, and current-universe construction.

The canonical source pair is `(permaticker, ticker)` after whitespace trimming
and ticker upper-casing. Both keys must be nonblank. Listing dates are strict ISO
calendar dates. Unknown/open endpoints are treated conservatively as negative or
positive infinity for overlap analysis; when both endpoints are known,
`firstpricedate <= lastpricedate` is mandatory. Intervals are inclusive, so two
different permanent identities using the same ticker on the same boundary date
overlap and are refused; an interval ending the day before the next begins is
accepted. A permanent identity changing to a different ticker remains valid.

`isdelisted` accepts only the source representations already supported by the
runtime (`Y/N`, `TRUE/FALSE`, `1/0`, booleans, or integer 1/0). Unknown values are
not coerced to the currently-listed state.

Rows with the same canonical pair are handled explicitly:

* byte-equivalent authority rows are collapsed deterministically to one row;
* any difference in an authority-bearing field is a conflicting duplicate and
  refuses the entire candidate.

Failure evidence is deterministic and bounded. It names the invariant, canonical
keys, intervals, row fingerprints, source-observation fingerprint, and at most a
small fixed number of examples. Validation holds one complete TICKERS snapshot
(~22k rows in retained calibration), never SEP history.

## 2. Manual daily through-session authority (#258)

The manual `feed-daily` command requires `--through YYYY-MM-DD`. The value is
strictly parsed, must be an XNYS session, and must not exceed the latest session
whose official close has passed at invocation. Historical closed sessions remain
valid. The resolved session is printed before producer/database construction and
is passed unchanged to `sentinel.feed.ingest.daily`; the existing automation path
continues supplying its already-resolved decision session.

Missing, malformed, weekend/holiday, future, and not-yet-closed values refuse
before vendor access or database mutation. Container UTC date is never used to
select the manual command’s market boundary.

## 3. Post-seed generation coherence (#259)

A seed records a causal SEP update boundary before its first source observation.
After all annual chunks are staged but before publication authority is granted,
Sentinel performs a bounded finalization phase:

1. Double-observe every SEP mutation exposed on the `lastupdated` axis from the
   seed-start boundary through the fixed update ceiling.
2. Validate the update envelope before fingerprinting, derive affected market
   dates, and replay only merged prior/effective/following XNYS windows through
   the canonical normalizer into the same candidate run.
3. Double-observe the complete trailing Wealth Core close window through the
   seed frontier, normalize it with the candidate TICKERS/ACTIONS generation,
   and compare exact normalized key and strategy-value fingerprints with the
   effective local candidate (published rows plus this run’s rows).
4. Persist the seed-start boundary, mutation interval and two fingerprints,
   replay windows, overlap interval, two source fingerprints, local fingerprint,
   and intended final mutation cursor in `feed_ingest_runs.publication_recovery`.

A seed publication is refused unless that durable proof is present and exactly
matches the run/window being published. Publication copies the proof into corpus
publication evidence. Only after publication succeeds may the durable SEP
mutation cursor be established at the proved ceiling.

The finalization is bounded by source changes observed during the seed plus the
fixed trailing strategy window. It is not a second full-history pass. A crash
before proof leaves no publishable authority; a crash after proof but before
publication can only resume publication from the durable proof. Source
instability, update-envelope violations, or source/local overlap drift fail
closed while the previous publication remains readable.

## 4. Composition with #251–#256

This change is based on `main@722aa14ae0e452437b80425528ba30fcf133b029`.
It expects #251–#253’s source-session membrane and #254’s update-envelope ceiling
to merge before final release. The code keeps those checks at the underlying
source boundary rather than creating competing interpretations. #259 adds the
cross-year sequencing and durable publication gate that those per-request
validators do not provide by themselves.

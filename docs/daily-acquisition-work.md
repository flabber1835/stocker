# Reduce repeated daily acquisition work

## Purpose and boundary

Startup forms the canonical book using current-information history (379 closes).
Daily operation continues that saved book with a 300-session input window. Neither
path claims historical point-in-time vendor reconstruction. Immutable input
generations protect consistent reads and restart; they are not a requirement to
reconstruct every historical information vintage.

The desired eventual acquisition path reuses unchanged history, acquires new and
revised inputs, and publishes a complete consistent window. A short date overlap
alone cannot establish unchanged history: a split can restate earlier adjusted
prices, and a disappearing record has no new price row. A provider update filter
is not by itself a complete deletion/change log. The existing Sharadar adapter
observes a table-wide refresh timestamp, not partition-specific revision proofs.
Consequently this first stage preserves complete-window acquisition. Delta-only
downloads need an independently established update/deletion contract and explicit
reconciliation policy; no unproved freshness assumption is added here.

## First-stage decisions, before implementation

Remove repeated local work whose dependency scope is already provable:

1. Alias rejection discovery depends only on collisions involving an inferred
   rename chain. Read the price rows for all labels capable of resolving to those
   identities, including native labels outside the chain. The latter must remain
   visible: a third native label can invalidate an apparent two-label witness.
   With no inferred chains, there can be no applicable rejection witness and the
   discovery price query is unnecessary. Full universe coverage and normalization
   still run once each over all rows; this projection grants no coverage authority.
2. Apply the discovered rejection evidence to the same current identity projection
   instead of rebuilding the identical metadata/action graph. This reuse lasts
   only within one fenced attempt. Every new attempt observes and constructs its
   own current projection, including after corrections or reference healing.
3. Validate a retained part's manifest identity before inspecting its payload.
   A generation mismatch cannot be reused and does not need a full payload scan.
   A selected matching part still requires the existing complete checksum/key
   verification before binding. Corrupt manifests still refuse; missing parts
   still follow ordinary reacquisition. No cross-generation reuse is introduced.

The discovery query filters before returning payloads to Python. PostgreSQL may
still scan the relevant part indexes; claim reduced replay/parsing and temporary
coverage writes, not elimination of all physical reads. Report actual phase row
counts through the existing progress protocol. No new service, persistent cache,
schema, deployment flag or strategy input is introduced.

Existing price domains, split/dividend checks, independent eligible-set coverage,
snapshot sealing, provider corroboration, deadline/fence checks and atomic
publication remain unchanged. Previous decisions and book state are never
rewritten by this optimization. Paper/execution and Alpaca authority are unchanged.

## Qualification

Compare selective alias discovery and resulting canonical snapshots with the
unoptimized full-discovery path on identical captured inputs. Include ordinary
windows, inferred aliases, competing native labels, reused symbols, changed
metadata, older price corrections and splits. Count rows consumed rather than
asserting unstable wall-clock speedups. Verify restart/corruption/deadline cases
and deliberately break selection/verification guards to establish that their
tests detect the resulting faults. These local checks do not certify NAS timing
or live-provider availability.

Local differential evidence: an ordinary 600-row source required 1,200 builder
row visits instead of 1,800 (coverage and normalization, with discovery skipped).
In the 699-row rename fixture, discovery consumed 301 relevant rows instead of
699; both paths produced identical canonical bars, benchmarks, coverage and
alias/split evidence. These counts cover builder replay only, not network bytes,
PostgreSQL physical I/O or total GO elapsed time. Four deliberate faults were
caught: omitted discovery, an excluded competing native label, unchecked matching
payload and unchecked obsolete manifest. Source updates still acquire and prove
their complete window; the result is not a claim of delta-download certification.

## Remaining acquisition work

Before delta-only acquisition, establish which revisions and deletions Sharadar
actually exposes; then define bounded overlap, periodic reconciliation, and full
refresh fallback for unsupported changes. Test assembled-window equality against
a fresh reconstruction of the same source observation. Keep this acquisition
proof separate from historical performance research or replaying the saved book.

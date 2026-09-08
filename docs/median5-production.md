# Certified Median-5 production promotion

This change promotes the complete `MEDIAN5_CANONICAL` economic profile through
a PR against main `388b8652fdb4cd43a93065884bddcc59ed59de83`. The account is flat
and no paper trading has occurred. Delivery requires a reviewed PR and a
successful equivalence test. The owner merges. This document does not authorize
deployment, state activation, a broker operation, or live trading.

The promotion branch also incorporates main
`df4683b8bf1c80453b8f542f4e3ed441387ad3f5` (PR #334, coherent NAS feed recovery).
That merge does not change the Median-5 economic rules. Its source-identity
change requires the final safety and equivalence evidence to cover the combined
code, so the pre-merge replay is not the final promotion receipt.

## Frozen authority

The independent reference is the full-PIT v13 replay at research commit
`1c66096c1e3bd650233c630d4e9f71104ac8fc32`, Actions run `34160387335`.
Its generated Median-5 normalized AST SHA256 is
`11c94a61c145261daac81047cf7b7bb1ea0c97b369476458d83fc29fbc10de95`.
The corrected base AST is
`435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde`.
Normalization replaces only the `OUT` assignment and removes AST locations.

The immutable canonical PIT package is
`ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c`;
dataset SHA256 is
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.
Formal source, classifier, and certification runtime pins respectively are
`27bb992087182c42c3c051e62bf837895f5d2ab7`,
`ba74e79490beb8950611b1d17f5d124833b3d91e`, and
`887f479b15ad861313da666ad698034d3847121c`.

Replay starts 2006-01-03; measurement covers 5,032 sessions from 2006-07-31
through 2026-07-31. The certified Candidate A curve has CAGR
0.19701208470494502, maximum drawdown -0.26388132212279014, Sharpe
1.0471046041739411 and ending multiple 36.47562758311568. Headline agreement
alone is insufficient evidence of equivalence.

## Economic profile and ownership

The canonical Wealth Core book, its ledger, next-open executor, and terminal
handling remain the owners of holdings and cash. A named Median-5 profile adds
the following behavior to that implementation. Research code is an independent
test oracle and is never imported by production.

* Twenty slots, 5% entry sizing, one steady-state admission per session,
  whole-share affordability, 10 basis points per traded side, 119-session
  review, 30% episode stop, 21-session slot and security cooldowns, and one
  session dividend settlement lag.
  New admissions require a current raw close for every holding. A documented
  terminal claim retains its carried value but freezes admissions while it has
  no current print, including during the ten-missing-session C1 grace.
* Leadership is the top raw-momentum population, with a floor of 25. The
  current durable order's first three candidates are reordered by their median
  rank over the current and previous four sessions. Absence has rank
  `len(historical_order) + 1000`; ties preserve current order. Every session,
  including an empty population or a full book, advances history. Freshness and
  admission vetoes are applied after that reorder.
* The certified security identity is the issuer exclusion key. Causal common
  equity classification, signal-domain dollar volume, and continuous history
  determine eligibility. Historical exchange metadata with no PIT authority
  cannot filter the reference population.
* Certified float32 close/return/liquidity rings and float64 running sums are
  reproduced explicitly. Recomputing rolling sums on restart changes this
  profile. Durable accumulators and 260 sessions of input history are retained.
  Published split-adjusted, dividend-unadjusted closes supply the exact signal
  basis; raw prices and raw-compatible volume retain their execution domains.
  The first published signal basis becomes the owned basis. If a declared split
  coincides with the vendor rebasing its adjusted series, a durable vendor-to-
  owned multiplier converts subsequent signal observations into that original
  basis. This conversion changes neither raw fills nor dividend entitlements;
  it prevents an existing peak from being compared to a newly rebased close.
* Sentinel breadth uses residual returns against SPY over the previous 252
  sessions, excludes the current return, requires 120 joint observations, and
  selects at most three peers at correlation >= 0.145. The security itself is
  included. Correlation ties follow the frozen security ordering. Sentinel
  retains the first observed metadata tuple (ticker, listing start, security
  identity) as the peer ordering key. Subsequent ticker renames cannot reorder
  otherwise identical correlations. These keys are formed during feature
  warm-up, persist across restart, and carry no holdings or exposure decision.
  The NumPy peer calculations live in the controller-specific
  `sentinel/controller/median5_breadth.py`; the shared recovered classifier in
  `sentinel/breadth/` retains its standard-library-only contract.
* The native parent uses damaged breadth 0.88, healthy damaged breadth 0.63,
  and a five-session damaged breadth increase of 0.30, with six healthy sessions
  for slow recovery. Candidate A uses the
  -0.085 recent-leadership divergence trigger and eight-session recovery,
  including its cross-surface recovery route. Prior effective native exposure
  is strategy timing state, never broker exposure.

## State, identities, and activation

The complete economic profile is part of the strategy identity. A caller may
not override Wealth Core or eligibility settings under an unchanged identity.
Median-5 state explicitly carries rank, numerical, peer, and recovery history.
Old 25-slot state cannot be relabelled as Median-5 or silently migrated.
Fresh paper preparation must form the profile's required history and create a
new binding under the existing execution and recovery contract.

Cold-seed validation permits the profile's warmed numerical/rank features while
requiring the canonical book to remain exactly empty. Recovery flags and native
controller memory remain cold; only the zero-capital witness and causal market
history may be formed. The warm-up commitment binds the Median-5 profile,
published signal closes, raw-compatible volume, SPY history and terminal input.

The runtime selectors must select the same profile for paper preparation,
shadow processing, authority identity calculation, and automation authority
checks. Existing frozen profile identities and certification
artifacts retain their historical meaning. Sharadar remains production input;
execution remains the sole broker-facing membrane. Median-5 certification does
not establish paper execution performance.

Observation and empty-account authority candidates must bind the controller
configuration named by their supplied strategy identity. A resolver recognizes
the frozen Sentinel 1.1, Concordance parent, and Median-5 identities and checks
the corresponding rule digest. Unknown or mismatched identities are refused.
Empty-account revalidation recomputes that controller binding instead of
copying the signed claim. This is evidence preparation only; it grants no
authority and does not enroll an account.

## Equivalence gate and review

The test runs the pinned reference and production transition independently on
the same immutable inputs. It does not feed research decisions, candidate
lists, holdings, controller states, or computed features into production.
Compare every session's eligible population, durable/admission order, pending
orders, filled quantities, occupied slots, cash/receivables, close/open equity,
breadth, witness, native/final allocations and resulting curve. Discrete
decisions must agree exactly; numerical tolerances must be recorded before the
run and cannot conceal a discrete divergence. JSON restart at selected branch
and corporate-action boundaries must match uninterrupted production.

Report the first divergence, its inputs and cause. Fix implementation drift
against the frozen authority; an economic defect in that authority is reported
explicitly and cannot be silently corrected while claiming equivalence.
Review also covers state identity guards, source hashes, warm-up, the default
runtime selectors and the unchanged execution membrane. Record confirmed bugs,
impact, disposition and falsifier evidence in the PR and this document.

The paper-package decomposition manifest remains a historical artifact. The
three intentionally changed definitions (`_default_paper_strategy`,
`_fresh_warmed_state`, `_assert_concordance_witness_authority`) receive an
explicit successor record naming this design and their current AST hashes.
Their original and decomposition-generated hashes are preserved; the promotion
does not claim those three economic definitions are equivalent to the old
default strategy. The package ownership gate checks the named successor.

The existing Sentinel safety workflow also runs the independent Median-5
component, numerical, restart, warm-up and admission regressions in its pinned
test image with network disabled. The full immutable-tape comparison is a
separate, retained promotion gate; the short CI suite does not substitute for
it. A reference staging helper reconstructs the isolated research dependency
tree from the three frozen source commits and verifies its aggregate digest
before the replay can start. Every replay requires an empty output directory
so a previous PASS cannot survive into a failed attempt. Results bind the
executed harness, dependency locks and scientific runtime versions.

## Bug register

1. **Stale breadth after a missing current bar (fixed).**
   `holdings_from_shadow` read the most recent security observation even when it
   belonged to an earlier market session. This could report a held security as
   green on absent current evidence and influence exposure recovery. The
   current global session index now gates all three breadth inputs. The
   regression fails when that guard is removed.
2. **Unbound economic override at the production kernel (fixed).**
   `advance_session` accepted a different Wealth Core or eligibility config
   under the same persisted strategy identity. A 99% entry weight could run
   under a default-profile identity. Overrides now require matching signed
   configuration hashes; Median-5 additionally enforces its exact profile.
   Removing the guard makes the regression fail with `DID NOT RAISE`.
3. **Authority defaults disagree with trading defaults (fixed).**
   The authority CLI and automation control check constructed frozen Sentinel
   1.1 identities, while the paper/shadow defaults already selected Concordance.
   This could issue/check authority for a different strategy and refuse the
   intended paper path. The runtime defaults now use the shared selector.
   Empty-account and observation candidate builders also recorded the frozen
   controller configuration; they now resolve and bind the named profile.
   Empty-account revalidation recomputes that field. Equality and stale-claim
   regressions protect the composition.

Both falsifiers are in `tests/median5/test_features.py`. The mutation checks
were executed against in-memory copies; both mutants were killed. No production
activation or broker operation was used to demonstrate either defect.
The legacy authority-default mutant was also killed by the shared-identity
regression in `tests/median5/test_components.py`.
`python tools/median5_mutation_check.py` reproduces those three kills and the
terminal-admission, breadth-precision and immutable peer-order falsifiers,
entirely in memory. The rename review fixture uses identical residual series:
replacing one red peer's ticker C with ZZ must leave the original tie order
intact. Rewriting that key changed a target's stress from 0.50 to 0.25 and its
amber label; the corrected profile preserves the first key through JSON restart.

The separate opening-equity harness defect described below is also fixed. Its
falsifiers reject replacing the production refusal with an estimated value,
silently valuing an unpriced delivered security at zero, and accepting duplicate
opening boundaries. The mutation runner now kills twelve reviewed mutations.

The full-PIT comparison fixes monetary tolerances at absolute 0.0001 and
relative 1e-12. Development exposed a scalar NumPy promotion that rounded a
small positive breadth return to zero; the port now explicitly preserves the
reference's double current close and float32 lag. Before the full run, the
nonmonetary absolute tolerance was tightened to 1e-12. Discrete order, security,
integer share quantity and allocation comparisons are exact. Fractional split
entitlements allow four floating-point representable steps (ULPs): on
2006-12-29 the canonical decimal serialization retained 216058.7007 shares while
the research binary split product was 216058.70070000002, a one-ULP difference.
This exception cannot admit an integer or whole-share order mismatch. Every
such roundoff comparison is counted. Partial development runs are explicitly
labelled `PASS_PARTIAL_EQUIVALENCE` and cannot satisfy the full promotion gate.

The frozen research curve estimates opening equity with the last observed raw
price when a current opening price is absent. Production's
`resolved_open_equity` deliberately refuses that substitution for verified
overnight/intraday performance. The first full Actions replay matched through
2008, then exposed the harness's incorrect assumption that every allocation
transition had resolved opening equity.

For economic comparison only, a read-only harness observer captures the
canonical book at its existing pre-fill opening-equity boundary, after splits,
dividend entitlement and terminal transformations. It calls the original
opening-equity function and returns its exact result unchanged. Separately it
values that same book using current raw opens or its own prior published raw
observations, matching the research convention without reading reference book
values. A missing current and prior price refuses the comparison. Every
estimated opening valuation and every affected allocation transition is
retained in the evidence. These estimates reproduce the certified research
curve; they do not establish executable returns or verified production
performance. The operational opening-price refusal remains authoritative.

The first replay divergence was 2006-09-27: production proposed buying 118,135
CMCSA shares while research froze admissions on a carried terminal claim. The
Median-5 profile now treats that claim as unresolved for admission sizing while
preserving its value and the canonical settlement machinery. This is an
explicit profile difference from the historical v1 carried-mark sizing rule.

## Reproduction

Use Python 3.12 and the repository's hashed Sentinel and test dependency locks,
with `shared` installed from this checkout. Fetch the three immutable research
objects, then stage the independent tree:

```sh
git fetch origin 27bb992087182c42c3c051e62bf837895f5d2ab7
git fetch origin ba74e79490beb8950611b1d17f5d124833b3d91e
git fetch origin 1c66096c1e3bd650233c630d4e9f71104ac8fc32
python tools/median5_reference.py --output /tmp/median5-reference
```

Extract `/canonical-pit` from the exact GHCR digest above into
`/tmp/median5-data`. The package is a data-only image and has no runnable
process. For example, Docker can copy it out of an unstarted container:

```sh
MEDIAN5_DATA_IMAGE='ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c'
MEDIAN5_DATA_CONTAINER="$(docker create "$MEDIAN5_DATA_IMAGE" /unused)"
mkdir -p /tmp/median5-data
docker cp "$MEDIAN5_DATA_CONTAINER:/canonical-pit/." /tmp/median5-data/
docker rm "$MEDIAN5_DATA_CONTAINER"
python tools/median5_equivalence.py \
  --research-root /tmp/median5-reference \
  --dataset /tmp/median5-data \
  --output /tmp/median5-equivalence --restart-every 251
python tools/median5_mutation_check.py
python -m pytest -q tests/median5
```

The full replay revalidates every immutable input member and its row contracts;
it cannot use the partial-run validation cache. `RESULT.json`,
`production-daily.csv`, and the independently generated `research/daily.csv`
and `research/summary.json` are the review evidence. A failure writes
`first-divergence.json` and exits unsuccessfully. No partial run is certification.

The long promotion replay runs in the dedicated `Median-5 equivalence` Actions
workflow, independently of the interactive workspace. It runs automatically
for relevant source changes on the promotion branch and can be dispatched
manually after merge. Documentation-only changes do not restart it. The job
records the exact commit and tree, rebuilds the existing pinned production and
test images, verifies the three research commits and data-image digest, and
runs the unchanged comparison with networking disabled. It retains the full
result, daily curves and log as a 90-day artifact, including failure diagnostics.
It cannot publish an image or activate any runtime. A terminated local run,
even after matching sessions, supplies no completion evidence.

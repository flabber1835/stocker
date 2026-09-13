# Issue 373: economic boundary repairs

Design recorded 2026-09-13, before implementation. Base:
`20dc3013da303e2fe316d239f59e604d4c43d425`. This repairs the seven code findings
in issue 373; historical impact, golden certification and deployment approval
remain separate evidence requirements.

## E1 and E6: one holder entitlement, exact classification

Conversion terms explicitly name `HOLDER` entitlement aggregation. Other
conventions are unsupported and refuse. Older serialized terms without the
field use this same holder convention. Internal strategy episodes are provenance
allocations within one holder, not separate legal holders.

Sum decimal-spelled source quantities and multiply by the decimal-spelled ratio
using exact rational arithmetic. Floor once for the security. A positive exact
remainder requires cash-in-lieu evidence regardless of the ambient Decimal
context. Allocate whole delivered ownership and the genuine residual cash pro
rata to source episodes, in ascending slot order, retaining fractional internal
ownership, age, stop state and source-lot history. Assign representation residuals
to the last slot so aggregate delivered shares and credited cash equal the
single-holder result. A zero aggregate delivery releases all episodes. Pending
SELLs follow their continuing episode's allocation; pending BUYs own no
entitlement and may proceed only when their exact product is integral.

## E2: corroborate the multiplier that is applied

The one-percent price agreement rule cannot reconstruct contractual ratios.
Keep stated non-integer consolidations. A rounded five-decimal source value may
be reconstructed as `1/N` only when exactly one integer denominator lies inside
its half-quantum interval and independent price evidence corroborates that
candidate. Values with more source precision retain that precision. Without
price evidence, apply the stated value. Ambiguous reconstruction retains the
stated value rather than choosing an integer. Direct, shifted and bridge paths
use the same rule and corroborate the applied multiplier.

Increment ACTIONS semantic authority and replay retained split dates through the
ordinary publication path before earning the new cursor. Preserve source rows
and publish split-source evidence with the semantic replay. Existing historical
mutation/reconstruction fences remain authoritative; no old book is silently
repaired and no performance claim follows from the migration.

## E3: event selection and historical relevance have different windows

Select terminal events by effective exchange session. Resolve permanent identity
before excluding an event for irrelevance. A resolved event remains visible even
without a current price. For unresolved identities, published raw-ticker bars and
rejections through the requested end date establish relevance, including prices
before the requested start. Never use future bars as evidence. This gives daily
and wider loads identical event facts for a carried security and its aliases.
Missing identity for a historically priced ticker blocks explicitly. Weekend
snapping, publication visibility, coalescing, and OPEN/CLOSE availability remain
unchanged.

## E4: coherent cash affordability and booking

Cash affordability and traded-side cash cost use exact rational arithmetic
over canonical decimal spellings of cash, quantity, raw price and basis points.
Floor the exact cash-affordable quotient and round the final cost once to float.
V5's intended-dollar sizing retains its frozen float quotient and is capped by
that exact cash affordability. Thus numerical sizing of a strategy dollar intent
remains distinct from permission to spend settled cash.
Canonical booking and execution opening projection call the same cost function;
the strict nonnegative residual guard remains. Float state remains the storage
contract. No epsilon permits overspending or rewrites a genuinely negative cash
balance. This corrects cash-affordability boundaries without changing the
selected strategy's intended-dollar quotient.

## E5: production backup policy is required by the image

Every supported financial service carries `REQUIRED_V1`, including the standby.
The immutable Sentinel image additionally contains a root-owned backup-policy
marker. Its presence requires full restore-horizon proof even when an environment
overlay omits the flag; malformed policy refuses. Outside that production image,
unconfigured test/developer calls retain their existing behavior. All common
writer and final transport checks use this policy. Observation, UNKNOWN recovery,
lease coordination and emergency fencing retain their existing exemptions.

## E7: refuse an unrepresentable split before mutation

Retain the existing twelve-decimal share storage convention. Before applying any
split, preflight every affected holding and quantity-based pending order. Refuse
a positive entitlement rounded to zero, relative share error above `1e-12`, or
marked absolute error above `1e-8` dollars using the larger available post-action
raw open/close. The relative bound also applies without a usable mark. Refusal
precedes relabeling, cash, ledger, share and pending-order mutation. This declares
the supported numeric domain explicitly: the extreme thirteenth reverse split
in E7 must refuse, preserving the last valid restorable state. Ordinary splits
continue preserving fractional entitlement without inventing cash-in-lieu.

## Validation

Use independent exact-arithmetic oracles, partition and restart metamorphisms,
the canonical session and opening resolver, physical PostgreSQL terminal loading,
and backup media/transport fixtures. Demonstrate each regression detects its
original fault. Run only relevant suites and syntax checks. Do not re-pin golden
results or claim corrected historical performance.

Unit/database fixtures model developer environments explicitly by substituting
an absent image-policy path. They retain flag-driven media enforcement and the
dedicated policy tests install the real policy bytes. A separate production-image
probe (without pytest fixtures) must prove flag omission cannot disable policy.

## Reproducible checks

The targeted scope below uses Python 3.12 in the existing
`sentinel-test:paper-observation` dependency image, current source mounted read-only
at `/work`, `PYTHONPATH=/work/shared:/work`, `SENTINEL_REPO_ROOT=/work`, and
`--network none`. PostgreSQL cases start isolated physical databases.

```sh
python -m pytest -q -p no:cacheprovider --tb=short \
  tests/wealth_core/test_conversion_entitlements.py \
  tests/wealth_core/test_terminal.py \
  tests/wealth_core/test_terminal_opening_causality.py \
  tests/wealth_core/test_terminal_audit.py \
  tests/wealth_core/test_terminal_admission.py \
  tests/wealth_core/test_pending_corporate_actions.py \
  tests/wealth_core/test_issuer_rebinding.py \
  tests/wealth_core/test_restore_economic_invariants.py \
  tests/wealth_core/test_restore_nested_economic_invariants.py \
  tests/v5/test_opening_rounding.py \
  tests/v5/test_opening.py \
  tests/v5/test_opening_durability.py \
  tests/v5/test_opening_identity.py \
  tests/v5/test_review_regressions.py \
  tests/sentinel/test_split_source_precision.py \
  tests/sentinel/test_terminal_historical_relevance.py \
  tests/sentinel/test_split_reconciliation_nas_evidence.py \
  tests/sentinel/test_issue237_tri_split.py \
  tests/sentinel/test_action_source_identity.py \
  tests/sentinel/test_actions_wiring.py \
  tests/sentinel/test_issue209_target_reprojection.py \
  tests/sentinel/test_preopen_share_unit_authority.py \
  tests/backup/test_service_backup_policy.py \
  tests/backup/test_runtime_backup_authority.py \
  tests/backup/test_runtime_backup_integrity.py \
  tests/sentinel/test_terminal_identity.py \
  tests/sentinel/test_terminal.py \
  tests/sentinel/test_corporate_action_cash_adjudication.py \
  tests/sentinel/test_history_mutation_publication.py \
  tests/sentinel/test_issue237_actions_semantic_v6.py \
  tests/sentinel/test_issue_185_renormalization.py \
  tests/sentinel/test_maintenance_future_cursor_refusal.py
python tools/verify_issue373_falsifiers.py
```

The mutation command restores thirteen faults in separate processes without
editing source: E1 holder allocation and unsupported convention; E2 broad ratio
snapping; E3 same-window relevance; E4 float cost and missing cash guard; E5 flag
omission, standby configuration, malformed and unknown policy; E6 context-rounded
entitlement floor; E7 precision loss and missing batch preflight.

Production image verification uses `docker build -f Dockerfile.sentinel -t
sentinel:issue373 .`, followed by a network-disabled container executing the
following probe outside pytest, as the image's default unprivileged user:

```python
import os
import stat
from sentinel import backup_runtime_authority as authority
marker = authority.POLICY_MARKER
assert authority.AUTHORITY_ENV not in os.environ
assert marker.read_bytes() == authority.POLICY_BYTES
assert marker.stat().st_uid == 0
assert stat.S_IMODE(marker.stat().st_mode) == 0o444
assert os.getuid() == 10001
assert authority.enabled()
```

These are code-regression and image-policy checks. Historical impact replay,
economic recertification, production deployment and audit closure are not
claimed by this remediation.

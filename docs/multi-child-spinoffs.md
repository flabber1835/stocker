# Multiple children at one spin-off boundary

A held parent may distribute several distinct child securities at the same
session. The canonical ownership transition must receive and liquidate every
supplied, reviewed child atomically under the existing child-liquidation policy.
This changes neither Wealth Core selection nor Sentinel exposure policy.

Identify an economic entitlement by session, permanent parent identity and
permanent child identity. A different source-row identifier does not create a
second entitlement to the same child. Reject duplicate/conflicting child terms,
including different tickers for one identity, before any cash, holdings, basis
or ledger mutation. Match parent and child opening-bar tickers to their reviewed
identities; ambiguous duplicate opening bars refuse. Unheld parents remain inert.

Preflight every supplied sibling's ratio, opening bar, policy and fractional
valuation before posting any child. Missing terms for a supplied sibling refuse
the whole transition. The kernel cannot infer a child omitted entirely by the
publisher: completeness of the reviewed event set remains a source-admission
obligation, not something this function certifies.

Round each child's entitlement once across all episodes owning its parent.
Charge the existing liquidation fee on whole shares only; retain the explicit
cash-in-lieu valuation for fractions. Do not substitute vendor spin-off value
for cash consideration. Record each child's receipt and liquidation separately.
Canonical session/parent/child ordering makes equivalent sibling input orders
produce the same accounting and evidence.

For parent opening price P and child ratios r_i with opening prices C_i, apply
one reference multiplier to every parent episode:

    scale = P / (P + sum(r_i * C_i))

Compute each per-parent child value directly from its exact rational ratio.
Use the existing single-child arithmetic when there is one child. Multiplying
individual child scales would reduce the parent basis too far. The basis uses
gross child opening value, while cash includes liquidation fees and the supplied
fractional valuation. Preserve parent shares, slots, age, pending exits and raw
entry cost; scale only the existing signal entry and peak references once.

The source identity changes and existing production checkpoint identity guards
must continue to reject a checkpoint from another runtime. No checkpoint
migration or historical research supplements are part of this production PR.

## Bounded financial certification

Require independent decimal/rational cash, fee, entitlement and basis oracles
for whole, fractional and multi-episode cases, including the two-share
LVNTA/CHUBA/CHUBK example (0.1 and 0.2 ratios). Prove complete supplied-set
atomicity, duplicate rejection independent of source IDs, permutation stability,
serialization/restart equivalence and canonical-session integration. Compare
single-child outputs to current main byte-for-byte. Deliberately break old
parent-only uniqueness, duplicate rejection, aggregate rebasing, holder rounding
and fee handling; the relevant financial tests must fail.

Run the applicable production-state, formed-accounting, source-identity and
operational-parity regressions plus normal PR CI. Record exact source and test
identities and results in the audit ledger. This is a bounded financial
certificate for the ownership transition, not certification of the twenty-year
performance, real provider event completeness, broker cash-in-lieu finality,
native fills, NAS operation or deployment.

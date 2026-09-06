# Research Champion PIT metadata closure

**Status:** accepted dataset-maintenance design

## Scope

Close metadata only for securities observed by the frozen Research Champion
strategy-path ledger produced by run `33994291853` at source SHA
`53dc0bf9adbe7d3ee60b2a54d9769dcdfdea7306`.

The Champion profile, parameters, execution rules, portfolio construction, and
controller economics are immutable inputs.  This work may change only the PIT
metadata corpus and the evidence describing that corpus.

## First closure stage

The first stage allocates already-retained ownership-strict V4 security-type
authority to the 1,751 unknown-type candidate-boundary securities.  It uses:

- the exact strategy-path worklist and session ledger from run `33994291853`;
- the issuer-safe, ownership-strict V4 canonical audit from run `33720489684`;
- strict-prior allocation: `usable_after < decision_session`;
- complete rejection of every same-date V4 security-type conflict.

This stage produces an evidence ledger.  It does not rewrite the canonical
corpus and does not run an economic replay.

## Economic priority

Unknown security types are ordered as follows:

1. securities that reached a durable rank or recent-leadership set during a
   classified part of their history;
2. remaining unknown candidate-boundary securities requiring counterfactual
   ranking after classification;
3. securities held during another classified part of history when they did not
   reach either recorded leadership set;
4. remaining candidate-boundary cases.

Terminal work is ordered by direct held-position contact, leadership contact,
then remaining candidate-boundary contact.

## Acceptance contract

Every allocated observation must resolve from a security-ID-bound V4 event
whose usable date is strictly earlier than the decision session.  Ticker-only
joins, future observations, same-session observations, and conflicted events
are rejected.  A security is `ELIGIBLE` or `INELIGIBLE` only when every unknown
candidate observation is resolved consistently.  Partial coverage remains
`PARTIAL`; absence of admitted authority remains `UNRESOLVED`.

The next dataset build may consume only the allocated observation ledger after
it has been retained in a content-addressed package and bound to its source
hashes.

## Second closure stage

The second stage closes the first held-position terminal batch.  A case is
accepted only when contemporaneous SEC filings establish the holder
consideration, completion date, and final executable session.  Mixed and
elective consideration preserves every cash and successor-security component;
the batch does not collapse those events to a cash approximation.

The initial batch contains KMR, HRC, VMW, STRZA, and GMCR.  These are selected
from the exact `1_HELD_POSITION` terminal priority produced by stage one.  The
stage-two workflow authenticates that parent artifact, proves the five
security-ID/ticker bindings, validates temporal ordering and consideration
completeness, and emits a content-addressed accepted-event ledger.  Corpus
mutation remains gated on that immutable ledger and a separate integration
replay.

## Terminal integration planning gate

Accepted evidence is translated into the existing
`backtester.causal-terminal-terms/1` schema only after the pinned canonical PIT
package reproduces the target identity, successor identity, issuer authority,
and same-session successor price witness.  Cash mergers require the target
identity at its last executable session.  Conversions and mixed mergers also
require a delivered security on the effective session.  Election mergers stay
blocked until the shareholder no-election allocation is established.

## Time-boxed best-effort security-type estimate

The exhaustive certification closure is supplemented by a separate research
estimate.  It answers the narrower economic question: whether the frozen
Champion remains attractive when a reproducible, vendor-corroborated estimate
of common-stock eligibility fills missing historical security-type evidence.

The estimate uses the frozen Sharadar TICKERS snapshot already retained on the
research branch.  An unresolved Champion security may be classified only when:

- its ticker has exactly one `SEP` securities-master row;
- that row's price bounds cover every candidate session requiring inference;
- its category maps unambiguously to common equity or an excluded instrument;
- existing strict-prior V4 evidence does not contradict the inferred class;
- already-known classification on the same strategy-path security does not
  contradict the inferred class.

Categories containing `Common Stock` are estimated common except categories
that also contain `Warrant` or `Preferred`.  Preferred stock and warrants are
estimated non-common.  Any other category remains uncertain.  Matching is bound
to the Champion security ID and its candidate-session interval; ticker-only
classification without interval coverage is rejected.

This is current-snapshot corroboration, not proof that the classification was
historically available.  The generated ledger and every replay consuming it
must therefore be labelled `BEST_EFFORT_NOT_PIT_CERTIFIED`.  It may not replace
the evidence-only corpus pointer or produce the project's PIT-certified banner.
The Champion profile, parameters, execution, ranking, and portfolio economics
remain frozen.  Comparative replays must generate their own chronological
decisions and report sensitivity to unresolved/rejected cases.

## Best-effort replay boundary

The completed inference ledger from coverage run `34000584483` is retained as
the branch-owned input `backtester/data/champion-best-effort-security-types-v1.csv`.
Its SHA-256 is
`1391630785c56daa2c4665abe792dd7b06d3697b47e2224edd380737fef133ab`.
The retained summary has SHA-256
`c483ccb077014eacdb742d3a74dcbce9fd68c41b0f77cc0ebbd6f6b64549cdf6`.
The ledger resolves 1,493 securities as common and 240 as non-common. Eighteen
conflicting securities remain unknown.

The economic estimate consumes this frozen ledger as an overlay at the
candidate/session security-type boundary; it does not rewrite or replace the
canonical PIT package. A classification is used only when the canonical
metadata row is unknown and the decision session lies within the ledger's
recorded inference interval. Canonically known common and non-common rows are
never overridden. A missing ledger row, an out-of-interval request, or an
unexpected class fails the replay.

Two chronological replay arms isolate the remaining classification uncertainty:

1. `conflicts_excluded` admits inferred common securities, excludes inferred
   non-common securities, and leaves all 18 conflicts ineligible;
2. `conflicts_common` makes the same changes but admits the 18 conflicts as
   common-stock stress cases because their current vendor category says common.

Both arms otherwise retain the corrected frozen Champion economics and
Production terminal behavior. They are sensitivity estimates, not PIT
certificates, and every result must carry `BEST_EFFORT_NOT_PIT_CERTIFIED` and
`certification_status: NOT_CERTIFIED`.

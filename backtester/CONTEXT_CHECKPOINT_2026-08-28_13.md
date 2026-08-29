# Backtester context checkpoint 2026-08-28 — 13

This checkpoint records the latest causal/PIT replay certification state. Production `main` remains read-only for this research work.

## Pinned production source

- Main SHA: `c502d077cae9c494f8b74a41ee8be7f40b25837d`
- Research branch: `research/backtester`

## Checkpoint/resume certification

The bounded checkpoint/resume architecture is implemented for the final v3 A/D replay and held-terminal-gap scan.

First equivalence run `#33230325743` is GREEN. Uninterrupted execution and stop/checkpoint/resume execution produced byte-identical `daily.csv.gz`, `metrics.csv`, and `summary.json` after canonical output-column ordering was enforced.

Stronger stateful equivalence run `#33231117281` is currently in progress. It crosses a live portfolio checkpoint at 1998-12-31 and continues through June 1999. Latest observed step: `Run uninterrupted stateful control`. Acceptance remains byte-identical economic output after checkpoint/resume.

## Split certification

Seven primary-source direct split adjudications are frozen in `backtester/data/causal-split-overrides-v1.json`.

Frozen dataset SHA-256:

`95e6c4f9519d70f88a3f4f17fccfb9bc6df772989b14210bd801a3d2e2c22557`

Exact-event verifier run `#33230648632`: GREEN.

Independent full-corpus normalization audit run `#33230668663`: GREEN.

Exact certified result:

`[SPLIT-ADJ-SCAN] PASS bars=46,238,394 last_session=2026-07-31 adjudicated=7 unresolved=121`

Therefore the exact unresolved count has moved from 128 to 121 with no unrelated disposition-count substitution.

Remaining genuine date/domain anomaly queue:

- DAYR
- PRTK
- NEOM
- PRPO

### PRTK identity-boundary result

Dedicated inspection run `#33231263414`: GREEN.

Permanent security identity is `123177`. The frozen TICKERS rows expose only alias `PRTK` for that permanent ID, with first priced date 2009-02-03. Frozen ACTIONS contains:

- 2009-01-30 split `0.2`
- 2009-02-03 listed
- 2009-02-06 split `0.2`

Frozen SEP shows raw/signal factor `0.2` on 2009-02-03 through 2009-02-05, then factor `1/12` beginning 2009-02-06. The February 6 row is therefore a separate vendor date/domain inconsistency, not evidence of another valid 1-for-5 economic split. Primary-source legal evidence still governs the actual reverse split. A repair must preserve the legal share change once and suppress the duplicate/stale vendor-domain transition without changing permanent identity.

PRTK inspection artifact ZIP SHA-256:

`c7099b765ec684e0b903aa6e7419e3514eb8525e65a4d01907bc06bca49e8f72`

## Terminal/corporate-action state

Frozen causal terminal repairs include LIT1, CIT.A, GPU, and EFD1/eFunds.

EFD1 security ID `182962` is settled as a cash merger at `$36.50/share`, effective 2007-09-12, known by 2007-06-27. Terminal terms verification `#33230738054` and production settlement integration `#33230759612` are GREEN.

Checkpointed full held-terminal-gap scan `#33230785210` is in progress. Latest observed state: segment 1 executing `Run scanner segment`. The workflow is segmented below the GitHub six-hour ceiling and persists accumulated gap evidence in each checkpoint.

## Obsolete one-shot A/D v2

EFD-aware uncheckpointed v2 run `#33230723752` was cancelled during the long replay step. Artifact upload completed. This cancellation was orchestration cleanup of the obsolete one-shot path, not an economic or data assertion failure. A dedicated `cancel obsolete uncheckpointed A/D run` workflow is present on the research branch.

The final replay target remains the checkpointed v3 path after all data-certification gates close.

## Outstanding certification work

1. Require stateful checkpoint equivalence `#33231117281` to pass byte-for-byte.
2. Complete the checkpointed held-terminal-gap scan and repair every economically reachable held terminal gap.
3. Freeze defensible date/domain repairs for DAYR, PRTK, NEOM, and PRPO and rerun exact-event plus 46,238,394-bar audits.
4. Complete economic/share-count review of the 66 no-transition split cases.
5. Complete timing/equivalence disposition for the 51 direct/inverse/shifted split cases.
6. Rerun terminal scanning under the final split dataset.
7. Launch the eight-segment checkpointed v3 A/D replay.
8. Publish 5/10/15/20-year CAGR, Sharpe, drawdown and A-vs-D results only after all certification gates are GREEN.

No current partial CAGR is promotion-grade or final PIT-certified.

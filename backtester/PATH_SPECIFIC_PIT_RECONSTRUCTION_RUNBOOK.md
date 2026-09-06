# Path-specific PIT reconstruction runbook

## Purpose

This runbook records the reusable process used to reconstruct and certify the
historical input path of a frozen trading strategy. It is designed for cases
where a complete market-wide point-in-time metadata corpus is too expensive to
close and the required claim is limited to one exact strategy, parameter set,
measurement interval, dataset identity, and execution model.

The process first discovers the largest conservative set of records that can
affect the strategy. It then narrows that set through chronological replays,
counterfactual sensitivity, and decision-frontier evidence. Only records that
can change the frozen strategy's decisions or modeled economics remain in the
final certification worklist.

## Certification claim

The target claim is:

> PIT CERTIFIED — frozen strategy-specific economic execution path

That claim means the authenticated historical inputs, causal timing rules,
security eligibility, corporate actions, terminal treatment, and execution
assumptions needed by the exact frozen replay were verified and reproduced.

The claim is bound to:

- strategy profile and profile hash;
- source commit and generated replay hash;
- canonical dataset and package hashes;
- warm-up, measurement-start, and end sessions;
- security-type authority ledger;
- terminal-event authority ledger;
- portfolio construction, transaction-cost, and execution assumptions;
- final orders, holdings, daily NAV, metrics, and artifact hashes.

It does not claim identical live fills, spreads, market impact, broker behavior,
tax treatment, operational availability, or realized account returns.

## Champion reference implementation

The reference reconstruction uses:

- profile: `strategy9-e3-research-champion-v1`;
- profile SHA-256:
  `1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26`;
- pinned runtime commit:
  `887f479b15ad861313da666ad698034d3847121c`;
- warm-up start: `2006-01-03`;
- measurement start: `2006-07-31`;
- end session: `2026-07-31`;
- initial capital: `$100,000,000`;
- slots: `25`;
- entry weight: `4%`;
- transaction-cost fraction: `0.1%`;
- execution: next positive-volume raw open;
- dividend settlement: one session;
- unresolved held mark: carry the last trustworthy raw mark and block new
  admissions;
- recent-leadership missing close: Production-compatible zero contribution,
  with every terminal contact retained for closure.

## Immutable checkpoints

| Purpose | Run or commit | Result |
|---|---|---|
| Conservative Champion path discovery | Run `33994291853` | 6,914 worklist securities; 1,751 unknown-type potential displacers |
| Retained strict-prior allocation | Run `33997143142` | 59 securities and 25,400 observations resolved from retained authority |
| Best-effort common-stock coverage | Run `34000584483` | 1,733 of 1,751 securities resolved; 18 conflicts |
| Classification sensitivity replay | Run `34001156188` | Material 20-year CAGR range established |
| Wayback evidence pass | Run `34001859807` | 5 non-common, 11 unresolved, 2 parser conflicts |
| Reviewed 18-name replay source | Commit `0735092abc43425f52a976c1525a6dbc486c347f` | Reviewed ledger plus effective decision-frontier telemetry |
| Definitive reviewed replay | Run `34005390953` | Pending at time of this checkpoint |

The retained Sharadar TICKERS snapshot SHA-256 is:

`308bcc46f4efaffe6f6fc4f7236af82df5c57a9f2be07c677089f0e6fba2eebf`

The best-effort 1,751-security ledger SHA-256 is:

`1391630785c56daa2c4665abe792dd7b06d3697b47e2224edd380737fef133ab`

The reviewed 18-security ledger SHA-256 is:

`3440fd1007062644868fbab5a872b52e87b9892f05673f825d27a385833143b6`

## Phase 1: freeze the experiment

Record the exact strategy profile, parameters, source SHA, runtime SHA,
measurement interval, warm-up interval, cash convention, costs, order timing,
portfolio sizing, and benchmark. Compute hashes before reconstructing metadata.

Strategy economics remain immutable during reconstruction. A correctness change
requires a new frozen profile and a new reconstruction identity.

## Phase 2: authenticate the canonical package

Pull the canonical PIT package by digest and verify it before replay. Preserve
the package pointer, dataset hash, manifest, observation counts, session count,
and input hashes in the run artifact.

The Champion workflows use:

```bash
python backtester/canonical_pit_package.py verify \
  --pointer backtester/data/canonical-pit-20y.json \
  --dataset canonical-pit
```

Never accept a mutable tag, an unverified extracted directory, or a current
vendor response as the identity of a certification input.

## Phase 3: discover the conservative strategy envelope

Run the frozen strategy chronologically and observe state after the normal
strategy calculations. Retain every security touching:

- the base candidate boundary before security-type filtering;
- the eligible ranking population;
- the established momentum pool;
- durable rankings;
- recent-leadership calculations;
- pending orders;
- held positions;
- terminal events attached to any live set.

The conservative base boundary is essential. An unknown security excluded by
metadata can still change top-decile population, cutoff geometry, leadership,
admission, holdings, or controller exposure if its true class is eligible.

Reference implementation:

- `backtester/research_champion_pit_closure.py`
- `backtester/run_research_champion_pit_closure_20y.py`
- `.github/workflows/champion-pit-path-closure.yml`

Primary artifacts:

- `strategy-path-session-ledger.jsonl.gz`;
- `strategy-path-events.jsonl.gz`;
- `strategy-path-worklist.csv`;
- `candidate-envelope-worklist.csv`;
- `strategy-path-manifest.json`.

## Phase 4: allocate retained PIT authority

Join existing historical authority to candidate observations by permanent
security ID. Require the authority to be usable strictly before the decision
session. Reject ticker-only joins, future observations, same-session evidence,
issuer mismatches, and conflicting events.

Assign one of four outcomes:

- `ELIGIBLE`: every required observation resolves as common equity;
- `INELIGIBLE`: every required observation resolves as non-common;
- `PARTIAL`: authority covers only part of the required interval;
- `UNRESOLVED`: no admissible authority covers the interval.

Reference implementation:

- `backtester/prioritize_champion_pit_closure.py`;
- `.github/workflows/champion-pit-metadata-closure-stage1.yml`.

## Phase 5: build a bounded research estimate

Use a frozen securities-master snapshot to estimate the remaining unknown
security types. Bind each inference to the permanent security ID and required
session interval. Require one unambiguous securities-master row whose price
bounds cover the interval. Reject conflicts with known path classifications or
strict-prior authority.

This stage measures economics and carries the label
`BEST_EFFORT_NOT_PIT_CERTIFIED`.

Reference implementation:

- `backtester/build_champion_best_effort_security_types.py`;
- `backtester/data/champion-best-effort-security-types-v1.csv`;
- `.github/workflows/champion-best-effort-security-type-coverage.yml`.

## Phase 6: run counterfactual sensitivity

Replay unresolved conflicts under explicit bounding scenarios. The Champion
used two chronological arms:

1. all 18 conflicts excluded;
2. all 18 conflicts admitted as common.

The resulting 20-year Champion CAGRs were approximately `17.18%` and `19.91%`.
The 2.73 percentage-point range proved that the conflicts were economically
material and required individual reconstruction.

Always replay the full chronology. A security classification can change
ranking composition, the recent-leadership market signal, portfolio holdings,
and future controller state.

## Phase 7: reconstruct disputed security types

### Eligibility definition

Freeze the strategy's exact security taxonomy before research. For the Champion
18-name review, corporate common stock and corporate common shares were
eligible. Partnership units and limited-liability-company interests were
ineligible even when a vendor labeled them domestic or ADR common stock.

Explicitly classify preferred stock, warrants, rights, SPAC units, funds,
depositary receipts, partnership units, LLC interests, and multiple share
classes according to the frozen profile's rules.

### Evidence hierarchy

Use the strongest available evidence in this order:

1. contemporaneous SEC registration statement, prospectus, or periodic filing;
2. contemporaneous exchange listing or corporate-action notice;
3. dated archived issuer investor-relations page;
4. dated issuer press release;
5. Reuters, Dow Jones, or another dated business wire;
6. scanned newspaper or institutional news archive;
7. current vendor classification as corroboration only.

For each accepted row retain:

- permanent security ID and ticker;
- disputed first and last sessions;
- classification;
- source date and source class;
- stable or archived URL;
- concise security-description evidence;
- reviewed disposition;
- file hash when a source document is downloaded.

### Reviewed Champion result

Eligible common shares:

- PCG;
- PDS;
- TFC;
- TRP.

Excluded partnership units or LLC interests:

- AB;
- BEP;
- BIP;
- BPY;
- EMESQ;
- EPD;
- ETP;
- LB;
- MMP;
- RTLR;
- SHLX;
- USAC;
- WES;
- WPZ.

The authority ledger is:

`backtester/data/champion-reviewed-security-types-v1.csv`

## Phase 8: use archive automation as discovery

The Wayback probe queries dated captures, records replay URLs and matched text,
and classifies exact security-title phrases. Its outputs are discovery evidence
that require review.

Reference implementation:

- `backtester/research_champion_wayback_security_types.py`;
- `.github/workflows/champion-wayback-security-type-evidence.yml`.

Known archive failure modes:

- serial 45-second retries can make a small worklist take more than an hour;
- CDX wildcard queries can time out or return zero candidates;
- archived pages can mention securities belonging to another issuer;
- a page can contain both common-share and partnership language for unrelated
  instruments;
- current pages can expose old articles with a recent capture timestamp;
- OCR and damaged encodings can hide exact phrases.

The Champion pass produced a false BPY conflict because a BPY page mentioned
BPO common shares. The TRP conflict was also caused by page-level mixed-text
matching even though the relevant passages identified TRP as common shares.
Review must bind the matched phrase to the exact ticker and issuer.

## Phase 9: run the definitive reviewed reconstruction

Apply the reviewed ledger only when the canonical metadata row is unknown and
the decision session lies within the reviewed interval. Preserve canonically
known common and non-common classifications.

Run:

```bash
python backtester/research_champion_best_effort_classification.py \
  --scenario reviewed_18 \
  --output reviewed-classification/reviewed_18
```

Reference workflow:

`.github/workflows/champion-best-effort-classification-20y.yml`

The output must remain `RECONSTRUCTED_PATH_NOT_YET_CERTIFIED` until the path
closure checks pass.

Required output includes:

- 5-, 10-, 15-, 20-year, and maximum-window metrics;
- daily strategy and benchmark series;
- generated replay source and source hash;
- package-integrity receipt;
- effective strategy-path ledgers;
- `reviewed-security-decision-frontier.csv`;
- `reviewed-security-decision-frontier.json`;
- complete `SHA256SUMS.txt`.

## Phase 10: close the decision frontier

For every reconstructed security, report its exact role:

- `ECONOMIC_PATH_CONTACT`: durable rank, recent leadership, pending order, or
  held position;
- `RANKING_INPUT`: eligible ranking or established-pool input;
- `BASE_CANDIDATE_ONLY`: passed the pre-classification boundary only;
- `NO_REPLAY_CONTACT`: did not touch the reconstructed replay.

Validate every authority that can alter rankings, leadership, orders, holdings,
or returns. Prove other unresolved observations irrelevant through retained
session state and counterfactual checks. Preserve the proof and hashes.

Cross-sectional effects require special care. Low-ranked securities can change
population size and percentile cutoffs. The proof must account for cutoff index,
score ordering, ties, minimum leadership breadth, and the effect of adding or
removing a candidate.

## Phase 11: close encountered terminal events

Inspect terminal events only when they contact the effective ranking,
leadership, pending-order, or held-position path. For each encountered event,
prove:

- permanent target identity;
- announcement and effective dates;
- last executable session;
- cash consideration;
- successor-security identity and ratio;
- election or proration rules;
- same-session successor price witness when required;
- dividends or other distributions included in holder value.

Mixed and elective consideration must preserve every delivered component.
Incomplete evidence remains an explicit certification blocker.

Reference components:

- `backtester/run_research_champion_terminal_pit_20y.py`;
- `backtester/validate_champion_terminal_evidence.py`;
- `backtester/plan_champion_terminal_integration.py`;
- `.github/workflows/champion-pit-terminal-closure-stage2.yml`;
- `.github/workflows/champion-pit-terminal-integration-plan.yml`.

## Phase 12: final causal verification

Run a clean replay from authenticated inputs after closing the frontier. Require:

- exact source and profile hashes;
- zero unresolved decision-relevant security types;
- zero unresolved decision-relevant identities;
- zero incomplete encountered terminal events;
- strict chronological availability of every admitted input;
- deterministic reproduction of orders and holdings;
- deterministic daily NAV and allocation hashes;
- required 5-, 10-, 15-, and 20-year metrics;
- complete artifact checksums;
- a machine-readable certificate and human-readable report.

Any changed profile, parameter, runtime, dataset, time interval, classification
rule, terminal rule, or execution assumption creates a new certification scope
and requires a new run identity.

## GitHub progress and retention

The chronological replay emits quarter-end strategy and SPY CAGR checkpoints,
year completion, rows processed, and elapsed seconds. These messages appear in
the expanded GitHub Actions replay step.

Every material stage uploads an immutable artifact containing its input
identities, output manifests, evidence ledgers, reports, and SHA-256 checksums.
Record the run ID and artifact digest in the certification decision record.

## Acceptance checklist

- [ ] Frozen profile and execution contract recorded.
- [ ] Canonical package authenticated by digest.
- [ ] Conservative candidate envelope generated.
- [ ] Permanent-security identities used for all joins.
- [ ] Strict-prior retained authority allocated.
- [ ] Remaining classifications reconstructed with cited evidence.
- [ ] Counterfactual sensitivity completed for material uncertainty.
- [ ] Effective decision frontier generated.
- [ ] Cross-sectional cutoff effects proved.
- [ ] Encountered terminal events fully valued.
- [ ] Final causal replay deterministic.
- [ ] 5/10/15/20-year metrics generated.
- [ ] Machine-readable certificate generated.
- [ ] Human-readable report generated.
- [ ] All artifacts and hashes retained on GitHub.

## Restart procedure for a changed strategy

1. Create a new research branch.
2. Freeze and hash the new strategy profile.
3. Point the replay at the authenticated canonical package.
4. Generate a fresh conservative path envelope.
5. Reuse retained authority by permanent security ID and strict-prior date.
6. Build a new residual classification worklist.
7. Run bounding sensitivity before manual research.
8. Research only the material residual set.
9. Run the reviewed reconstruction and emit its decision frontier.
10. Close encountered terminal events.
11. Run final causal verification.
12. Retain the certificate, report, ledgers, source, manifests, and hashes.

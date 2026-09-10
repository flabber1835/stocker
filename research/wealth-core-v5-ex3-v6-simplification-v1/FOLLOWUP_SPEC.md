# Combined simplification candidate — one additional replay

The user authorized this follow-up after the original ten slots were exhausted: “Ok test the simplification candidate.” Budget: **one additional full-PIT replay start**. Original slots and their permanent claims remain consumed. Tracking: #349 / PR #350.

## Candidate fixed before replay

Compose selective peer evaluation, bounded Native/EX3 decision counters, one-stage fragile recovery at 55% for ten healthy closes with the frozen prior-close check timing, and removal of SPY rebound release for both recovery episode and divergence latch. Preserve cross-surface recovery. Exposure levels are 0%, 55%, 100%. Wealth Core and execution economics remain frozen.

Composition starts from the validated bounded-counters transformation, changes the Native ramp completion threshold from two stages to one, disables CandidateA's rebound predicate and substitutes the validated selective peer function. An AST guard restricts changes to Native, CandidateA and dynamic_peer_breadth. The standalone mapping arm and twenty-close ramp are alternative treatments excluded from this candidate definition.

## Comparator and acceptance

Reuse the successful baseline artifact `simplification-baseline` from Actions run 34436432038, source f769623e86e949c35a0ddf7dc7df29744c298eae. Verify its file checksums, source/dataset identities, Core hashes and baseline record before claiming the additional slot. Retain actual historical source identity in every comparison. Reuse the exact frozen runtime, generated oracle, broad PIT universe and 5,032-session measurement horizon of the original experiment.

Acceptance remains the preregistered all-window screen: absolute CAGR difference <= 0.25 pp/year, drawdown deterioration <= 1 pp and absolute ending-multiple difference <= 5%, independently over trailing 5/10/15/20 years. Report allocation differences, NAV path divergence, turnover, tail risk and underwater durations. Passing individual arms does not establish combined parity.

## Budget and evidence

The single new claim is `refs/heads/research-budget/simplification-candidate-v1/slot-01`. A claimed start remains charged if replay fails. Duplicate starts fail closed. Staging, synthetic preflight and analysis of retained tapes use zero replay slots.

A dedicated workflow launches only on FOLLOWUP_LAUNCH.json changes. It downloads the existing baseline, runs synthetic composition tests, executes one candidate replay and posts its complete or incomplete comparison to #349. Generated replay driver, generated strategy source, baseline provenance, daily tape, result JSON, checksums, logs and summary are retained in the Actions artifact. Production promotion requires separate review.

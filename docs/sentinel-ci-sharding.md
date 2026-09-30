# Sentinel safety CI sharding

## Decision

Build one runtime image and its disposable test lens for each exact source
commit. After that shared build, run twenty independent Sentinel-safety workers:
four ordinary Sentinel shards, four rolling Sentinel shards, one contention
worker, one status/memory worker, the existing warmup, automation, champion,
operator, Wealth Core, and mutation workers, and four Sharadar replay shards.
The account-wide GitHub runner limit can queue workers; twenty is a useful
maximum, not a requirement to keep every runner busy. The protected `main`
run uses the same test partition as a pull request and remains the only source
for image publication.

The ordinary and rolling shard planners enumerate tracked test modules from
the exact checkout. Ordinary modules are partitioned by a stable path hash;
rolling modules are assigned by deterministic estimated runtime weights so
the slow daily, runtime, initialization, restore, and recovery modules do not
land in one worker. Future modules enter the plan automatically. Automation,
warmup, contention, status/memory, and rolling modules remain outside the
ordinary plan. The planner must refuse an empty shard, duplicate or missing
module, unexpected module path, or changed shard count.

Every worker runs the production code from the single built test lens without
rebuilding it. Its receipt binds the same source commit, tree, workflow run and
attempt, runtime image ID, test-lens image ID, and exact JUnit bytes. The
assembler requires all twenty lane receipts, merges all Sentinel JUnits with
duplicate and non-pass refusal, and re-collects the protected test-owner union
against the exact image. A missing new test, skipped test, or omitted worker
cannot produce certification evidence. A PR failure remains a refusal, and
protected publication still requires a successful exact-commit `main` run.

The million-row cold-seed/warmup remains one worker with its shared fixture.
Splitting it would duplicate expensive acquisition and change the scale claim.
Whether to run that scale qualification on every PR is a separate decision;
this change preserves its pre-merge gate.

## Expected effect and limits

The last successful Sentinel-main lane spent about thirty minutes on ordinary
tests, six on contention/status, and eighty-two on rolling tests. The proposed
four rolling groups project to roughly twenty minutes each from that measured
run. The existing warmup (roughly thirty-six to thirty-nine minutes), shared
build, and evidence assembly then bound the best case. CI speed is not a new
certification claim; queued runners, variable database work, or new slow tests
can extend the wall time. Failure diagnostics must name the precise shard.

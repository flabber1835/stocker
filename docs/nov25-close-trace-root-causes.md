# November 25 close trace follow-up

The November 25 close published version 30 at 21:15:27 UTC. The SHADOW
attestation arrived at 21:18:08, and the scheduled Friday plan was ready at
21:22:46. The earlier expected-key index fix was already installed. The trace
recorded repeated PAPER refresh callbacks before publication, a preparation
retry for `EVIDENCE_COVERAGE_ADVANCE_REQUIRED`, and two database-wide temporary
file bursts. Those counters did not retain the statement or backend.

For an exact, typed closing-data wait with a captured source completion hint,
space full retries at least one minute apart when that still fits inside the
original close and producer deadlines. The existing light poll can wake
immediately when the matching publication or attestation commits. Missing hints,
other failures, and a nearer deadline retain the ordinary retry policy. Every
callback that runs still checks the actual source, authority and fence.

The mirror advance first consumes changes and then checks newly due plans.
Checking a plan appends a signed dependency-row event, so the first advance can
return pending solely because its own events have yet to be authenticated. Under
the same existing lock and unit budget, continue into those events within the
same advance. Consume and authenticate each event through the existing path.
An exhausted budget still persists only its real contiguous prefix and never
grants readiness. A mismatch, invalid row, or missing event keeps its refusal.

The daily feature adapter currently orders the expanded normalized price view
by security across the full 300-session window. Stream through the existing
physical reader in stored session order, bounding each ordered query to one
session for shared storage. Keep the canonical feature formula, its exact last
127 signal and last 20 liquidity observations, and the same protected-price
histories. Store signal tuples compactly per security and produce final signals
in the old identity order. Validate every returned row even when it contributes
no retained value. The exact economic transition must retain the prior input
hash and outputs. Independent canonical content validation and split/price
domain checks still run. Historical receipt hashes and all existing ports
remain independently verified.

The publication's retained action-price lookup also sorts its multi-session
view. On the retained November 25 price blocks and retained action-price IDs,
the private query wrote a 58 MiB sort file, matching the smaller historical
burst in size. Traverse actual stored days in order, and look up the same
identities from each day's logical relation. The existing merge with requested
action dates still uses strictly earlier prices, the same identities and
price domains. The legacy scalar query stays on its existing ordered path.
Seal the reader change together with the unchanged DDL, view and action
compiler semantics. The trace did not record the original query text or PID.

Measure the current whole-window sort and the bounded reads with actual retained
price rows in private PostgreSQL. Compare feature payloads and hashes against the
retained compiler using multiple securities, gaps, absent final bars, and a
symbol change. Test a due mirror recheck with its generated change, a tight page
budget, and bad history. Test prompt wake on each producer milestone and normal
fallback at deadlines. A reproduced sort explains an avoidable query cost; the
historical counters alone cannot assign every byte of either observed burst.

# Joint acquisition, startup and daily-operation rehearsal

The October 1 NAS failure exposed a composition gap: a large price corpus and
a large reference download had been tested separately, but full reference
storage had not been exercised through publication and the later readers.

Add a manually invoked local campaign outside routine CI. Use the real HTTP
acquirer, PostgreSQL schema, operational publisher, GO financial proofs,
canonical 126-session formation, durable shadow and automated daily refresh.
Follow those with the existing simulated paper preparation, execution and
reconciliation membrane. Retain the same database across consecutive sessions
and reopen connections to exercise restart and duplicate-wake behavior.

The representative profile combines 6,000 active securities, 30,000 ticker
records and 1,000,000 distinct historical action records. Startup contains
426 sessions; daily acquisitions contain 300. Synthetic actions outside the
decision window provide realistic reference pressure without manufacturing
unknown corporate-action economics. Separate focused economic fault tests
remain necessary; this is not a replacement for them.

PostgreSQL gets 1 GiB RAM and 2 GiB combined RAM/swap, matching the reported NAS
container. GO/formation and the shadow service's daily acquisition get 4 GiB RAM
and two CPUs. Paper preparation/execution runs in a separate persistent automation
process with its production 2 GiB RAM and one CPU limit, reading the same database.
The provider is a separate 512 MiB container. All
containers use an internal network and disposable volumes.
No actual provider credentials or broker endpoints are used. Keep per-phase
logs, cgroup counters, exact source/image identities, row counts and verdicts,
including failed runs. A missing phase is incomplete, never a pass.

This campaign exercises the production financial/automation functions; it does
not issue a deployable certificate. Its explicit fixtures are the clock,
provider, reviewed runtime/certificate authority and broker. The existing
canonical shell GO harness separately tests checkout/image promotion, backup
media and certification orchestration. Results must distinguish these scopes;
neither local campaign certifies NAS hardware or actual provider/broker behavior.

Acceptance requires actual large references stored and read through the new
TEXT representation, complete publication, GO parity/readiness/database checks,
formed startup matching preview, daily retained-state continuation, duplicate
wakes without duplicate publications/commands, reconciled simulated orders and
successful restart reads. Automation coverage also includes its scheduler,
lease and recovery tests. Do not infer that passing isolated storage alone
satisfies this acceptance. Run a small protocol profile first, then the large
profile; batch findings and their targeted regression fixes before publication.

## Findings and storage decision

The large campaign reproduced a second PostgreSQL OOM in
`sentinel_acquisition_parts.reference_payload`, before snapshot publication.
Apply the same 1 MiB JSONB / 256 MiB bounded canonical TEXT policy to reusable
acquisition reference parts. Add a nullable TEXT column, preserve existing JSONB
rows and logical content hashes, enforce exclusive representations and the TEXT
checksum in SQL, and verify parsed content on reuse. This covers startup and
daily acquisition without raising database memory limits. Existing ownership,
immutability, successor reuse and retention rules remain authoritative.

The small campaign also found that retained-action publication mapped dates
outside its coverage before filtering them, causing pre-1997 source records to
fail calendar conversion. Filter raw dates against the exclusive lower session
and inclusive upper session first. Daily correction checks keep the original
retained basis, not just the latest price-window start.

The canonical shell fixture still supplied roughly 385 sessions for a selected
426-session startup. Its source axis now derives from the selected formation
window plus one session for the pre-GO seed, rather than 560 calendar days.

## Running locally

Build from this checkout with the existing dependency test image available:

```sh
docker build -f tools/operational_rehearsal/Dockerfile -t sentinel-test:joint-rehearsal .
python -m tools.operational_rehearsal.runner --image sentinel-test:joint-rehearsal --commit "$(git rev-parse HEAD)" --small --output artifacts/joint-rehearsal/small.json
python -m tools.operational_rehearsal.runner --image sentinel-test:joint-rehearsal --commit "$(git rev-parse HEAD)" --output artifacts/joint-rehearsal/full.json
```

The host runner uses only Python's standard library and the Docker CLI. It
records the resolved image IDs and the worker's actual source digest; the commit
argument alone is not proof of the image contents. It removes only its uniquely
named containers, network and volumes, retaining the report and logs locally.
Allow up to six hours for the large profile. The runner requires cgroup v2 for
measurements and is a local Docker Desktop/Linux tool, not a NAS deployment step.

The separate-process small campaign passed in 244 seconds with 12,780 initial price rows,
100 ticker records and 500 actions. It completed GO financial proofs, 126-session
formation with a lost acknowledgement halfway through, restart, two daily
top-ups and three paper cycles containing 60 filled simulated commands. Duplicate
wakes created no additional publications or orders. The separately capped paper
process peaked at 124 MB; sampled PostgreSQL working memory peaked at 135 MB.
This establishes protocol
coverage; it does not establish full-size resource safety.

Targeted regression validation also passed: 68 automation scheduler/composition,
lease and recovery tests; 89 acquisition reuse, retained history and canonical GO
fixture tests; and 20 feed-schema tests. All 39 acquisition and 16 retained-history
mutations were killed, including the new storage bound/checksum and calendar-bound
mutations. The size-bound child was repeated after its source matcher was tightened
and failed at the intended missing refusal.

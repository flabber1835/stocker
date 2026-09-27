# Acquisition reliability: design and certification

Certification here means scrubbing the production code and proving small,
isolated behaviors, then testing their composition. It does not introduce a
signed certificate, an approval ceremony or an economic claim. The immediate
NAS failures exposed two composition defects: rolling preflight stopped at the
first pending export, and foreground GO abandoned a durable WAIT_SOURCE job.

## Decisions before implementation

Keep the existing PostgreSQL job, lease, fencing, checkpoints and publication
transaction. A single source preflight sweep checks every required export,
collects fresh descriptors, and defers only export-generation pending statuses
until the end of the sweep. Authentication, malformed data, network cooldowns
and other errors still stop the sweep; pending generation is not permission to
ignore a provider-wide throttle. Requests and downloads remain sequential, with
concurrency one, avoiding extra NAS memory and provider load. No downloads begin
until every descriptor is ready and SEP refresh generations agree.

The rolling worker remains one bounded attempt. Pending exports return it to
WAIT_SOURCE with no owner. Foreground GO drives that same job until publication
or refusal; scheduled runtime callbacks retain their one-attempt behavior and
existing scheduler retries. GO never enqueues another job inside its retry loop. PostgreSQL's
absolute deadline and next-retry/lease timestamps govern the wait, with short
sleep slices for cancellation and source-final target checks. No transaction or
corpus writer lock is held during sleep. Restart attaches through existing exact
request coalescing; reclaiming a lease never extends the deadline. Expired or
terminal attempts remain retained; a later explicit invocation may create a
successor. Changed source-final target refuses the foreground operation.

Do not retry an arbitrary exception merely because an old job looks waiting.
Only recognized source deferrals, connection/writer contention and JobWaiting
can enter the resume path, and only when durable state permits recovery.
Interrupted operators exit immediately. Integrity/generation changes refuse.
Transport failures and retryable HTTP failures that exhaust one network slice
must remain distinguishable from authentication/protocol errors. Use a typed
source-unavailable deferral, handled by the same durable retry mechanism. Do not
classify arbitrary provider exceptions by parsing their error strings.
The existing job budget (one hour by default) remains distinct from GO's outer
two-hour process watchdog: diagnostics name the remaining job budget, and the
watchdog does not imply an entitlement to spend two hours waiting for a provider.

Source descriptors are re-observed after a wait; authenticated URLs are not
durable checkpoints. Verified downloads retain the existing checksum/cache and
generation checks. Existing reference corroboration, worker fencing, publication
CAS, atomic commit and lost-ack recovery remain mandatory. Waiting cannot grant
readiness or broker authority. Startup remains 379 price sessions; ordinary
refresh remains 300. Full ACTIONS reference coverage is unchanged.

## Practical certification work

Use isolated tests for export sweep ordering, pending/ready combinations,
provider errors, deadline/lease calculations and foreground retry decisions.
Use real PostgreSQL for WAIT_SOURCE ownership release, unchanged deadlines,
restart, competing claims, checkpoint changes and publication atomicity. Exercise
the GO preparation caller with the actual rolling source and publisher, mocking
only provider responses and the clock/sleep boundary where necessary. Retain
existing cache-corruption, expired-link, source-revision and lost-ack tests.
Break new guards deliberately and show the corresponding tests fail.

Report concrete findings, commands and residual limits here. Passing local tests
does not establish provider latency or NAS resource headroom. Actual NAS cold
acquisition, interruption/resumption and a subsequent refresh remain deployment
qualification; they are not prerequisites for calling the local implementation
tests successful. No economic results or strategy fixtures change.

## Scrub findings and limits

- Fixed the rolling preflight's first-pending abort; both bounded acquisition
  implementations now share the export sweep.
- Fixed foreground GO abandoning a durable WAIT_SOURCE job. Retry timing comes
  from the database clock, waiting holds no transaction, and no retry creates a
  successor job. Existing committed receipts win over an elapsed acquisition
  deadline when another worker publishes while the foreground caller waits.
- Distinguished exhausted transient HTTP/transport retries from permanent
  request errors, so the existing worker records RETRY_WAIT instead of REFUSED.
- Kept runtime scheduler callbacks one-attempt; only foreground GO owns the new
  waiting loop. Preserved source-refresh checks, cache checksums, immutable
  checkpoints, source-final target checks and final publication fencing.
- Resource qualification remains incomplete: transfers are sequential and the
  cache retains at most 64 completed files, but compressed files and decoded rows
  are buffered in memory and there is no aggregate byte quota. Calendar bounds
  and file counts are not a RAM bound. NAS measurement and a measured streaming/
  byte-budget design remain necessary before claiming resource certification.
- Status polling retains the existing provider delay (30 seconds by default).
  A provider-wide Retry-After takes precedence. No extra thread pool or polling
  service is added; the foreground driver checks state/cancellation in at most
  ten-second sleep slices.

The dedicated guard-removal runner is executed in the existing CI mutation lane.
New tests belong to the existing Sentinel test owner; no new evidence authority,
certificate format or operator approval is introduced.

## Local validation

Run in the existing PostgreSQL-capable Python 3.12 test image with networking
disabled. Counts overlap; these are targeted regressions, not a full-suite claim.

```text
python -m pytest tests/sentinel/test_export_readiness.py tests/sentinel/test_acquisition_wait.py tests/sentinel/test_rolling_go_inputs.py tests/sentinel/test_rolling_snapshot_publisher.py tests/sentinel/test_rolling_snapshot_jobs.py tests/sentinel/test_source_acquisition_lifecycle.py -q --tb=short -p no:cacheprovider
93 passed (initial waiting implementation)

python -m pytest tests/sentinel/test_export_readiness.py tests/sentinel/test_acquisition_wait.py tests/sentinel/test_sharadar_snapshot_export.py tests/sentinel/test_bounded_operational_feed.py tests/sentinel/test_go_source_final_preparation.py tests/sentinel/test_go_preparation_attempts.py -q --tb=short -p no:cacheprovider
70 passed

python -m pytest tests/sentinel/test_source_acquisition_lifecycle.py tests/sentinel/test_sharadar_snapshot_export.py tests/sentinel/test_sharadar_secret_redaction.py tests/sentinel/test_rolling_snapshot_publisher.py tests/sentinel/test_go_source_final_preparation.py tests/sentinel/test_go_preparation_attempts.py tests/sentinel/test_go_readonly_data_preflight.py -q --tb=short -p no:cacheprovider
93 passed (after transient classification change)

python -m pytest tests/sentinel/test_acquisition_wait.py tests/sentinel/test_export_readiness.py tests/sentinel/test_rolling_go_inputs.py::test_go_waits_for_all_exports_then_publishes_same_job -q --tb=short -p no:cacheprovider
18 passed (final foreground driver, including concurrent publication)

python -m tools.sentinel_acquisition_falsifiers
8 mutations killed by behavioral failures, including bypassing the GO driver
```

Changed host entry scripts also compile on Python 3.8.15. Real provider waiting,
actual process termination on the NAS and measured peak resources remain outside
these local results. Existing tests cover simulated interrupted workers and
verified cache reuse in a fresh process; those are not a claim of NAS SIGKILL
qualification.

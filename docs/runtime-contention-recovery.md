# Recovering from ordinary runtime lock contention

Local functional validation found that PostgreSQL advisory-lock contention can
escape the shadow worker as an unhandled exception or a terminal refusal. The
supervisor then persists its integrity latch, although releasing the competing
reader/writer would have made the next attempt succeed.

## Decision before implementation

Distinguish failure to acquire a corpus lock from the broader `CorpusBusy`
contract, which also reports a writer that never acquired its required lock.
Only an actual failed nonblocking acquisition raises `CorpusLockUnavailable`.
It remains a `CorpusBusy` subtype for existing publication/acquisition callers.
Missing ownership stays a refusal; do not infer transience from error text.

The existing behavioral writer's `WriterLockUnavailable` and the new corpus
contention type are local dependency availability failures. Both shadow and
paper callback classification preserve this distinction. They release their
transactions and retry through the existing scheduler/supervisor without
issuing strategy or broker authority, resetting state, extending a job deadline,
or latching an integrity failure. Arbitrary errors and integrity wrappers must
not inherit retry permission from an earlier transient cause.

The acquisition worker must also preserve the existing database-availability
classification when recording a failed attempt. A query cancellation,
serialization failure, or database outage is not evidence that the frozen
request is invalid. Where the connection and lease still permit recording,
persist `RETRY_WAIT` with the existing bounded delay and absolute deadline.
Permission errors, invalid source data and lost ownership remain refusals.

Public shadow runtime wrappers preserve direct, recognized database availability
and lock-contention exceptions instead of relabelling them as integrity refusal.
Already classified integrity exceptions remain terminal even when their cause
was transient. The existing fail-closed callers still receive no result or
authority while a dependency is unavailable.

Validate actual PostgreSQL reader/writer exclusion, production worker exit
semantics, recovery after lock release, and unchanged durable state while held.
Exercise the real rolling service as well as the smaller classification seams.
This is local functional evidence, not provider, NAS, or economic certification.

## Local results

The original code failed seven contention cases, including the actual rolling
service returning terminal exit 2 where the supervisor requires availability
exit 12. A separate real `statement_timeout` reproducer confirmed that an
acquisition attempt was incorrectly persisted as `REFUSED`.

After the fixes, this targeted command passed **126 tests**, using the existing
Python 3.12 test image and CI's separate `/app/sentinel`, `/work/tests`, and
`/work/repo` paths:

```sh
python -m pytest tests/sentinel/test_runtime_contention.py tests/sentinel/test_dependency_recovery.py tests/sentinel/test_shadow_service.py tests/sentinel/test_rolling_snapshot_publisher.py tests/sentinel/test_corpus_publication.py -q --tb=short -p no:cacheprovider
```

The **16 tests** in `test_runtime_contention.py` also passed against isolated
PostgreSQL **16.14**, image
`postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b`.
Only the test cluster fixture was redirected to that server. Production schema,
locking, publication, acquisition, worker, and canonical startup code ran
normally; provider and reviewed-authority fixtures stayed synthetic.

Four deliberate mutations each produced the expected behavioral test failure:
broadening retry to missing ownership, terminating database retries, wrapping
database availability as integrity refusal, and treating a missing acquisition
lock as retryable. Syntax checks passed for all ten changed Python files.

The tests establish retry classification, unchanged state while contended,
same-job/deadline recovery, and no duplicate startup authority or broker rows.
They do not establish actual provider latency, NAS filesystem behavior, runtime
resource headroom, or economic certification.

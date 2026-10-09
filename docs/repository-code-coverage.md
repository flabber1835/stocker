# Repository code coverage qualification

The repository coverage campaign includes all tracked non-test Python and shell
source: Sentinel, Wealth Core/shared, deployment scripts, tools, research,
audits, and executable reference code in documentation. Tests and test fixtures
are measured as consumers, not counted as application source. Historical and
research programs remain visible even when they are not production imports.
CI helper libraries and executable qualification drivers under `tools/` and
`scripts/` remain source, including files whose names start with `test_`.

The inventory is bound to an independently fetched main revision and the exact
working-source hashes. Python statement and branch coverage are reported with
all exclusions disabled, including existing `pragma: no cover` annotations.
Unexecuted files remain in the denominator. Runtime, host, research, and audit
results are shown separately as well as in an aggregate, so an uncovered domain
cannot disappear behind a narrower source selection.
Installed shared-library paths and the identical read-only source used by
research fixtures map to the same repository source identity; both require
the exact source hash before any executed arc can contribute.

Separate pytest processes preserve the repository's suite isolation. Coverage
uses the hash-pinned native tracer in the Linux CPython 3.12 test lens. The
same coverage version's AMD64 and ARM64 wheels are admitted by the test-only
dependency lock, and the lens build checks the native tracer import. The
pure-Python fallback adds instrumentation warnings to child stderr and much
greater timing overhead; it must not be mistaken for a production failure or
used to justify extending production deadlines. Production dependencies and
the deployable runtime do not acquire coverage tooling.

Synthetic subprocesses containing only a sleep and constant status JSON carry
no repository code. Their fixtures remove only coverage's automatic child
startup variable, keeping real process execution, the original deadline,
timeout/refusal assertions, and coverage of the production parent runner.
Real repository programs and callback workers remain instrumented.
The full provider-worker recovery fixture uses its existing production-style
assembly lease and heartbeat configuration. Its 4,000-identity acquisition,
restart, source healing, session-expiry and explicit-kill assertions test
provider recovery rather than an artificially shortened three-second lease.
The independent real-process supervision fixtures retain their short leases,
deadline, heartbeat-loss, process-reaping and acknowledgement-stall assertions.
Expanded instrumentation must not change production lease or deadline policy.

Coverage
data from child Python interpreters and multiprocessing workers are combined
when they can flush evidence. Real SIGKILL tests remain necessary but cannot
promise a final coverage flush from the killed process; deterministic protocol
and OS-failure tests independently cover those paths. Subprocess coverage must
not alter production deadlines, fences, transport, or recovered-book identity.
Empty child coverage databases are retained as empty evidence and contribute
no executed paths. They cannot shrink the inventory or cover a branch. A
database containing line-only measurements remains a hard refusal for the
branch-qualified report, even when other inputs contain branch measurements.
A terminated interpreter can leave an unfinished SQLite coverage header. It
is classified as unflushed empty evidence only for a child-named file with
zero bytes or a readable database containing exclusively coverage tables and
zero rows in every table. Its checksum and classification remain in the report.
Unknown tables, any recorded row, a damaged nonempty SQLite file, or another
filename cannot use this exception; the original parsing failure is preserved.
The reporter classifies those proven-empty child files before calling the
coverage loader, which may try to initialize an unfinished database. All other
counters are loaded from a private disposable byte copy. The retained original
is never opened for writing; a loader that changes its copy cannot contribute
measurements. Read-only evidence and writable evidence have the same admission
rules.

Shell and embedded browser JavaScript require their own execution measurements;
syntax checks, Python coverage of a shell launcher, and browser test counts do
not establish coverage of those languages. An unmeasured language is reported
as unmeasured, not as 100 percent.
The inventory records the panel renderer's embedded JavaScript as a separate
language obligation bound to that source path and hash. A manifest cannot drop
that obligation merely because every Python line in the renderer executed.
Browser execution fixtures assign the actual rendered script a content-hashed
V8 source name. Raw block counters remain bound to those exact script bytes;
the refresh and notification controllers are measured separately. Deliberately
broken refresh and notification-polling variants have different identities and
cannot add coverage to their intact controllers.
Docker build and workflow definitions remain separately verified execution
contracts; their structural tests are not converted into invented source-line
percentages.

Coverage is a path-execution measure. Meaningful assertions, deliberate broken
guards, isolated PostgreSQL recovery, and the existing financial invariants
remain required. No golden repinning, excluded source, weakened guards, dummy
execution without assertions, or irreversible host experiments may be used to
manufacture 100 percent. External broker behavior and actual deployed paper
execution remain separately observed evidence.

For the current local deployment, installation is held until the requested
coverage qualification is completed or the operator explicitly changes that
gate. The admitted backup owner, original financial database, account binding,
and fenced paper state are preserved while the campaign runs.

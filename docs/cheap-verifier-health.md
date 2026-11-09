# Keep verifier heartbeat checks out of financial imports

Decision before implementation, November 7. Docker invokes
`python -m sentinel.panel.verification_service --health` every ten seconds with
its existing five-second command ceiling. That entrypoint imports the financial
verifier, sources and their large dependency graph before dispatching a check
which only needs two local heartbeat timestamps. Retained healthy executions
take approximately 3.5–4.4 seconds. This repeated startup cost is avoidable and
competes with the work being supervised.

Dispatch the exact `--health` command before third-party or financial imports.
A standard-library-only module owns the two existing heartbeat paths and the
unchanged predicate: both timestamps must be parseable, nonfuture and at most
45 seconds old. The long-running verifier and operational publisher use those
same path constants. The normal Python `health()` API delegates to the same
predicate while retaining caller-selected paths for existing tests.

Do not change Compose commands, role identities, heartbeat producers, readiness
receipts, timeout, startup grace or restart policy. This removes dependency
startup from each disposable probe; it does not claim a missing heartbeat is
healthy. The separate mismatch between successful-publication readiness and
process liveness remains visible for a later protocol decision. The initiating
branch of the historical startup incident is unproved because its failed Docker
Health.Log was not retained; do not label this correction as retrospective proof.

Qualify both original heartbeat boundaries and malformed/missing inputs. Exercise
the actual module entrypoint with financial/third-party imports forbidden, and
an executed removed-dispatch falsifier. Measure cold negative-probe cost in an
isolated resource-bounded container, without probing or faulting production.

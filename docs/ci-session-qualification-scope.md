# All-hour CI and current-session recovery evidence

Decision: 2026-10-24, before implementation, following the owner's restoration
of backups, CI and reviewed PAPER releases. `sentinel.complete` is an all-hour
software owner. Its complete tracked collection must execute with zero skips;
neither the owner verifier nor its JUnit acceptance is relaxed.

The whole-worker scenario added during live preparation deliberately uses real
service-loop UTC, host/PostgreSQL skew sampling and database leases. Its original
financial/authority/observation/calendar clocks remain explicitly synthetic.
Its generated source must name the actual current closed-session obligation,
and the real execution wake must still be future so new submissions can be
shown deferred. During an open session that finite pre-open profile is genuinely
unavailable. A calendar-dependent pytest skip therefore does not belong inside
the all-hour `tests/sentinel` owner.

Keep the fourteen pure process-ownership and positive-order-evidence tests in
`tests/sentinel/test_current_service_recovery.py`, with the same removal
falsifiers. Move the composed scenario, preserving its body and real guards, to
the explicit selector in `tools/current_session_service_recovery.py`. It has one
named manual owner, `execution.current-session-worker-recovery`, registered in
`config/current-session-qualification.json`. This is separate operational
qualification, not a silently omitted CI test or another generic authority
framework. The existing CI ownership registry/verifier is unchanged.

A small runner validates that one finite registry and selector, refuses provider
credentials, requires the existing independently owned private PostgreSQL 16
context, and uses actual UTC to assess the real schedule before invoking pytest.
An unavailable session yields BLOCKED, never PASS or a fabricated earlier clock.
Direct invocation of the scenario also refuses if the boundary changes after
preflight. A fresh evidence directory owns the invocation; retained claims,
JUnit and logs are never overwritten. PASS requires exactly one passing scenario
with no skip/failure/error/deselection. Receipts bind the actual module/registry,
JUnit and log bytes and retain scope NONE for authority/native/live permission.

The manual module imports only the explicit source-cache isolation fixture and
its existing canonical generated fixtures. It does not opt into any legacy
schema, backup or clock-skew seam. Runtime, broker, calendar, UNKNOWN, funding,
authority, completeness and command guards are unchanged. There is no request to
the running paper account, backup media, backtest or a native broker.

This separation is not an additional installation/activation gate and does not
require waiting for another market open. The owner may run the finite manual
scenario in an available current session; CI still proves the all-hour software
scope and full PAPER installation uses the existing supported release gates.
Original opening timing is a different sealed campaign and is not proved by
either these pure tests or the whole-worker functional scenario.

Run the status command inside the reviewed private test environment:

```text
python -B tools/current_session_qualification.py status
```

When eligible, with the existing explicit private PG16 URL, physical system ID
and ownership token supplied by the host launcher:

```text
python -B tools/current_session_qualification.py run --evidence-dir NEW_DIRECTORY
```

The exact manual pytest selector is stored in the registry and may also be
invoked by the host's frozen-source private qualification launcher. Its result
retains that launcher's original commit/source/physical-container evidence.
The ordinary CI module tests registry identity, both actual-calendar outcomes,
missing-evidence refusal, and preservation of the manual scenario's scope.

# Simplify the automation runtime

The deployed worker builds the base scheduler and immediately replaces it with
the recovery scheduler. Replacement drops the independent authority observer
that is required during a long callback. Select the scheduler class before
construction and pass the complete callback set once. The unattended worker
selects the production recovery policy. The separately supported bounded
operator and rehearsal construction keeps its existing policy.

The scheduler makes one durable retry decision for a callback exception or an
explicit retry result. It uses one transition writer, the existing diagnostic
fields, and the original retry clocks. Publication pin and backup owner failures
retain their own consecutive counters. Corporate actions retain their bounded
recovery policy, and unattended temporary outages can recover without a count
limit. Supervised data and read-only recovery deadlines remain restartable.
An execution timeout schedules immediate reconciliation under the original
command identity. No retry decision proves that a broker send was absent.

Control-only and cycle authority checks share the same validation without
publishing an intermediate verdict. A cycle check publishes one fenced result
for its completed scope. The active control observer still requires successful
verdict publication, and the read-only close wait still publishes nothing.
Keep the idle control observation and the final transport checks at their
existing ownership boundaries.

Alpaca has three address-selection routes into the create-order endpoint. The
existing adapter classes keep their identities and choose their address as
before. The deployed adapter requires the resolved durable asset ID. Share the
request, final transport authority check, and acknowledgement interpretation
after address selection. Preserve order terms, timeout, refusal, rate limits,
and UNKNOWN handling. No authority or broker capability changes follow from
the shared transport implementation.

Qualification runs the selected production constructor and revokes authority
during a bounded long callback. Exercise existing scheduler retry, outage,
backup contention, source completion and uncertain order recovery cases, and
the existing Alpaca transport matrix. Economic identity and retained-source
acceptance remain separately qualified.

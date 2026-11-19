# November 18 PAPER opening execution cost

On November 18, 2026, the installed PAPER opening completed a clean,
zero-command plan in 259.6 seconds. Native
order/position observations accounted for about eight seconds. Host CPU counters
include concurrent work and do not prove a per-function duration. Preserve the
successful cycle and the original ten-minute increase cutoff.

## Same-callback immutable proof reuse

The PAPER execution gateway verifies current dual shadow intent and rederives
the immutable account-sized plan while it owns the execution writer lock and
rolling publication pin. The automation completion path then verifies the same
financial intent again before deciding whether the final observed book has an
actionable delta. The second verifier runs because broker reconciliation and
other writers may have changed its dependencies since the first proof.

Carry only the gateway's private structural-verification scope to its immediate
automation caller in the same callback process. The scope is a performance
hint, never a broker permission or a result that itself proves completion. The
automation completion path reacquires the ordinary writer lock under its still
live rolling publication pin, checks cancellation and current cycle/control
authority again, re-reads the current durable plan identity, and invokes the
canonical plan and shadow verifier and the durable target-projection delta calculation. Reentering the scope requires the
same database connection, original live pin and actual writer-lock ownership.
Every material use rechecks the exact economic row inventory and current
context. A changed or added economic row forces a cold verification. The existing broker,
trial and cash namespace exclusions apply only to immutable structural inputs.
The retained-target predecessor dependency also includes command state: when
its immutable share projection is absent, every basis schema must recheck
whether any command for that predecessor has left `PLANNED` or `SUPERSEDED`.
Command rows are outside the processed-session inventory, so the private
structural scope includes this predicate in the versions of both retained
targets and the enclosing dual sizing proof. A change across the
gateway/completion writer-lock gap invalidates both warm results and runs the
ordinary cold verifier, which refuses an unprojected transported or `UNKNOWN`
predecessor. Fractional bases additionally keep their existing command and
fill row-version dependencies.
Current source, readiness, transport approval, binding, rollout, signed
authority and projection checks remain fresh in their respective verifiers.

Outside this exact operational dual callback, or without an active outer pin,
the completion path uses its original full proof. A failed lock, changed
authority, expired pin, cancellation or verifier refusal cannot become a
successful cycle. The final observed positions/orders and durable target
projection remain the completion authority; a no-order plan does not bypass
them. No cached material crosses a callback, process or installation boundary.

## Bounded stage evidence

Record monotonic elapsed milliseconds for these PAPER gateway stages, including
entry checks, shadow proof, sizing/authority, account/action evidence, initial
projection, broker reconciliation/cash, final projection, executor and final
account evidence. Record the completion proof separately in the automation
callback. The scheduler logs the elapsed time around the terminal transition,
including its fenced row/event write, commit and post-commit reload; the label
does not claim to isolate PostgreSQL's commit call alone. A raised commit has
an unknown durable outcome and the log says only that the operation did not
return. Emit fixed-name stage logs for both successful and exception paths and
attach the bounded timings to successful callback diagnostics. No raw broker
payload, credentials, arbitrary exception text or unbounded series enters a
stage record. Stage timers measure this callback only and are not market-price
or authorization inputs.

The deployed automation worker installs a sink for a dedicated opening-stage
logger at its process entry point. It emits only these fixed timing records
through the supervisor's bounded, nonblocking diagnostic writer to worker
stderr. The worker does not raise the root logger's level or enable unrelated
dependency INFO logs. Failure to format or deliver a timing record is
best-effort diagnostic loss: it cannot change broker, callback, transaction or
UNKNOWN-outcome control flow. A fresh-process worker-entry test must observe a
real terminal transition timing record with default logging configuration.

Qualification must show one cold shadow/sizing derivation when unchanged,
fresh completion checks, and cold rederivation after an economic-row or
context change. Falsifiers must also cover lost pin/writer ownership, changed
control/cancellation, current-plan replacement, projection mismatch and
remaining actionable shares.
Measure elapsed times in isolated tests and retain production-sized latency as
an installed-open qualification to be observed later.

On November 19 the cycle took 175.1 seconds. The gateway took 114.7 seconds
and completion took 4.3 seconds. Measure connection and schema admission,
observation integrity, cycle authority, operational inputs, and plan, pin and
adapter setup individually from callback entry. Emit the duration of a stage
even if it raises. Use the existing bounded timing sink and monotonic clock.
The difference from the durable EXECUTING transition to callback entry also
includes scheduling and process startup. These measurements confer no trading
authority and never change which checks execute.

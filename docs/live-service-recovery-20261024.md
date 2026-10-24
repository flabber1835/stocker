# Whole private-service recovery preparation

Decision: 2026-10-24, before implementation. Extend the current callback-death
qualification to an entire disposable `ProductionAutomation.run` process. This
is offline functional preparation, not deployment, native broker acceptance,
opening latency or live-money authority. The running PAPER services, their
database, the protected backtest and all backup/archive controls remain untouched.

The existing generated current-profile fixture supplies canonical source
publication/formation, actual runtime attestation, a genuine disposable PAPER
certificate and the current protected DAY execution path. Setup explicitly uses
its prospective business clock to create one accepted partial order whose
response is lost. No fake journal entry or manual command outcome is written.
The independent simulated provider retains fsynced order/fill state outside the
worker. Fees, native settlement and real-provider completeness are not inferred.

Run the complete private service loop with actual UTC and its unchanged
host/Postgres clock-skew guard. The source's real latest closed session and the
service's real next-session obligation must match. The inherited `BusinessClock`
remains installed throughout the test, including recovery: financial preparation,
execution, reconciliation, authority validation, observations and calendar-input
module clocks remain explicitly synthetic. Only the outer service-loop clock,
its host/Postgres clock sample and database lease/mutation clocks are real. This
is not real-clock financial-callback evidence. The scenario never moves host or
database time, changes exchange dates, extends a submission window or qualifies
an opening. If the actual next-session execute wake has already arrived, skip
this finite pre-open profile before formation/authority/control activation;
never manufacture an earlier instant. Retained qualification must explicitly
show that the scenario actually executed, rather than treating a skip as proof.
On a weekend the service can positively recover an existing command before its
Monday execution wake, but must not create a new order before that immutable wake.

An external local transport gate blocks a native recovery lookup while worker A's
real supervised recovery callback is in flight. The test retains the exact
worker and callback PID/start-time identities, kills only its owned worker with
a Linux pidfd, and verifies that production parent-death supervision also kills
the callback. The provider and PostgreSQL remain running. Let the real finite
database lease expire; never rewrite or release the dead worker's lease. A new
whole worker B must acquire a greater fence and recover the same key, quantity,
limit, DAY terms, funding basis and outstanding principal reservation. A separate
transport outage must keep uncertainty unresolved without a second order POST.
After positive observations return, recovery records partial/final executions
exactly once and defers any remaining new submissions to the original wake.
Verify the actual PostgreSQL fill journal against both original simulated native
activity identities, independent expected SHA256 fill keys and every quantity,
price, client/order identity and timestamp. Provider totals or a cumulative
command quantity alone do not establish durable exactly-once accounting. The
last complete worker must stop normally with exit zero and its STOPPED receipt
before any exceptional cleanup fallback.

The private process owner accepts only its direct child and its original Linux
start ticks; signal through its opened pidfd. An in-memory copied-function
falsifier removes each parent/incarnation comparison and observes that the same
public bad-identity refusal assertion fails. It cannot target the test process,
provider, an arbitrary PID, a production service or a process group. Teardown
stops/reaps only owned processes and withdraws control in the newly generated
database. It does not reset/prune Docker or WSL or restart PostgreSQL. Failure
evidence is retained before private cleanup, with no exception payload or secret
environment dump.

This deliberately narrower proof does not establish a powered-off laptop's
recovery, complete-basket execution in a real exchange session, automatic Docker
Desktop relaunch, physical database recovery, native corporate-action accounting
or live activation. Those remain separately named acceptance gaps.

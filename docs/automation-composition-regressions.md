# Automation callback composition regressions

The automated assembly gate drives the real `ProductionAutomation` callbacks
through `AutomationService`, PostgreSQL cycle/control tables, canonical paper
preparation, the execution gateway, command journal, and read-only recovery.
An acknowledgement or accepted-but-lost response must remain nonterminal until
fresh broker evidence proves the fill. Recreating the runtime and database
connection must not duplicate transport. Kill/revocation must stop new transport.

This bounded test uses an explicit synthetic strategy/source fixture, a test
certificate verdict, deterministic exchange time and the existing simulated
broker. It does not replace callback return values, SQL, the executor or
reconciliation. It is not signed-certificate certification, a Sharadar feed
certification, an Alpaca wire test, or a deployment of the unattended process.
Those boundaries retain their separate gates. In particular, a passing assembly
test is not evidence that the entire authorized NAS automation deployment has
run end to end. The full GO/deployment campaign remains necessary for that claim.

Missing PostgreSQL must fail this regression, never silently skip it. The
scenarios run automatically in the existing Sentinel test owner on every PR.

The worker source-recovery regression additionally launches the actual
`automation_worker.main` process and `RecoveryAutomationService`, with real
callback child processes, leases, notifications and durable wake times. A
local HTTP provider withholds a rename pair while returning restated prices.
The worker retains its last publication, persists the failed identity, performs
small probes beyond its configured attempt count, is killed and restarted,
and then recaptures and publishes through canonical ingest when the provider
heals. A separate simulator process retains broker orders across callback and
worker deaths, including an accepted order whose response is lost.

PostgreSQL has a real private WAL archive and is restarted during setup. This
test still uses the explicit synthetic strategy, certificate verdict, readiness,
market clock and pre-open authority fixtures. Its bounded capture invokes canonical seed
replay; it does not contact the Tables Exporter or run historical certification.
Those exclusions must accompany any end-to-end claim. Recovery, missed-open and
kill-during-source-wait scenarios run on every PR; missing PostgreSQL is a
failure. Actual deployment against NAS media, Sharadar and Alpaca remains a
separate validation.

This worker run exposed a pre-existing notifier mismatch: durable transitions
nest retry metadata under `diagnostic`, while live enqueue and crash
reconstruction previously read only top-level fields. Both readers now accept
the canonical nested event and retain compatibility with older flat events.

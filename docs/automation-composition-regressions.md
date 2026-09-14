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

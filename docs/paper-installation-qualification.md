# Paper installation qualification — 2026-10-04

Base: `38cbc4edfd210bb5a69edae02975ea4e3b2dcdb8`.

The certified runtime completed the cold, real Alpaca/OpenFIGI GO in 2,745
seconds. Wealth Core parity, market-data readiness and database financial health
passed; the result was SHADOW_GO and DUAL_RUN_GO. Provider acquisition recorded
no repeated download components. This establishes GO on that release, not a
completed paper installation.

Actual paper installation then refused Sunday identity resolution before any
order transport. A subsequent shadow installation exposed contention with the
recurring backup owner. Both attempts remained fenced. The cold reset also
retained a previous database's UI health projection; the existing missing-origin
guard correctly refused it. The matching prior projection was archived after
verifying it against the retained supervisor-state archive. No financial pending
attempt or critical latch was discarded.

The correction covers three production defects:

| Boundary | Correction | Evidence |
| --- | --- | --- |
| Account administration | Resolve the exchange session at or before the current New York date. Preserve the next-session bound and actual broker observation time. | All three CLI owners with real rolling PostgreSQL publications; weekend, holiday, midnight, pre-open and stale-publication cases. Composed enrollment also uses the actual read facade, stable-empty proof, binding transaction and certificate consumption. |
| Installer backup | Explicit bounded waiting for the existing canonical target owner, followed by exclusive descriptor verification and a new installer-owned backup. | Real process contention, no overlapping child entry, timeout, invalid arguments, inherited ownership, both bootstrap backup phases, and the actual Bash producer entrypoint. The 3,660-second bound covers maintenance's whole 3,600-second invocation plus cleanup; ordinary backup commands still refuse contention immediately. |
| Failure cleanup | Attempt the durable fence and both service stops independently, preserving the original failure. | Actual public installer class dispatch in child interpreters, with failure at each cleanup boundary. |

Regression tests fail when the original calendar policy, immediate backup
refusal, or coupled service cleanup is restored in isolated test processes.
Tracked source and deployed services are not mutated by these falsifiers.

## Additional local qualification

The remaining software checks exercise provider retries and malformed responses,
OpenFIGI completeness and cached classification reuse, Alpaca action handling,
publication consistency, GO inputs, worker deadlines and heartbeat failures.
Automation checks exercise real SQL, callback processes, lease/fence changes,
activation behind kill, plan reread mismatches, accepted-but-lost order responses,
reconciliation, and restart without duplicate submission. Host checks exercise
Python 3.8.15 and Linux 3.10-style procfs. Backup shell tests also run with tests
and inspected source in separate directories, matching CI's layout.

Final focused runs: 130 calendar/lock/installer tests; 250 provider/GO/supervisor
tests; 156 automation/broker/restart tests; 140 adjacent installer/CLI tests;
18 selected backup-shell/process tests in the separate-directory layout; four minimum
Python host tests. These groups overlap and are not a unique total. A broader
shell/lock run passed 146 cases; its one test needing server-local PostgreSQL
filesystem access was excluded from this disposable network-only fixture.
The certified deployment separately completed actual physical backup and restore
checks; the excluded fixture result must not be reported as passing.

Real certified-adapter GET qualification completed 13 account, clock, position
and order reads, with stable identity and complete observation. Positions and
orders were empty. Non-GET transport was prohibited in that diagnostic.

## Notification installation and monitoring qualification

The private dashboard was running while its sender container had been stopped
for hours. Enrollment correctly persisted requests, but the installer never
started that dependency and the browser reported queueing without a delivery
receipt. Restoring the unchanged certified sender resulted in three current
tests accepted by the external push service (HTTP 201). Three older tests for an
explicitly removed subscription remained dead letters; they are not successful
deliveries.

Every installer mode now starts the panel and configured notification sender,
waits for readiness, checks them before kill-switch release and checks again
after the final backup before retaining success. Failure cleanup keeps the
independent sender running while attempting the financial fence and stops.
The browser reports sender availability and polls a restricted, read-only test
receipt; it distinguishes service acceptance, failure and unreadable status.
Only explicitly cancelled informational device tests leave actionable alert
aggregates. Operational warnings, critical incidents and transport failures
remain visible.

Qualification uses disposable PostgreSQL with the actual public installer
class, dispatcher supervisor/worker processes and dashboard readers. The real
dispatcher test starts a worker, stops it, waits for its heartbeat to expire
using the database clock, observes failure and restarts it. Other cases cover
absent/stopped services, faults after final backup, all installer modes, device
rotation and removal, delivery claim fencing and receipt privacy. Isolated
mutants removing startup, activation or availability checks fail their
regressions. Removing the narrow cancellation filter causes the tests for real
WARN/CRITICAL incidents to fail. Mutants never alter tracked source or deployed
services.

Five Edge Chromium browser tests cover explicit permission/subscription gesture,
sender absence, push-service acceptance, delivery failure and an unreadable
receipt. Their transport responses are fixtures; these tests do not establish
physical iPhone presentation or click delivery. Edge was used because the
cached Chromium executable could not launch on this host.

The final notification/monitoring/installer selection passed 355 tests in
154.82 seconds. It includes the real stop/expiry/restart test and all public
installer service guards. Python AST parsing, browser JavaScript syntax,
`git diff --check` and test-responsibility validation also passed. Exact test
commands are retained in PR #477; the larger earlier groups overlap this one.

Docker probes automation every five seconds, the dispatcher every ten seconds
and the panel every thirty seconds while their containers run. Worker
supervisors also enforce progress deadlines. These mechanisms do not install a
host-level watchdog that restarts manually stopped containers, and a stopped
sender cannot report its own absence through itself. The independent dashboard
can expose its stale heartbeat; the installer now enforces service presence at
the installation boundaries.

## Certified installation boundary recovery, 2026-10-07

The actual certified `edaa258fe409978823fb422d4a0d063a4521c8ee`
installation completed real Alpaca/OpenFIGI GO, reused all price partitions and
the authenticated 126-session formation, and passed physical backup/replay.
It exposed three installation failures: repeated behavioral DDL deadlocked
against notification readers; a configured UUID alias differed from execution's
canonical account number; and ten successful HTTP GET log lines preceded an
otherwise valid empty-account JSON result. The last inspection proved the
correct empty $50,000 paper account, but strict installer parsing refused it.
The UUID configuration was corrected through the supported atomic writer after
GET-only proof of the same account, unused administrative authority was revoked,
and fresh GO passed. Financial state and failed attempts were retained.

The recovery branch routes CLI logs to stderr, changes hot administrative
commands to read-only schema validation, and checks execution's canonical
account subject before enrollment. Review of the later activation path also
found that the hardened override omitted the separate verified-shadow/plan
comparison present in the base installer. That check is restored before any
automation activation. Strategy, input windows, execution sizing, signing,
backup, timing and reconciliation requirements are preserved.

Qualification covers actual HTTP logging in fresh processes, strict installer
JSON parsing, every changed administrative schema gate, real PostgreSQL with
health-reader locks held, and the public bootstrap's dual activation ordering.
Existing focused suites exercise empty-account binding, signed authority,
plan preparation/reread, automation kill/start/release, advancing leader proof,
exact backup replay, service loss before release and after final backup,
session expiry, installation overlays and notification recovery. Deliberately
restoring stdout logging, hot DDL, UUID-alias admission or omitted shadow
reconciliation must each fail its regression by assertion.

A separate GET-only diagnostic using the recovery code made ten actual Alpaca
account/order/position reads. It proved a complete matching empty observation
and clean JSON accepted by the unchanged strict installer parser, with HTTP
logs on stderr. It created no account binding, certificate, deployment GO or
paper authority. Software regressions use isolated PostgreSQL and test signing
keys; they do not activate the actual installation.

The refused deployment remains disabled and killed, with zero account bindings
and broker commands. Its database, sender, UI and certified backup maintenance
are retained. Successful real enrollment, release of paper automation, the
first market cycle and physical iPhone notification presentation remain actual
deployment boundaries, not results of this qualification. Windows reboot or
operation before login remains unqualified.

## Remaining deployment evidence

Local admission and transport fixtures are explicit in the software regressions;
they do not establish actual signed account enrollment or broker execution.
No order was submitted in this campaign. The corrected release still needs
merge certification, its actual signed installer run, and the first real market
cycle with reconciliation. A real future close, fill, or laptop reboot without
login has not been qualified by these fixtures. Paper automation remains
disabled and killed until supported installation succeeds. The existing private
dashboard remains available at its unchanged URL.

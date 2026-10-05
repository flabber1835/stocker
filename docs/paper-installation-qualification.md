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

## Remaining deployment evidence

Local admission and transport fixtures are explicit in the software regressions;
they do not establish actual signed account enrollment or broker execution.
No order was submitted in this campaign. The corrected release still needs
merge certification, its actual signed installer run, and the first real market
cycle with reconciliation. A real future close, fill, or laptop reboot without
login has not been qualified by these fixtures. Paper automation remains
disabled and killed until supported installation succeeds. The existing private
dashboard remains available at its unchanged URL.

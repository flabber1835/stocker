# Unattended operating changes: local qualification

This report covers the operating contract in `unattended-operating-contract.md`.
Base: `a65eb9f731bf30d21d0b67f9dabd1d77a01a7314`. The real financial GO and
worker diagnostic use runtime code
`3ed428e8a6f3121b5390eeca7916d812710141d0`. The final presentation-only delta
adds the `.not-current .dot.ok` CSS rule to remove stale green row dots. It was
checked in an actual browser and the six rendered-controller cases were rerun;
financial modules are byte-identical to the real-GO runtime.

## Scope and limits

The campaign exercises GO preparation, canonical formation and restart,
installation timing, shadow and daily recovery, Alpaca/OpenFIGI acquisition,
backup boundaries, execution pricing and durable command recovery. Wealth Core's
pure transition and the controller's selection/exposure rules are unchanged.
Formation still makes 126 transitions after 299 feature sessions; each decision
uses its own trailing 300 sessions. Starting cash and deployment scaling are
unchanged.

The local real-provider run is a diagnostic against an isolated database and
Compose project. It neither issues a certificate nor grants deployment or paper
authority. Real Alpaca calls are GET-only. Broker mutation tests use simulators
and actual isolated PostgreSQL journals. Actual paper fills, the next real daily
cycle, and recovery after a Windows reboot without login remain deployment
qualification boundaries. Initial formation is not evidence of a subsequent
daily cycle.

## Targeted tests

Python commands below use the production runtime's Linux environment and an
isolated PostgreSQL fixture where required, with pytest dependencies mounted.
They do not introduce a separately deployed test image. Overlapping campaigns
must not be added together as a unique test count.

The main Linux integration campaign collected 282 cases. Initially 280 passed;
the two failures were investigated. Current-information fallback improperly
accepted an unmarked late research publication; it now requires the explicit
operational recovery marker. The process-containment test used a two-second
wall-time assertion under competing load; it now verifies that the child is
terminated and cannot perform a delayed write. Both cases passed in the focused
reruns below.

| Campaign | Result | Coverage |
| --- | --- | --- |
| Timing/schedule/shadow | 60 passed | Closed-session clock and service timing |
| OpenFIGI | 28 passed | Structural identity, cached classification, display-name changes |
| Candidate continuity | 28 passed | Clean contiguous tails without fabricated prices |
| Focused execution | 107 passed | Quotes, funding, bounded increase window and retries |
| Additional pure contracts | 55 passed | Operating boundaries; PostgreSQL case covered separately |
| Final Linux seams | 55 passed | Regular quotes, final submission fence, source revision, research refusal and durable journal |
| Final containment | 75 passed | Automation failure/deadline containment, quote/proof guards, operating contract |
| Final proof regressions | 15 passed | Known-unsent retry, exact command reuse, UNKNOWN protection and READY preflight |
| Corroboration/parser integration | 2 passed | Real producer through host progress parser, READY renewal and preflight falsifier |
| Host progress parser | 41 passed | Bounded parsing and explicit source corroboration phase |
| Adjacent broker contracts | 134 passed | Adapter capabilities, instrument UUID, certification and UNKNOWN boundaries |
| Activation and orchestration | 134 passed | Actual PostgreSQL activation/control, concurrent leaders, leases, restart, source waiting and simulated broker recovery |
| Panel HTTP/presentation | 125 passed | Concurrent readers, bounded last-known HTML, configuration isolation and fresh machine health |
| Browser controller execution | 6 passed | Actual rendered JavaScript: busy, cached, timeout, stale, incomplete responses and guard-removal detection |

The principal integration command was `python -m pytest` with:

```text
tests/sentinel/test_unattended_formation_recovery.py
tests/sentinel/test_alpaca_daily_formation.py::test_full_formation_chain_and_frontier_match_unchanged_loader
tests/sentinel/test_current_window_formation.py::test_selected_formation_go_restart_and_daily_preserve_simplifications
tests/sentinel/test_unattended_installer_timing.py
tests/sentinel/test_unattended_operating_contract.py
tests/sentinel/test_regular_quote_submission.py
tests/sentinel/test_alpaca_revision_recovery.py
tests/sentinel/test_install_causal_vendor_window.py
tests/sentinel/test_env_automation_config.py
tests/sentinel/test_automation_runtime.py
tests/sentinel/test_automation_safety_seams.py
tests/sentinel/test_rolling_recovery.py
tests/backup/test_runtime_backup_authority.py
tests/backup/test_runtime_backup_bounds.py
-vv --tb=short
```

Final focused reruns included `test_regular_quote_submission.py`,
`test_opening_submit_freshness_boundary.py`, `test_guarded_execution_broker.py`,
`test_alpaca_revision_recovery.py`, `test_rolling_recovery.py`, and the
SEND_PENDING/stale-target safety seams. The complete automation safety-seam
campaign was rerun, not just the initially failing containment case.
The final adapter command was:

```sh
python -m pytest tests/v5/test_opening.py tests/sentinel/test_broker_conformance.py tests/sentinel/test_alpaca_certification_boundary.py tests/sentinel/test_issue_209_alpaca_asset_id.py tests/sentinel/test_issue_183_alpaca_hardening.py -q --tb=short
```

Explicit activation and presentation commands were:

```sh
python -m pytest tests/sentinel/test_automation_store.py tests/sentinel/test_automation_service.py tests/sentinel/test_automation_composition.py tests/sentinel/test_paper_activation.py tests/sentinel/test_automation_deployment.py -vv --tb=short
python -m pytest tests/sentinel/test_panel_concurrency.py tests/sentinel/test_panel_plain_language.py tests/sentinel/test_panel.py -vv --tb=short
python -m pytest tests/sentinel/test_panel_browser_refresh.py -q --tb=short
```

The last command executed all six cases with local Node.js, rather than taking
its optional skip for runtimes without Node. An actual browser also loaded the
rendered dashboard, received a deliberately delayed 503, retained its original
values with a non-current headline, recovered automatically, and continued
refreshing after document replacement. Eleven fixture requests recorded a
maximum of one concurrent read. The fixture had no database or broker access.
The final color check observed red dots (`rgb(255, 145, 139)`) while status was
non-current, then green dots (`rgb(128, 228, 178)`) only after a fresh response.

Canonical formation was compared with an independent uncached input loader:
all formation state, chain and frontier outputs matched. PostgreSQL integration
also verified completed preview reuse without another 126 transitions, restart
after committed progress, late state-only genesis, two missed publisher days
with current-information reconstruction, preserved genesis, and the next fresh
prospective decision. These daily recovery cases use deterministic provider
fixtures, not a claim that two real market days have elapsed.

Guard-removal falsifiers detected all five deliberately broken guards: sealed
pretransport proof, fresh-ask affordability, final quote expiry, both staging
backup markers, and contiguous-tail reset. A separate PostgreSQL falsifier
detected removal of the READY publication backup preflight. Mutations were
in-memory test changes; production guards remained intact.

The browser single-request and bounded presentation allocation guards also
passed tests that deliberately removed each guard and detected the regression.

All 65 changed Python files compiled. Static review reported no new pyflakes
findings and `git diff --check` was clean.

The final regression campaign passed **129 tests in 429.77 seconds**, including
the initialized candidate's first worker attestation, unchanged same-session
polling, and the final dashboard styling. Exact command:

```sh
python -m pytest tests/sentinel/test_unattended_formation_recovery.py tests/sentinel/test_panel_concurrency.py tests/sentinel/test_panel_plain_language.py tests/sentinel/test_panel.py -vv --tb=short
```

The rendered JavaScript campaign was rerun after the final styling change:
**6 passed in 0.76 seconds**. These groups overlap earlier counts; they are not
additional unique-test totals.

## Real provider evidence

The first real capture used actual Alpaca and OpenFIGI credentials, with no
Sharadar access. It discovered 13,194 active equities, classified 5,912 common
stock candidates, admitted 5,755 securities and normalized 2,156,651 price bars
from 22 monthly partitions. The capture covered 2025-01-24 through 2026-10-05.
This larger capture supports formation; each individual decision still uses
only its trailing 300 sessions.

The run renewed an initially uninitialized archive, then renewed once at the
financial restore horizon. Its second partition sequence reused all 22 retained
parts under the same job identity rather than downloading the price corpus
again. Publication occurred at 2026-10-06T02:59:27.562096Z, before the retired
03:45 UTC source-clock barrier. Preparation took 1,898,720 ms. Canonical
formation and startup/restart parity passed. Final-code GO results are recorded
below.

The financial-code run at `27057ff743f9249f9b8c9620a59dc691a1a9b198`
passed all five gates: account GET, formation/Wealth Core parity, provider
readiness, database financial health and final account GET. It ran from
2026-10-06T03:21:11Z to 04:09:39Z and renewed one backup horizon. The final
runtime at `3ed428e8a6f3121b5390eeca7916d812710141d0`, local image ID
`sha256:92eb916f3e42e1b37eea8f06b68e56690530428989ca73b46a2227ff43b8990e`,
also passed every gate, from 04:09:45Z to 04:28:37Z. Its preparation returned
`ALREADY_CURRENT` in 49,590 ms. Formation took 943,863 ms and the revision scan
74,562 ms. Changing the runtime code intentionally invalidated the disposable
formation cache; no second market-data download was required.

Real-input initialization subsequently logged `AUTHENTICATED_WORK_REUSED` for
all 126 sessions. Restart preserved the canonical state and record hashes. The
first worker diagnostic initially expected healthy status before the first
attestation poll; that assertion was incorrect. Initialization commits a
candidate, and the worker separately attests it. Failed evidence was retained,
and the corrected check resumed the same candidate without resetting it.

The actual worker's first poll changed health from `RECONSTRUCTION_PENDING`
to `HEALTHY_ATTESTED`. The second poll returned the identical book/record and
appended no duplicate decision. There were zero repeated formation transitions
and zero broker commands. Retained initializer recovery took 5,845 ms; that
measurement is not the duration of the whole worker/restart campaign or a claim
about the next daily cycle.

A real GET to the free `feed=iex` latest-quote endpoint returned HTTP 200 with
valid SPY and BIL response fields at 2026-10-06T04:25:18Z. This proves access and
format, not fresh opening quotes or actual fills outside the regular session.
PostgreSQL reported no OOM and no restarts throughout these diagnostics.

Failed evidence was preserved. No real orders were submitted and the cancelled
certified paper installation was not restarted by this campaign.

## PR #480 CI follow-up

The first GitHub run exposed two composition assertions and one container
fixture that still expected the retired 23:45 clock. They were updated to the
documented exchange-close boundary, including DST, exact close and half-day
checks. No production module changed in this follow-up. The retained legacy
read-only preflight is not called by the production GO launcher; its isolated
container fixture now checks the previous closed session before today's close.

Focused command: **73 passed in 25.85 seconds**:

```sh
python -m pytest tests/production_composition/test_clock_calendar_faults.py tests/sentinel/test_bounded_operational_publication.py tests/sentinel/test_go_readonly_data_preflight.py -q --tb=short
```

Broader command:

```sh
python -m pytest tests/production_composition -q --tb=short
```

This produced **572 passes and one prerequisite failure in 167.31 seconds**:
the runtime contains no `sudo`, which the existing foreign-owner CI test invokes.
The same atomic ownership replacement was separately exercised on Ubuntu:
root created one temporary selector, the normal `bron` process replaced it,
and the new owner, inode, mode 0600 and selected digest all matched. That native
check passed; it is not represented as a passing pytest test. No host sudo policy
was changed. GitHub's corresponding ownership test passed in the first CI run.

The corrected `test_go_probe_runtime_integration.py` also passed against the
real non-root runtime `sentinel-go-local:3ed428e8`, a unique disposable Compose
database and a local override removing its host port. All six read-only marker
checks, import/authentication failures, publication lock exclusion and receipt
ancestry checks passed. This fixture's synthetic legacy export seam cannot
contact a provider and is not real-data acquisition evidence.

The next CI run exposed one production configuration mismatch: the optional
standby automation service still defaulted to the retired 23:45 policy. Its
default now matches the documented validated-closed-session policy and the
primary service. The existing primary/standby parity and configuration-loading
tests catch the old default. This restores the current contract; it does not
claim an actual deployment or failover to a second host.

The worker-expiry fixture now advances beyond the configured execution
deadline, rather than assuming the former three-minute window. Mutation
drivers now refer to the current opening-quote retry tests and the actual
dispatch code seam. They retain the checks that unavailable/transient opening
evidence must remain retryable and that SEND_PENDING precedes broker transport.

The focused Linux/PostgreSQL command produced **30 passed in 54.13 seconds**:

```sh
python -m pytest tests/sentinel/test_automation_process_contracts.py tests/sentinel/test_automation_worker_source_recovery.py tests/sentinel/test_process_death_recovery.py -q --tb=short
```

This used a disposable PostgreSQL 16 server with actual private WAL archival;
the local fixture adapter verifies the runtime backup guard after a restore
point and WAL switch. No deployment database or real broker was used.

`python tools/v5_mutation_check.py` passed: **all 43 mutations were caught**.
The updated `submit-before-send-pending` mutant was separately exercised against
real PostgreSQL. Its process died after simulated broker acceptance, leaving
PLANNED rather than SEND_PENDING, and the intended assertion failed (one failure,
zero test errors). The unmodified process-death test passed in the 30-test run.
GitHub had already caught the other ten Sentinel mutations; the repaired driver
still requires all eleven on the next exact-head run.

Local launcher failures (missing archive support and Windows dependency import
order) were retained and corrected before these successful checks. They were
not counted as production defects or successful mutation detection. All 71
changed Python files compiled with zero new lint findings.

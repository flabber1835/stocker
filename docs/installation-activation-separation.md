# Installation, preparation and activation

Decision: 2026-10-07. Supersedes the combined deployment-success boundary and
source-final installation waits in `ci-certified-paper-installation.md` and
`unattended-operating-contract.md`. Software installation has no trading clock,
broker-readiness, source-readiness or execution-authority prerequisite.

Software receipt finalization rechecks the existing physical backup chain; it
must not invoke the financial post-activation base/semantic-restore milestone.
Required schema migration still proves its exact pre-migration physical replay.
The formed/authorized state's full semantic restore remains exclusively an
activation requirement. During a software-only upgrade, maintenance of retained
financial state keeps its previously admitted runtime/configuration until the
new financial identity is admitted; installing software does not invent source
validation for retained shadow history or authorize a maintenance identity swap.

The installer admits the exact protected CI-certified image independently of a
financial GO ZIP. It verifies source/image identity, preserves the database and
its existing account binding/journal, fences execution, performs only required
backed-up schema migration, starts the operator services and creates the exact
financial service containers dormant. It does not start a source or trading
writer, require a signing key, issue a certificate, prepare a plan, release a
kill switch, or wait for a trading session. Source/activation credentials and
unconfigured alert transports are not installation prerequisites. Configured
operator services still require safe local configuration and process health.
After fencing and migration, independently verified software installation also
atomically selects its signed immutable runtime through the canonical pointer
writer. An old financial GO selector cannot override the newly installed image.
Generic unsigned runtime promotion remains disabled.

Installation ends with a versioned immutable `installation-receipt.json`:
`installation_state=INSTALLED`, `activation_state=FENCED`, exact source/runtime,
requested mode and disabled/killed execution. This receipt is not financial
admission and does not claim a shadow decision, account reconciliation, restored
new authorized state, first cycle or broker mutation. A later activation cannot
overwrite it or revoke the fact that this software was installed.

The public install command may request `--activate-when-ready --mode dual` (or
shadow/paper). Only this explicit request queues automatic activation. A separate
host systemd service owns the activation command, independently of the install
process/terminal/cgroup. The request binds the completed receipt, exact checkout,
mode and private environment file digest; no credentials are command arguments
or state output. A verified service handoff is an activation status, not a new
installation gate. Where systemd ownership is unavailable, installation still
finishes and reports `WAITING_FOR_SERVICE_OWNER` with the supported foreground
activation command. No unowned detached process is a fallback. Host reboot and
no-login recovery are not implied by this handoff.

Activation separately verifies the installation receipt, actual runtime and
unchanged configuration, retains the canonical lifecycle/writer locks, quiesces
financial writers before the supported financial GO, and validates its exact
bundle with the existing immutable/non-temporal financial guards. The sealed
explicit mode request authorizes the coordinator to produce its own GO evidence;
it cannot turn a financial NO_GO into paper authority. An operator-provided GO
ZIP remains digest checked and cannot select different software. No installed
image is rebuilt or promoted during activation.

Existing source-final preparation, parity, lineage, ownership/enrollment, host
offline signing and killed-first activation remain canonical. Source work uses
bounded existing acquisition/checkpoint recovery; no parallel book is added.
Missing configuration/account readiness or a missed prospective window is an
activation wait, with execution disabled/killed. A bounded attempt may yield to
the coordinator's next attempt; it must preserve the installed broker-free
worker and its state. Unknown/corrupt identity, lineage, JSON or financial outcome
still refuses and fences. Structural refusal is never treated as an availability
retry. A fresh actual decision determines the next eligible execution session;
an installation during an open session cannot backdate or submit that session.

Process readiness and financial readiness are distinct probes. The host startup
probe checks the live supervisor, critical latch and exact pending-worker proof;
it does not require a prospective financial projection. The existing financial
health/attestation remains mandatory for activation and stays red while waiting.
The formed/authorized state's coordinated full semantic restore remains before
kill release; installation storage proof and activation proof are distinct.

### Activation writer handoff

Decision: 2026-10-08. A verified immutable shadow decision does not mean that
its continuous publisher has released the behavioral writer lock. After that
attestation, the coordinator stops its Compose shadow and automation services
and verifies both are absent. Automation must still be disabled and killed.
Allow the shadow supervisor its reviewed host health budget (at least thirty
seconds) to terminate its child, durably acknowledge it and finish cleanup.
Use that same bounded grace for the initial coordinator quiesce and failure
cleanup, so a readiness retry does not interrupt the acknowledgement it needs
to resume. This extends owned-container shutdown grace only; worker, readiness
and broker-operation deadlines remain unchanged.
Only then may it prepare/re-read/reconcile the exact plan, enable automation
behind the kill fence, and establish the coordinated semantic restore. Plan
preparation, control activation and kill release each acquire the unchanged
nonblocking database writer lock; a foreign writer still refuses the attempt.
Never retry a generic CLI refusal, force an advisory unlock or discard a pending
worker marker to make this handoff succeed.

The automation process stays stopped through kill release. After the unchanged
authority, restore and prospective-window checks allow release, resume the exact
shadow service, require structural liveness and a verified attestation for the
same decision session, and repeat exact plan/shadow reconciliation. Recheck the
released control's exact certificate and that no automation process appeared,
then start automation. Thus a released control cannot dispatch through this
coordinator before the resumed shadow is verified. Any failed stop, changed
or contradictory proof, restart failure or cancellation follows the existing
durable emergency fence and stops both financial services; a typed readiness
wait keeps the broker-free shadow available under that fence. Activation success
still requires the real leader and advancing heartbeat. Software installation
does not enter this sequence and gains no time-of-day dependency.

If a legitimate newer shadow session appears during restart/restore, fence
execution and yield a typed activation wait so the existing coordinator can
prepare that actual newer decision on its next attempt. Never execute the old
plan, rewind the book or treat ordinary daily continuation as corruption.
After the next attempt establishes the durable kill and stops financial
services, explicitly deactivate any still-enabled control and re-read the exact
disabled/killed fence before changing reviewed configuration. Deactivation is
the supported control mutation; it preserves the book, account binding,
authority history and command journals. A missing kill fence, failed
deactivation or contradictory re-read remains a permanent refusal.

Qualification must use separate real processes holding the PostgreSQL advisory
lock, including a publisher active at the initial attestation, all three writer
boundaries, a foreign owner, unsuccessful stops and resumed-worker failure.
Exercise the actual shadow supervisor's interrupted-worker acknowledgement and
restart separately. A mocked service launch cannot establish lock handoff or
worker reaping. Preserve the original book/binding and distinguish these local
fixtures from protected certification and actual deployment admission.

Installation, activation-request/status and activation-result records use distinct
schemas and atomic writes. The installation receipt is never rewritten by
activation. Source/configuration changes require a new request instead of silently
retargeting authority. Install and activation share exclusive lifecycle ownership;
stale/replaced receipts and concurrent phase owners refuse before financial work.
An activation readiness retry releases lifecycle ownership before its idle sleep;
an active financial transaction still owns the exclusive lock. Upgrades never run
concurrently with that transaction, and stopping the activation service safely
returns its ownership without stopping the installed operator services.

Qualification must cover all modes at arbitrary clocks, missing financial inputs,
broker delay/blocking, signer absence, source lag, retained reconstruction, startup
health, signed-image mismatch, preserved bindings/journals, exact GO/JSON parsing,
activation window loss, locks/handoff/interruption, immutable status, and repeated
attempts. Reintroducing each coupling must fail an actual behavioral assertion.
No fixture, local image or rehearsal grants production deployment authority.

## Operator commands and receipts

Install software only, at any time:

```sh
bash scripts/sentinel-autonomous-deploy.sh
```

Install and explicitly queue dual activation after software completion:

```sh
bash scripts/sentinel-autonomous-deploy.sh --mode dual --activate-when-ready
```

Queue a new activation request for an existing installation, including after
editing activation configuration (no new software installation is necessary):

```sh
python3 scripts/sentinel_activation_coordinator.py \
  --queue-from-installation /absolute/path/installation-receipt.json --mode dual
```

Each request has a new private directory beside the installation receipt.
The command prints its `activation-request.json` path and handoff status. Where
the systemd manager is unavailable, run the printed request in a foreground
terminal using `python3 scripts/sentinel_activation_coordinator.py --request PATH`.
The foreground command owns the same exclusive lifecycle/activation locks;
closing that foreground terminal interrupts activation, leaving installed
software intact and execution fenced. A supervised systemd handoff survives
closing the installation terminal; inspect its named unit with `journalctl -fu UNIT`.
The JSON `activation-status.json` reports preparation, waiting, active, refused
or interrupted state. It does not replace the immutable installation receipt.
Never pass credentials as command arguments.

The change introduces no new provider, formation, execution or restore algorithm.
Qualification uses the retained real-provider results for those unchanged paths,
real ephemeral PostgreSQL for adjacent fences, and an isolated actual systemd
service for ownership/interrupt behavior. The systemd test deliberately refuses
its financial attempt; it cannot qualify paper activation or create authority.
New phase behavior and strict parsing require behavioral falsifiers. Protected
certification and the exact new release's real financial GO/activation remain
required before deploying these changes; no extra provider acquisition or
backup/restore of the running system is part of this local host-boundary test.

## Qualification coverage

The repository-wide screen covered 1,267 Python, shell, Compose and workflow
files, followed by reachability review of the installation/financial boundaries.
That screen is a search inventory, not a proof that every repository bug was found.
The seven reproduced couplings are covered by the new phase-boundary suite:

| Former coupling | Corrected boundary |
| --- | --- |
| Enrollment/signing/kill release before install completion | Immutable software receipt precedes the separate request |
| Financial GO required for software admission | Independent protected source/image signature verification |
| Source/session waits before starting installed services | Operator services plus dormant financial containers first |
| Readiness timeout rolls back installation | Typed activation wait preserves installation and execution fence |
| Financial health used as process startup health | Separate bounded liveness/critical-latch probe |
| Provider/account/signer/alerts required to install | Storage/operator profile; financial prerequisites checked by activation |
| Combined receipts and incomplete dual-mode tests | Separate strict schemas, immutable completion and all-mode/clock tests |

Local qualification uses Python 3.12 with unprivileged isolated PostgreSQL,
network disabled, read-only source and no production credentials, Docker socket,
authority, data or backup mounts. It includes configuration/writer/fencing tests,
source publication/formation recovery, actual-open cutoffs, runtime selection,
semantic restore and process health. The actual Python 3.8.15 interpreter also
imports both new host entry points and parses every host script. Full minimum-host
execution remains an exact-head CI requirement.

`python tools/sentinel_installation_mutation_check.py` tests disposable broken
copies of sixteen installation/image/health/JSON/authority/recovery guards. The existing
`python tools/sentinel_env_mutation_check.py` checks thirty-eight adjacent host
guards. Each mutant must fail a behavioral test; syntax/import errors cannot
substitute for a detected broken guard. The real Compose resolution witness
uses synthetic credentials and starts no service. The real systemd witness
proves ownership after launcher exit and SIGTERM cleanup with financial work
deliberately forbidden. Neither witness is release or execution authority.

## Recovery finalizer second pass

The second repository screen at base `d8112f8e` covers 1,272 tracked source and
configuration files. Reachability review includes all public deployment entries,
the bootstrap/driver inheritance chain, environment profiles, Compose health,
runtime selection, receipt finalization and the separate activation coordinator.
The inherited software finalizer still called the full financial backup/restore
hook. That is removed from software completion; the existing read-only physical
backup-chain check remains mandatory. Tests exercise the actual finalizer and
its inherited dispatch at open boundaries, midday, close, weekend and holiday,
with missing financial inputs and unavailable activation ownership. They must
also detect restoring the financial hook or removing backup-chain admission.

Exact rolling checkpoint/runtime matching remains a financial integrity guard.
This change does not silently rebind old history to upgraded software, certify
cross-runtime continuation or reset a retained book. Installation must complete
while that financial admission remains pending or refused. The screen and
boundary tests are evidence of the reviewed paths, not a guarantee that all
possible repository defects have been excluded.

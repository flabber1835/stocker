# Verified shadow recovery after a host restart

Decision, 2026-10-14, before implementation. Windows System events identify two
planned Windows Update restarts at 23:29 and 23:32 Pacific on October 13. Docker
and PostgreSQL returned at 05:35 Pacific on October 14. The durable shadow
pending marker correctly prevented a replacement worker, but an intact,
authenticated October 13 checkpoint then required a manual publisher stop,
inspection, marker archive and restart. Automation retained its existing
Wednesday opening plan; this was not a lost book or an Alpaca order failure.

## Recovery contract

Add one startup recovery path for an abandoned, well-formed pending marker with
no critical latch. This supersedes the unconditional operator-clearance rule in
`autonomous-paper-readiness.md` only for the positive proof below. An unknown
worker exit is never relabelled successful. Instead, independently verify the
current committed state before permitting the normal publisher to resume.

Hold a nonblocking, persistent filesystem owner lock throughout the supervisor
lifetime. A second supervisor cannot inspect, archive, arm or spawn concurrently.
The lock file is never unlinked, and the descriptor does not enter an executable
worker without explicit inheritance. Pass the same owner-lock descriptor to
each executable worker so an orphaned child keeps the owner fenced until it
actually dies. Record a version-3, HMAC-authenticated pending attempt with the
current runtime binding and Linux supervisor/boot/namespace identity before
spawn. Only these attempts can use automatic recovery. Legacy version-2 markers
lack this ownership guarantee and retain operator inspection, including the
already recovered October 14 incident. Keep the existing pending marker before
every spawn and the existing
normal acknowledgement and terminal-latch rules.

Recovery requires the deployed rolling input contract, exact reviewed
configuration, a typed pending attempt, no live old worker and no critical
marker. Use the canonical read-only `rolling_runtime.status` reader, not a
cached UI row or a new book implementation. It must return SHADOW_GO / VERIFIED
for the latest closed XNYS session, with an authenticated runtime attestation,
record, state and runtime identity. Its existing current publication/snapshot,
admission, schema, source, predecessor and integrity checks remain mandatory.
Read the current PostgreSQL cluster identity in the same diagnostic. Candidate,
reconstruction-only, stale, foreign, missing or unverifiable state cannot clear
the marker. No broker is constructed or contacted, no strategy record is
changed, and no execution authority is issued by this recovery.

One startup has a fixed 180-second monotonic recovery budget. The production
read-only closure measured 97 seconds; the original 30-second estimate would
have refused intact production state. Each independent
read is a killable child with a maximum 120-second budget and a PostgreSQL
statement timeout. Availability failures may retry within that original budget;
heartbeats do not extend it. Keep pending state unhealthy while proof is absent.
Require the finished proof to be at most 30 seconds old before its archive.
An unreaped observer prevents replacements. Exhaustion, terminal integrity,
malformed markers or a critical latch retain operator inspection and the
existing idempotent critical alert. This is a startup check, not another
ordinary polling, activation, backup, restore or after-close ceremony.

After proof, re-read the exact pending bytes and critical marker under the
owner lock. Persist and fsync a small typed, authenticated incident receipt
binding the original marker digest/attempt and the verified session, record,
state, runtime authority and cluster. Archive the original pending marker in
the durable state directory and fsync both directories before spawning.
Use a deterministic incident identity so an interrupted archive can resume
without duplicating or discarding evidence. Any changed marker, alias,
unreadable file or uncertain receipt/archive outcome refuses continuation.
An uncertain archive result latches for inspection; while latch persistence
itself is unavailable, do not renew a positive publisher heartbeat.
Preserve critical markers and alert/delivery history. Normal financial gates
independently decide whether the saved plan can execute; restart recovery never
backdates a plan, reopens a failed cycle or authorizes late orders.

Admit only the exact supervisor, marker decoder and worker-liveness successors
and added restart module through the
existing authenticated shadow UI source profile. Wealth Core, controller,
execution, feed publication and the immutable original book remain unchanged.

## Host availability and qualification

Docker Desktop is configured to start automatically at user login. This does
not establish unattended Windows boot before login; the observed six-hour gap
must not be presented as fixed by publisher recovery. Windows Update scheduling
and a host that starts the runtime without an interactive login require separate
host configuration and an actual reboot acceptance test. This release adds no
Windows autologin, stored password, update suppression or unqualified startup
claim. Installation remains deferred until the existing 06:31 paper cycle and
its reconciliation finish.

Qualify the real supervisor startup, process ownership, durable archive and
interrupted archive recovery. Use actual PostgreSQL rolling state for intact
positive recovery and corrupted/foreign/candidate negative cases. Falsify
critical-latch, exact-marker, canonical-verification, latest-session, owner-lock
and receipt guards. Verify zero broker calls, no additional book rows, no
backup/restore allocation and unchanged plan/command history. Preserve the
existing unknown-worker refusal tests for cases lacking positive proof.

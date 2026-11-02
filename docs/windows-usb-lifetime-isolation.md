# Windows USB failures must not own Ubuntu lifetime

Owner instruction, 2026-11-01: fix the remaining Windows/USB coupling while the
authorized backup-isolation release proceeds. Ubuntu currently hosts the native
Docker Engine and trading services inside WSL2. Windows still supplies the VM
lifecycle and USB/IP attachment. This change does not migrate the host OS.

The installed supervisor starts one foreground WSL keepalive, then observes and
attaches the backup USB. A USB command timeout, malformed inventory, changed
identity or failed attachment escapes to its outer fatal handler. Its `finally`
then kills the keepalive. Private interactive and S4U fault injection proved
that mechanism. The morning production exception remains unknown; do not claim
that it has been diagnosed merely by repairing this boundary.

## Separate failure domains within one existing owner

Keep the single existing scheduled task and its single foreground keepalive.
Start and supervise that keepalive independently of optional USB configuration,
client installation/version and observation/attachment success. Contain those
USB failures inside a bounded USB step. Record an explicit degraded USB result
and retry observation on the existing poll cadence. Never restart WSL or Docker
because the backup device or its management client is unavailable. Never attach
an ambiguous, foreign or unverified device.

Preserve the admitted usbipd client version, exact configured InstanceId and
persisted sharing GUID, process/output bounds, exact owned-client cleanup and
normal absent-device behavior. Put the public machine-specific USB identity in
an immutable SHA-bound local configuration, not in generic repository code.
Validate it inside the optional USB failure domain. A missing or invalid USB
configuration prevents attachment, not primary-runtime startup.

Keep actual primary failures fatal: wrong supervisor source hash, failed WSL
keepalive start or an exited keepalive must not be reported healthy. Preserve
original exception type, native code when present, source line and stack before
cleanup. Original installed scripts and diagnostic records remain immutable.

Diagnostics are bounded and cannot halt primary supervision. Keep one atomic
current-state record, at most eight rotating USB-error records of at most
64 KiB each, and at most eight exclusive fatal-error records of at most 64 KiB
each. Repeated unchanged USB errors do not create repeated files. Do not copy
private environment values or credentials into task arguments or evidence.
This does not re-enable the cancelled error-monitor automation or deliver the
separate dashboard-history prototype.

## Qualification and delivery

Qualify the actual Windows PowerShell version and the task's S4U context with
finite, private fake USB clients and fake keepalives. Exercise attached/absent,
missing or unsupported client, nonzero exit, timeout, malformed inventory,
ambiguous/changed identity, attach failure and failed diagnostics. USB failures
must leave the keepalive alive and allow another iteration. A true keepalive
failure and source tamper must still refuse. Execute a removed-containment
control. No qualification may invoke real WSL, attach/detach real USB, alter the
production task, or touch trading state.

Publish the reviewed source through the feature PR and require the release's
normal exact-head, merged-main and signed-publication gates. Host-only delivery
must use that exact source. Do not execute the preserved recurrence prototype.
Keep the committed PowerShell source LF-normalized and install its exact Git
blob bytes under their SHA-addressed filename; do not reinterpret text encoding
or edit an existing immutable startup file.

The one authorized live handover preserves the existing task's S4U principal,
ACL, triggers, IgnoreNew policy and native retries. Stage new content-addressed
source/configuration and record exact preimages. Before retiring the old owner,
create one uniquely owned temporary foreground WSL keepalive, without a USB
observer or restart loop. Verify the already-running Ubuntu boot, native Engine
and PostgreSQL identities. Update the existing task, stop only its old instance,
and invoke the same task once with the qualified supervisor. Verify its actual
new instance/anchor and a completed USB iteration. Only then remove the temporary
handover keepalive. Prove Ubuntu boot, Engine PID and database/container starts
unchanged across the handover.

Identify the temporary Linux sleep by a unique public handover marker in its
environment, together with its PID and kernel start time. Retiring its Windows
client alone is not sufficient cleanup proof. After the new supervisor is
proven, terminate only that exact marked Linux process if it remains, and verify
its disappearance. Never target unrelated sleeps or the new supervisor anchor.

This temporary keepalive is a handover resource, not a second supervisor. If the
new owner is not proven, preserve the exact owned handover resource and failure
evidence rather than dropping the last keepalive, replaying the operation or
inventing success. An existing request means inspect owner/result, never repeat
the handover. No WSL/Docker stop, restart, reset or prune; no financial/control
edits and no physical USB removal as part of installation.

## Recorded private qualification

The Windows PowerShell 5.1 private run passed 20 finite end-to-end cases and nine
direct controls. The USB cases cover attached/absent devices, successful attach,
nonzero state/attach exits, malformed or excessive output, identity mismatch,
ambiguity, changed bus, missing/unsupported client, missing/tampered configuration,
diagnostic failure, recovery and the unchanged native command timeout. Each USB
failure retained its fake keepalive and completed another iteration. Independent
keepalive start/exit failures and source tamper still failed with original error
records; native exit codes were retained. All owned fake processes exited.

Direct controls exercised the removed USB catch and removed unreaped-client
guard. They also verified the eight-record rings, byte limits, unchanged-error
deduplication, preservation of the first eight fatal records, atomic cleanup and
continued supervision when diagnostic writes fail. A first private attempt
exposed Windows PowerShell's null-string interop for atomic File.Replace; its
failure is retained, with no passes claimed. The corrected run used an actual
successful atomic-overwrite probe before the finite qualification.

The matching S4U run remains required before host delivery. These are private
fake-client tests; they neither reproduce the historical primary exception nor
establish installed production recovery.

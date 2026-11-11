# Proposed event-driven installation observers

This is a second-wave design for review, not implemented or activated behavior.
The first-wave installer reuse changes remain independently frozen. The installed
29ff image, financial authority, canonical book, UNKNOWN recovery and all original
proof clocks remain unchanged.

## One owned drain observer

Replace the repeated `docker exec ... acknowledged` loop with one finite owned
observer in the qualified immutable candidate image. The predecessor may be an
older image without this new reader API; its signed request/status/ACK formats
and existing worker admission protocol remain the interoperability contract.

The host still installs and verifies the journaled restart-policy hold, writes
the request once through the predecessor's canonical writer, and verifies its
exact container/image/StartedAt/RestartCount before and after observation. A
positive observer result must equal the exact initially returned request and
retain its original quiescent and expiry clocks. Existing final stop checks stay.

The helper gets only the exact inspected named state volume, read-only; no Docker
socket, broker credentials, additional volumes, published ports or network. Its
root filesystem is read-only, capabilities are dropped and no-new-privileges is
set, with bounded CPU, memory and PID counts. Its name and cleanup label bind it
to the immutable installation request. A private environment supplies only the
existing receipt-authentication key and the exact old runtime values needed by
canonical binding validation, including its database URL. Network none and no
database socket prevent that URL from becoming database access. No broker URL,
broker API key, authority issuer or financial command credential is supplied.
Do not copy the full rendered service environment into the helper.
Select this whitelist from the already inspected exact predecessor container's
immutable environment, rather than launching another Compose/environment probe.
Check its old commit/image against the journaled predecessor and use the fixed
read-only mount path. The ordinary fresh literal environment/digest checks remain
at the existing installer boundaries. Pass the exact request over bounded stdin.
Run with the exact predecessor container's configured user (explicit root when
empty), so dropping capabilities does not accidentally remove access to its
0600 state files. Candidate image qualification preserves the foundation user
database; no new identity or permission change is introduced.

Keep the transport in a small `sentinel.shadow_drain_observer` module and the
canonical shared-lock/read validation in `sentinel.shadow_drain`. The new module
uses standard-library inotify bindings and cannot write state or arm work. Its
one bounded status decode per coalesced status-only event batch reads at most the
existing 8192-byte status limit and verifies the existing HMAC/schema; it performs
no SQL, broker call, financial hashing, or new proof-clock publication. The helper
and its new source module require the ordinary candidate source/profile seal
before any installation; the frozen installed predecessor is not edited.

Use the candidate image rather than importing application code into native host
Python. That preserves qualified source/dependency identity and avoids trusting
a mutable native volume path, installed host dependencies, or a second signature
validator. Host-native access would require a separately qualified exact volume
mapping and cryptographic source/dependency equivalence; it is not selected here.

## Canonical read-only admission API

Add an explicit canonical read-only reader alongside the existing writer API.
It opens the already existing admission lock with O_RDONLY, O_NOFOLLOW and
O_CLOEXEC, never O_CREAT or O_RDWR. Validate regular-file/single-link identity
and stable device/inode against the named lock before and after acquisition and
observation. Take a shared flock; request/ACK/arm writers retain their exclusive
flock. A missing, aliased, replaced or malformed lock refuses. Do not work around
a read-only mount by opening the current writing admission helper differently.

Factor the current nonmutating poll body once, so both existing polling and the
new reader use the same authenticated request/status/ACK, exact binding and
incarnation, pending/critical, original ACK clock, expiry and remaining-handoff
checks. Genuine prior acknowledgements remain pending, never current quiescence.
The API cannot call arm, acknowledge, request, cleanup, or any financial reader.
File/lock errors, malformed signatures and changed requests remain refusals.

The helper's parent-owned finite process deadline bounds blocking lock acquisition
as well as its event wait; it must not become an unbounded in-process API call.
An implementation must demonstrate that a held writer lock cannot extend that
original deadline or leave an unowned observer running.
The read-only admission API accepts the absolute monotonic deadline and uses a
temporary main-thread alarm only around blocking shared-lock acquisition, restoring
the prior handler afterwards. It refuses an already active timer; no existing
owner's timer is replaced. The helper's parent timeout also bounds the complete
read/event process. There is no loop repeatedly attempting the same lock.

## Watch ordering and lifetime

Register an inotify directory watch before the first canonical read. Observe
the exact request, ACK, status, pending, critical and lock names. Atomic rename
events must wake the observer. Events are wakeups, never evidence. Drain a bounded
event batch and make one canonical observation for request/ACK/pending/critical/
lock semantic changes, rather than revalidating once per queued event. Ignore
unrelated state-volume churn.
For the admission lock, only create/delete/move/attribute changes are semantic.
Legacy writers open its unchanged inode O_RDWR, so a mere close-write notification
must be ignored; it does not change lock authority or file identity. Shared-reader
inode fences and overflow handling remain mandatory.

Status heartbeat writes alone must not cause repeated full request/ACK polls.
On a status-only event, a bounded canonical status decode may compare only its
binding, incarnation, state, reason and attempt ID with the last semantic status.
Ignore changes solely to heartbeat observation time or an active worker's deadline.
A semantic change triggers one complete read-only admission observation. This is
only a wakeup hint: it cannot authorize ACK, and every actual acceptance freshly
validates status age/incarnation/signature and all canonical drain facts under
the shared lock. Factoring the canonical poll may return its already-read semantic
status to avoid an extra read at initial/full observations; the old public poll's
ACK-or-pending result remains unchanged.

This status distinction matters when ACK is written while the last published
status still says ACTIVE_WORKER: the later IDLE status must wake validation even
if the canonical writer preserves the same existing ACK bytes. Pure heartbeat
silence with no ACK or semantic-file event may delay a negative result until the
original deadline. It never admits work, declares healthy, or extends that deadline.
Overflow requires one fresh full canonical observation under the same original
clock; watch invalidation, unmount or directory replacement refuses. No reconnect
or fresh timeout starts.

Derive one absolute ACK-acceptance deadline from the current original 180-second
wait, before launching the helper. Launch, lock wait, filesystem reads and IPC
consume its remaining ACK-acceptance duration. The helper also checks the original request's
expiry and required remaining handoff interval; neither gets renewed. Parent
and helper refuse clock regression or any response received after the original
deadline. A helper crash, Docker refusal or EOF does not fall back to repeated
exec probes or assert ACK. Positive results require exact current incarnation
and the existing restart-policy hold after helper exit.

Owned cleanup must preserve exact name/label/image identity. Preserve the complete
original 180-second ACK-acceptance window and the existing separately bounded
15-second cleanup inspection plus 20-second exact-owned removal allowance after a
Docker CLI timeout. This cleanup cannot authorize a late ACK, restart an observer,
renew a proof, or make the refused stage successful. Total failed-path wall time
may therefore exceed 180 seconds; do not describe cleanup as fitting inside that
ACK window. A failed or ambiguous cleanup remains an explicit owned-resource
refusal requiring inspection, never permission for another financial mutation.
Nonzero or unknown observer CLI failures also perform owned cleanup; an error
return is not proof that the daemon never started the container. Keep the primary
private child-error diagnostic as the cause if cleanup is unconfirmed. Successful
exit relies on completed `docker run --rm`, without another success inspection.
If exact-name inspection fails, one successful exact-name absence query may
confirm no helper remains, consuming only the remainder of the same 15-second
inspection deadline. Daemon errors or a present unvalidated ID remain UNKNOWN.

## Shadow health observation

The shadow's existing health meaning and finite 180-second startup bound remain.
One owned host-side `docker events` reader may replace fixed three-second inspect
polling. It subscribes to the exact candidate container before a fresh initial
inspection, filters relevant health/lifecycle events, and never treats an event
alone as readiness. A healthy event prompts a fresh exact container inspection;
OOM, exit, replacement, EOF, stream loss or expiry refuses under existing rules.
Reap the owned CLI on every exit. No daemon socket enters an application/helper.

Starting a Docker CLI process is not a subscription acknowledgement. Resolve that
ordering before implementation: a native read-only Engine event stream can wait
for the successful HTTP subscription response before initial inspection; a CLI
`--since` replay plus final inspection at the original deadline is safe against
accepting false readiness but may unnecessarily wait the full interval after a
missed event. Docker's finite event history is not proof that no event was lost.
Do not claim that process launch alone closes the read/subscribe gap.

This uses the installer's already qualified read-only Docker operations. The
event reader has no new daemon API surface or financial permission. It changes
how a wait wakes, not which final current facts admit the next stage. Verifier
liveness/readiness separation is a different design and is not changed here.

## All-role startup health

The November 11 pre-open installation refused in the all-role Engine wait.
The original journal then completed verification with the same application
incarnations. Docker health records probe outcomes for a running process, and
a failed startup probe can recover without a process replacement.

While the exact startup group is pending, an inspected `unhealthy` role is a
negative readiness observation, like `starting`. Keep the existing subscription,
canonical inspections, absolute startup deadline, and final fresh observation.
All roles must report `healthy` before this gate can finish. A stopped process,
OOM, restart, changed identity or image, or malformed health still refuses
immediately. The later current process, leader and dashboard gates keep their
existing requirements. Qualify same-incarnation recovery, persistent negative
health, malformed health, and terminal process changes without adding probes.

### Verifier startup grace (November 10, 2026)

The November 10 local PAPER rollout reached the verifier health refusal at
31.94 seconds. Its first operational projection heartbeat appeared at 32.94
seconds, after the initial full composition and the fast worker's startup.
Use a 120-second Docker startup grace for `sentinel-verifier`, matching the
installer's all-role health wait budget. Both fresh heartbeats are required
for the first successful probe, which begins ordinary Docker failure counting.
Installation also requires the same healthy processes and a current dashboard
receipt under the existing deadlines.

The backed local installer admits the exact verifier grace change in
`docker-compose.sentinel-automation.yml` against the installed predecessor.
The changed Compose file belongs in the qualified source inventory and
approved delta. Verify the old and new effective graphs, a delayed cold-start
heartbeat at the deployed half-CPU limit, and refusal for a permanently
missing heartbeat or a replaced process.

## Required private falsifiers before delivery

Qualify a real read-only mounted volume and existing shared/exclusive lock;
missing/aliased/replaced locks; ACK before watch/after watch/between read and wait;
atomic renames; overflow/unmount/EOF; irrelevant event storms; old/foreign ACK;
active/pending/critical work; original expiry, clock regression and late response;
same-ID/image process restart; held writer lock and bounded helper cleanup;
failure without polling fallback; and exact owned cleanup after lost CLI ACK.

Health tests must subscribe before observation, refuse missed/foreign lifecycle
events, re-inspect before accepting healthy, keep the original deadline despite
many events, and reap only the owned event reader. Actual native fixtures must
have no financial authority, network or production mounts. Source/profile changes
and deployment qualification remain separate from this design review.

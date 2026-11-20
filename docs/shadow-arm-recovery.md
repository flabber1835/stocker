# Shadow worker admission after an arming timeout

On November 20, 2026, a SHADOW arming helper expired after 2.08 seconds. The
supervisor exited before launching a worker. Its Docker replacement found no
retained marker and armed in 50 ms. Local browser and automation qualification
shared the WSL runtime during the failure. The kernel had recorded memory
pressure shortly before. The retained evidence cannot identify which operation
stalled in the helper.

The supervisor currently turns a first helper timeout into a process refusal
even when the helper has stopped and no worker or marker exists. The original
publisher owner can safely re-establish admission in that case. Give it one
fresh arming attempt after a one-second pause. A shutdown during the pause ends
the attempt. Keep the two-second budget on each helper and the existing helper
kill, reap, and unreaped-process checks. The retry helper must observe both
marker names absent under the same publisher ownership before attempting the
existing drain and arming protocol. A dangling or otherwise present marker
counts as present. A read error leaves the state uncertain.

Only a successful fresh drain check, exclusive marker creation, file and
directory sync, and positive child reply permit launch. A live drain still
holds admission. A retained marker, an uncertain marker check, an unreaped
helper, or an unsuccessful retry takes the existing refusal path. The startup
recovery protocol owns retained pending markers. The retry never removes or
reuses one. `ARM DEFERRED` records that the first helper timed out before a
retry decision. `ARM ACCEPTED` records the usual positive admission.

A separate controlled audit of the installed source found that each fresh
arming child attempted to open both the `shadow_drain` bytecode cache and its
source. Load that module in the supervisor before forking. The helpers inherit
the imported code and still read and authenticate the drain request fresh. Run
full browser and automation qualification outside the installed runtime host.

Qualification must reproduce a transient pre-marker stall in a real helper
and verify one launch under the original supervisor. Block the first helper
after it has synced the marker and verify that the retry preserves the marker
and refuses to launch. Cover persistent timeout, drain, and uncertain marker
observations with the existing dependency and recovery tests. Preserve the exact
retained predecessor and reseal the changed candidate source.

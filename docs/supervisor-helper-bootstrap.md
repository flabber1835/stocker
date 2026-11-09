# Load the helper's ctypes module before forking

Decision, 2026-11-08, before implementation. The owner requested removal of
avoidable repeated operational work. A controlled, authority-free proof using
the installed c2569 supervisor source found that importing `shadow_supervisor`
does not import `ctypes` into its parent. Three real `supervisor_io.run(noop)`
calls each repeated the ctypes module imports and four standard-library file
open attempts in their forked children. The parent still had no ctypes module
after those calls. Preimporting it once in that private parent removed the
module imports and all four open attempts in every child, while child-local
library lookup and parent-death signaling remained active.

Import the standard-library `ctypes` module at `supervisor_io` module load,
before creating forked observers. Remove only the function-local import from
`_parent_death`. Each child must still construct its own `CDLL(None,
use_errno=True)`, call `prctl(PR_SET_PDEATHSIG, SIGKILL)`, refuse a kernel error,
and check the actual parent PID after arming. Do not create that libc handle or
arm a signal in the supervisor parent. Spawned helpers import their own module
normally and retain the same child-local boundary.

This reuses immutable imported Python code within a process. It does not reuse
a database connection, dependency observation, status, proof, mutable file
content, or financial authority. Keep the observer's timeout, IPC envelope,
cleanup/reaping, parent-PID race check, and all original lifecycle decisions.
No new dependency is introduced.

The controlled proof ran 06:50:10.142125–06:50:14.458063 UTC in one private
network-free container limited to one quarter CPU and 192 MiB, with source
read-only and no production state or credentials. Its artifact is
`.codex-tmp/supervisor-ctypes-bootstrap-20261108.json`. The four audit events are
open attempts; they do not establish that missing bytecode files were read.
This demonstrates repeated bootstrap work, not a latency guarantee or the exact
instruction/page fault that delayed an earlier production helper. In
particular it does not establish the cause of the historical 05:40 ARM timeout
or identify the pathname of the sole open in the 06:32 heartbeat failure.

Qualification must launch a fresh Python parent, verify three real forked
helpers inherit ctypes without reopening its library files, and query
`PR_GET_PDEATHSIG` inside the actual helpers to confirm SIGKILL is armed. A
private source mutant that restores the old local import must restore those
child file-open attempts and fail the no-repeat assertion. Exercise the real
spawn path and the existing timeout, unreaped-child, and parent-death guards.
Use one bounded isolated cohort; no service, application-state mount, or
production operation is needed.

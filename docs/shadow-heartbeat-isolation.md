# Shadow supervisor heartbeat failure containment

Stage 1 review on main `ec8351ff2f535885d5a1cefcbca9b9bb83498b5c`
found that the supervisor touches its heartbeat directly while a worker runs.
A blocked filesystem call suspends deadline enforcement; an ordinary write
exception exits the supervisor without disposing of its active worker.
There is also an ordering defect: after observing a terminal worker exit, the
parent touches the heartbeat before persisting that refusal. A heartbeat failure
can therefore lose the refusal and allow a later supervisor to launch again.

The heartbeat is a liveness observation, not economic authority. Perform each
touch through the existing one-second killable dependency observer. If it fails
or exceeds that budget, propagate failure after terminating and reaping the
active shadow worker. Use a `finally` boundary around the whole supervised loop,
including shutdown and exceptional exits. Remove the heartbeat through the same
bounded observer, best effort. The parent must never wait on a filesystem write
before disposing of a known active worker during failure cleanup.

Successful worker outcomes, retry classification, checkpoint identity, persisted
integrity latches and the existing five-second termination grace are unchanged.
This is an availability failure, not permission to clear a latch, initialize a
new book, or mark UNKNOWN execution final. A replacement process recovers only
through the existing journal/checkpoint contracts.

Persist a known terminal exit or exhausted semantic retry before attempting the
next heartbeat. An ordinary heartbeat failure must not preempt this durability
obligation. The existing latch writer and first-refusal retention stay intact.

Acceptance uses the public supervisor loop, real disposable workers and real
forked observers. Inject both an ordinary write error and a touch that ignores
SIGTERM and never completes. Require bounded failure, no live worker/observer,
and no next worker launch. A positive case completes a heartbeat, stops normally,
reaps the worker, and removes the heartbeat. Removing the observer boundary or
exceptional cleanup must fail its respective acceptance test.
Also require a real exit-2 worker's refusal to be durably latched despite the
next heartbeat failing, and bound a stalled heartbeat removal during shutdown.

This does not qualify kernel uninterruptible I/O, an unavailable persistent latch
volume, parent SIGKILL, container restart, or NAS storage semantics. The startup
latch check and durable latch persistence remain separate filesystem gates.
Independent container/external health and target fault injection are still
required. No historical return or economic certification follows from this fix.

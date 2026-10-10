# Activation startup contention and retained cycle diagnostics

Decision: 2026-10-10. A resumed broker-free publisher and automation lease
acquisition use the same canonical nonblocking writer lock. Losing that initial
acquisition is a bounded scheduler wait, not a programming failure or permission
to steal the lock. The automation tick rolls back its observation transaction
and returns without a permit, cycle mutation or financial callback. The existing
heartbeat/control-poll wake retries acquisition with the same worker identity;
there is no blocking advisory lock, shortened financial guard or new deadline.
Only `WriterLockUnavailable` from the lease-acquisition boundary is classified
this way. Other lease, authority, integrity and mutation failures retain their
existing refusal behavior. A waiting instance cannot prove another leader's
liveness or create execution authority.

The activation observer must distinguish a durable blocked cycle from a retained
diagnostic. In the actual PR499 attempt, takeover intentionally superseded a
pre-transport cycle and retained `CONTROL_GENERATION_SUPERSEDED`. Treating any
nonempty `latest_failure_code` as a new fatal failure killed the worker before
it completed its first authority/liveness poll. Both the readiness wait and
final advancing-heartbeat proof must refuse `BLOCKED`, while other historical
or retry diagnostics do not independently latch activation. They still cannot
satisfy activation: current operational readiness, exact signed authority,
current leader/fence and advancing durable heartbeat remain mandatory. An
unready worker still reaches the existing bounded readiness wait; no success
receipt is fabricated and no failed request is retried by this repair.

The executable transition is admitted by a separate immutable one-file source
profile for `automation/service.py`, authenticated against verified main
`4c9f8769a53dc1dd924348f21a357616209e41c4` and the unchanged earlier reviewed
source profiles. Preserve every earlier source profile and fixture. The repair
introduces no schema, strategy, controller, account, plan or command change and
must preserve the authenticated formed book without reformation/acquisition.

Qualification exercises an actual PostgreSQL advisory lock in a separate
process, release and successful same-worker acquisition, persistent contention,
foreign live leadership, cancellation and non-contention refusal. Join retained
generation supersession to both actual host readiness and final heartbeat
checks, including blocked/unready/stale/wrong-authority falsifiers. Exercise
the first worker tick's terminal, notification and control-poll boundaries
before publication; source coverage alone is not activation acceptance.

Retained shadow health reported a changed projection during the attempt. An
exact-image read-only observer after shutdown found both configuration and
inventory hashes equal, with the financial origin intact. This does not prove
which inventory snapshot changed during the active publisher. Preserve those
logs and qualify publication/health overlap; do not waive a changed projection
or claim a confirmed shadow corruption from that retained diagnostic.

# Retained private gateway handoff

Decision: 2026-10-24, before implementation. Complete the operator procedure for
the already prepared `bcda30952e884cf58a252e63ccbd926b` campaign without changing
its frozen driver, original clock, database, helper bytes, or installed software.
This is an offline-preparation deliverable, not permission to run native orders,
activate LIVE, deploy the PR, or schedule unattended future work.

The tracked host wrapper is deliberately a one-campaign handoff. It authenticates
the original owner-local host launcher by an independently pinned SHA256 before
loading its existing image, resource, mount, network and physical-database checks.
It pins the original request, PostgreSQL facts, campaign seal, campaign bytes and
prepare receipt. It does not copy, recreate, reset or upgrade anything. The old
host launcher's permitted modes remain unchanged; the separate wrapper adds an
explicit, separately recorded gateway invocation using that original bundle.

`check` reads files, Docker metadata and a SELECT-only private database summary.
It never creates a container or claim, and never consumes a financial namespace.
It reports the actual UTC eligibility interval and retains no PASS claim. `run`
repeats these checks and requires the actual clock in the immutable original
session's eligibility interval before claiming a fresh host invocation exactly
once. The frozen inner driver independently rechecks the real exchange calendar,
source frontier, runtime identity, original EXECUTE clock, authority and funding.
Host eligibility is an additional refusal, not a substitute for those guards.

The only process it can start is a new labelled helper container using installed
image `c198a55a...`/source `fb295202`, one CPU/two GiB, read-only helper bind,
evidence bind, and the exact private PostgreSQL container's network namespace.
That namespace has no network. No provider credentials or operational database
are mounted. Local simulated broker calls are the only orders in this campaign.
The wrapper can stop only its just-created fully revalidated container after
failed attachment/timeout. It preserves containers, volumes, original reports
and logs; no shared-engine or PostgreSQL restart, backup, archive or cleanup runs.

Full host resource and ownership checks occur before starting and after exit.
A Docker exit code alone cannot establish success: the original gateway report
must bind the same campaign and original EXECUTE, first simulated POST <=120s,
positive complete basket <=300s, durable successful cycle, and unchanged book.
The original report remains authoritative evidence. A host summary names its
hash and always states native/live/production-opening qualification false.
The outer attach timeout is only a process containment bound; the frozen inner
120/300-second financial timing limits are not extended.

## Operator procedure

Run `python -B tools/live_timing_gateway_host.py check` from the reviewed checkout.
The owner-local launcher and retained campaign must exist at their pinned paths.
Saturday correctly returns `BLOCKED_MARKET_SESSION`; nothing is consumed.

For this campaign the original EXECUTE is **2026-10-26 13:31:00 UTC**, Monday
**06:31 Pacific**. At the actual eligible session, begin the explicit `run`
invocation between **06:21 and 06:25 Pacific** to leave preflight time:

```text
python -B tools/live_timing_gateway_host.py run
```

Do not run other builds, qualification, profiling or resource-heavy work during
the timed gateway. If eligibility, ownership or a financial gate refuses, retain
the refusal and original namespace. Never rerun a claimed invocation, move the
clock, shorten PREPARE, relax a deadline or substitute another namespace's result.
Do not rerun preparation or the consumed cold diagnostic. A failed gateway is
not repaired by repeating status or by observing subsequent paper fills.

No future automation is created by this work. This command does not deploy or
activate anything. Even a full private gateway PASS proves only the named
generated exact-image software timing scope; native provider behavior, production
history, independent strategy economics and real-money acceptance remain open.

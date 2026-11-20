# Opening trace coverage and callback timing

The November 20 opening reached its scheduled cycle transition on time, but the
command-owned trace stopped before the open. Its retained runtime events leave
25.8 seconds unattributed between the cycle transition and first timed preflight
operation. Use the existing browser journey for subsequent opening captures.
Run it as an independently owned, bounded host job and retain incremental
coverage and event records. A current green sample alone does not qualify a
capture. Missing or stale coverage and unexpected recorder exits are explicit
diagnostic failures. Incomplete trace evidence stays separate from a completed
capture with a product finding.

Expose a caller-selected new private evidence directory so the supervisor and
operator can resolve the same path before launch. On Linux, run the existing
CLI under the user service manager with a finite RuntimeMaxSec and retain its
exit status in the journal. On Windows use Task Scheduler under the operator
identity with a finite execution limit. Coverage files distinguish running,
finished and interrupted attempts even when the original client disconnects.
Keep event output bounded by the existing journey limits.

Record execution-admission stages for lineage, leadership, idle observer handoff,
callback registration, fork and process group readiness. The child emits entry
before setting up its event loop. A cycle entering the normal execution path
validates its lineage in _run_execute; recovery/adoption retain their separate
validation before use. Measure before-read guard, adapter read, and after-read
guard separately during a PAPER execution, with operation names and durations
only. This preserves broker read order, account consistency brackets, bounded
supervision and financial authority. It does not attribute the historical
unmeasured interval to a particular operation.

Within one fresh PAPER authority check, derive one strategy identity and use
that same value for plan validation and signed authority. The next check
derives it again. Repeated identity reconstruction inside the same check
adds work and can give its two consumers different identities.

Persisted protected funding fields retain the exact wire key schema. Internally
use a field name that does not shadow the Pydantic base class. Verify canonical
serialized evidence and hashes against the retained format.

Seal the final application source inventory through the existing exact-source
handover workflow, using the original PR #615 merge as the retained predecessor.
The seal records compatibility without granting financial authority.

## Launch and verify an opening trace

Start the run shortly before the expected opening transition. Setup uses an
installed browser and the existing lock-matched Node dependency cache. Select
one browser project and an unused evidence path. For a Linux operator with an
active user service manager and an installed Chromium channel:

```sh
systemd-run --user --unit=sentinel-opening-trace --property=RuntimeMaxSec=1320s \
  /usr/bin/python3 /path/to/stocker/scripts/sentinel_dashboard_journey.py \
  --phase opening --url http://127.0.0.1:8004/ --project chromium-pwa \
  --dependency-cache /path/to/node_modules --evidence-dir /private/opening-trace
```

On Windows configure the same command with the installed Python executable and
browser channel as a one-time Task Scheduler action. Use the same output path
to check `coverage.json` during the run and `result.json` after it exits. On Linux
check the independent owner's exit status with
`journalctl --user -u sentinel-opening-trace`.
```sh
python3 scripts/sentinel_dashboard_journey.py --check-coverage /private/opening-trace
```

A successful result requires the existing matched waiting, execution,
completion and verified display evidence plus continuous recorder coverage.
Incremental events remain available after interruption, with no successful
verdict inferred from the partial files. Pause or stop the trace through its
own host job, independent of the application services.

CSS or layout can reveal content without changing the DOM. While a document
generation lacks rendered evidence, recheck visibility once every 100 ms in the
finite capture. Emit visible content only after the same generation is visible
through two animation frames, then stop rechecking it. Keep the mutation
observer for transient states and require the same matched HTML and navigation
timing evidence in the final report.

## Browser CI runtime

The November 20 browser job spent 29 minutes downloading Ubuntu packages
and reached its 30-minute deadline before either test project ran. Use the
official Playwright image at the version selected by the test lockfile.
Pin its registry digest so the browsers and their system libraries are fixed.
Give the pull its own bounded step. Keep the existing exact-source Sentinel
image and loopback test target. The browser runner installs the locked npm
packages and runs the complete WebKit and Chromium suite in that image. When
the Playwright lock changes, update the browser image version and digest in
the same change.

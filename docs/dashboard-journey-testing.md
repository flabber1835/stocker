# Dashboard journey evidence

Decision, 2026-10-31, before implementation: qualify the observed launch and
refresh journey separately from the existing mocked, virtual-clock guard tests.
This changes test observation and acceptance only. It changes no production
dashboard, financial rule, clock, service, database, authority or execution path.

## Scope and delivery

Use the exact installed dashboard over its real HTTP/rendering path. The
dedicated browser configuration is opt-in, uses one worker and no retries, and
does not silently become a healthy-financial-state requirement for the existing
unconfigured CI server. Extend PR 551, based on main
`91c1ee3d4adfb52c3acfe32aa1e822971edf21af`. Keep existing focused guard tests.

Capture one cold navigation through two actual HTML refresh responses, with real
elapsed time. Do not rewrite HTML, headlines, timestamps, evidence budgets or
polling intervals. Do not install virtual clocks or simulate visibility events
as evidence of actual iOS suspension. Allow the real service worker in both
browser projects; report unsupported or uncontrolled workers explicitly rather
than claiming coverage or registering a replacement worker for the application.
Desktop WebKit at an iPhone-sized viewport is desktop coverage, not an installed
physical-iPhone result.

## Evidence and attribution

Record the navigation/HTTP timing phases, response status and freshness headers,
original document generation and expiry budget, original server health label,
rendered warning identifiers, first meaningful dashboard content, paint entries,
document replacement, visible health/preparation changes, browser lifecycle and
service-worker state. Preserve a digest and request identity for each observed
HTML response. Classify the source of each warning using the response that
actually produced that document; a later separate `/panel.json` read is not
evidence of the earlier response. Record unknown attribution honestly.

Observe across `document.open`/`document.write` replacements. Verification of
the recorder must prove that a root replacement and a short warning transition
are retained; instrumentation must not change the application document or
re-register its worker. Node monotonic capture times and browser document times
remain distinct. Never infer a server database duration from browser TTFB alone.
Initial OS splash frames precede document instrumentation and require a phone
screen recording.

Use an isolated browser profile and passive navigation only. No account,
notification-enrolment, control or broker actions are exercised. Record request
paths and safe timing/status metadata, not cookies, authorization headers, query
secrets, raw account payloads or a full HAR. Do not copy a database, produce a
backup, rebuild an application image, install browsers or roll production.

One invocation is bounded to 120 seconds per browser and two refreshes. Keep a
small JSON timeline and at most three viewport screenshots per browser. No
always-on recorder or recurring monitoring is introduced. A missing response,
timeout, event overflow or unavailable recorder is incomplete evidence, never a
passing journey. Output is a new owned directory under `.codex-tmp`; no existing
artifact is overwritten or unrelated history deleted.

## Independent acceptance

Capture and acceptance are separate results. A complete capture can expose a
failing user experience. The initial provisional normal-network targets are
meaningful visible dashboard content within 3 seconds of navigation, and at most
1 second between receiving the document and showing its main content. Report
actual timings alongside both targets; changing a target requires a documented
decision, not a test repair to make the current release pass.

The healthy baseline requires original server health to be green and stable.
An amber browser headline during ordinary healthy refresh is an explicit
`HEALTHY_REFRESH_FLICKER` finding even when it correctly withdraws stale proof.
This acceptance finding does not authorize retaining stale green, changing a
financial deadline, or treating a real backend warning/failure as a UI defect.
Record original negative server evidence separately and require immediate
negative precedence. Unexplained blank content after first meaningful paint,
missing timing evidence, unexplained colour changes and overlapping refreshes
are reported independently. Screenshots and performance entries cannot prove
the absence of every one-frame visual flash; do not make that claim.

For the first baseline, do not repair production behavior in response to a
finding. Produce the timeline and a failing current-release reproducer first.
Controlled latency/failure cases belong in a dedicated test environment or
client-only transport profile, with unchanged response bytes and clocks; never
inject faults into production services or fabricate financial PASS evidence.

Decision, 2026-10-31, before the latency-profile implementation: when a direct
baseline does not reproduce intermittent refresh flicker, use a separate
explicit client-only slow-refresh profile. An owned loopback proxy forwards
passive GETs to the exact HTTPS origin. It holds only completed non-navigation
root HTML responses until that request has taken at least 6.4 seconds in total,
matching the previously observed response duration, then sends their unchanged
entity bytes. Already slower upstream responses receive no extra delay. It preserves original
freshness/header verdicts and document timestamps, records upstream entity
digests, and binds those digests to the browser-captured responses. Compression
and transfer-length headers describe the proxy transport, not new evidence.
No new financial fixture or rewritten green headline is permitted. This is a
controlled transport reproducer, not a claim that the same delay occurred in a
direct run or on the physical iPhone. Run it explicitly and keep its origin,
latency and result separate from direct evidence. Close the owned proxy and
upstream requests at the end; no permanent listener is installed.

## Physical Home Screen gate

A separate actual-iPhone session must start recording before tapping the Home
Screen icon and continue through first content and two refreshes. Also capture
return after genuine background suspension. Record iOS version and connection
type. Where available, correlate Safari Web Inspector network/timeline evidence
from a connected Mac. Without physical device evidence, mark this gate
`NOT_RUN`; desktop success cannot clear it. A video without network timing can
establish visible phases but cannot identify backend or network causes alone.

After capture, choose one attributable defect, preserve a reproducer that fails
on the current release, implement one correction through the PR workflow, and
rerun the same acceptance without altering thresholds or evidence timestamps.
No production correction is part of this initial capture task.

For subsequent dashboard behavior changes, the acceptance evidence is a release
gate: do not describe the installed iPhone experience as fixed from the old
virtual-clock suite alone. A failing controlled journey, incomplete direct
capture or unrun physical gate remains open work. The opt-in command prevents
an unconfigured CI server or a developer without private-origin access from
silently manufacturing a healthy dashboard fixture. Delivering this diagnostic
test code does not itself clear that product gate.

## Running the bounded capture

Use existing Node, Playwright dependencies matching `tests/browser/package.json`,
and installed WebKit plus a Chromium channel. Nothing is downloaded. Run the
recorder integrity check before the actual read-only capture:

```sh
python scripts/sentinel_dashboard_journey.py --phase integrity \
  --url https://YOUR-PRIVATE-DASHBOARD/ --dependency-cache /existing/node_modules
python scripts/sentinel_dashboard_journey.py --phase capture \
  --url https://YOUR-PRIVATE-DASHBOARD/ --dependency-cache /existing/node_modules
python scripts/sentinel_dashboard_journey.py --phase capture --profile slow-refresh \
  --project chromium-pwa --url https://YOUR-PRIVATE-DASHBOARD/ \
  --dependency-cache /existing/node_modules
```

On Windows the default Chromium channel is installed Edge; on other platforms
it is installed Chromium. `--channel` can select another already installed
supported channel. Use `--project` to deliberately restrict a diagnostic run;
the report must continue to identify its narrower coverage.

The integrity phase uses an owned ephemeral loopback fixture, not the supplied
production origin. It proves that short changes and document replacement are
observable. `RECORDER_VERIFIED` qualifies only that instrument. The capture
phase returns `PASSED_DESKTOP`, `OBSERVED_FAILURE`, or `INCOMPLETE` separately
from the physical Home Screen gate, which remains `NOT_RUN`. A real acceptance
failure returns exit 1 and retains the original browser results; it is not
converted into a passing test. Skipped/retried/extra browser cases, global
framework errors, missing reports and source changes cannot pass the runner.

Inspect `result.json`, each `journey.json`, and the at-most-three viewport
screenshots in the newly owned `.codex-tmp/dashboard-journey-*` directory. The
entire invocation has a 280-second deadline and 20 MiB evidence budget. No full
trace, video, HAR or financial HTML is stored by this desktop runner. On the
iPhone, begin a short screen recording before leaving the Home Screen, tap the
installed app, wait for two refreshes, and record a genuine background/return
sequence. Device video is separate evidence and must not be replaced with a
simulated visibility event.

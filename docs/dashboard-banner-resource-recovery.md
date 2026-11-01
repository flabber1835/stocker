# Banner resource recovery

Decision: 2026-11-01, before implementation. This is a presentation-only fix,
separate from the DELL recovery PR. Deployment remains stopped.

## Reproduced failure

The original PNG is valid, and the owner can display its direct URL in Safari
on the same iPhone. The original phone transfer is unavailable, so its initial
failure must not be described as proven network corruption or a Safari defect.

A controlled desktop WebKit experiment reproduces the persistent blank square:
serve the unchanged dashboard HTML and exact PNG, interrupt the first HTTP 200
PNG response after 1,024 bytes, and restore normal delivery. The image becomes
`complete=true`, `naturalWidth=0`, yet retains a full square layout. Three normal
HTML requests, including the dashboard's actual document replacement, leave it
blank and make no second image request. A fresh navigation requests the same
valid PNG again and displays it. Thus ordinary HTML replacement does not clear
the failed subresource identity. A separate delayed-image experiment did not
reproduce refresh starvation; do not change refresh timing on that hypothesis.

## Narrow correction

Keep the original asset and static route/cache headers. Add an independent
presentation controller for the expected banner. Only an actual image error or
`complete && naturalWidth === 0` may replace a known-failed resource identity.
Make one immediate request with a fresh, non-secret URL query identity. Do not
retry a merely pending image, call decode during observation, add a retry timer,
or change a healthy image URL.

Retain that selected identity and its consumed attempt across the application's
document.open/write replacements in the same window. Healthy subsequent refreshes
reuse it. A genuine new navigation gets the ordinary fresh-window lifecycle.
Select the retained identity before admitting an image request: the main image
declares its expected asset in data-banner-src, and the controller assigns src.
Otherwise the HTML parser can request the old failed URL again before a footer
script runs. Keep explicit square dimensions and a noscript image using the
original URL, so the graphic remains available with JavaScript disabled.
Keep the script-controlled image hidden until a successful load supplies
positive intrinsic dimensions. This also prevents an unused empty main image
beside the noscript image when scripting is disabled. A pending transfer remains
pending; hiding it cannot renew a request or declare it failed.
If that one recovery request also fails, show a compact accessible brand label
instead of a large empty square; repeated status refreshes cannot renew the
attempt budget. This is an explicit unavailable graphic, not operational health.

No banner state can refresh the dashboard, change its operational verdict,
extend evidence validity, alter source/account/notification facts or affect
broker execution. No new service-worker cache or global cache-busting policy is
introduced. Keep the existing full-width artwork whenever it is available.

## Evidence

Retain the original truncated-200 failure, its ordinary-refresh/fresh-navigation
control and exact source hashes. Test the repaired behavior in desktop WebKit
and Chromium: healthy first load, interrupted first transfer, a permanently
failed recovery, a slow pending transfer and document replacement. Assert actual
image dimensions and inspect banner screenshots; HTML tag presence alone is not
acceptance. Falsify the failed-image guard and the consumed-attempt boundary.

Extend journey observations to include banner resource success/failure and
intrinsic dimensions, without recording account payloads or making a desktop
run a physical iPhone claim. The physical Home Screen gate remains NOT_RUN until
the installed change is checked on the actual device. A separate PR and passing
desktop tests do not claim production deployment or a completed iPhone fix.

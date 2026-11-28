# Dashboard browser recovery and marquee

Decision, 2026-11-26. The app owns a bounded deadline for the entire response,
including the body. Expiry releases the browser's refresh slot even if the
network operation stays pending after cancellation. Only the still-current
request may install a document. Foreground launch and subsequent refresh use
the same request deadline and freshness validation.

Anchor display expiry to the server's UTC response time and the browser's
monotonic elapsed time. Charge the full observed round trip against the
remaining display lifetime. Retain the original server evidence times and
deadlines. Use the same monotonic clock for refresh scheduling and recovery.
Direct document navigation charges the server's age at render time and the
time elapsed since navigation began.
A fresh document is required when time or currentness cannot be established.

The normal refresh path carries the current controller version and receives a
fragment with the present dashboard content and timing metadata. It omits the
startup shell, inline styles and controllers. A version handoff sends the full
document. Both paths obtain the same authenticated display projection and
preserve the same receipt, review and expiry rules. The browser reconciles
stable elements in place and does not restart a banner on a routine refresh.

Use the red, amber and green 3:1 Caesar's Palace assets from the owner's
“Create Three Letterbox Variations” discussion. Each status selects its own
neon sign; only the gold perimeter bulbs alternate, at their original rate.
Use a still frame for reduced motion. Use a muted brass still while status
is being checked and grey when the device is offline. Label last verified red
and amber in text when the connection or
freshness is uncertain, and keep the next status check visually separate from
the review. The dashboard logo carries color in place of a colored border.
The app launcher icons reuse their existing square icon format.

Qualify the updated service worker with the launch and refresh controllers.
Exercise stalled responses, inaccurate device clocks, return from background,
degraded observations, review history and version handoff. The app can
continue to show a dated last-known warning after its current evidence expires.

Seal the exact dashboard Python source inventory against the installed PAPER
application revision. The source comparison preserves existing execution and
recovery authority. The release image carries the marquee files.

## Request ownership across suspension

Decision, 2026-11-27. Launch and the loaded dashboard use the same browser
request owner. It holds the active request and a scheduled retry. Hiding the
page, leaving it, or going offline releases both synchronously before aborting
the request. A retired completion cannot install a document, report a failure,
schedule a retry, or release a replacement request. A timeout of the current
request follows the normal retry policy.

A foreground return that needs a status check can immediately start one fresh
request. The original scheduled polling and evidence clocks still govern
ordinary visible refreshes. Repeated lifecycle events share the current request
and the same fixed 15-second foreground recovery episode. At launch, a manual
retry or a restored network connection can advance a scheduled retry. Only
fresh server evidence renews display authority. Suspension, aborting a request,
and changing request owners grant no extension of financial evidence or observed
warnings.

Exercise a delayed request and a pending retry across suspension. Check that the
new foreground request starts immediately, retired responses have no effect,
and a failure on the new request still backs off. Qualify the exact browser
source successor on the current main release, with prior source history retained.

The launch page and loaded dashboard distinguish an unavailable status from an unavailable connection. A response from the selected origin establishes contact even if the server returns HTTP 503 or its document fails validation. Show that the dashboard is waiting for current status, in blue. A trusted 503 may include deployment progress. An incomplete network transfer or a device reporting offline gets connection wording. A different origin cannot establish contact with Sentinel. These display facts do not extend evidence expiry, change retry ownership, or clear a dated amber or red warning.

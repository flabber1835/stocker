# Dashboard behavior during a PAPER deployment

The November 18 install trace showed that the financial observer was deliberately
stopped during fencing and validation. Current signed status may be unavailable
during those phases. The panel also receives a finite, diagnostic-only phase
from the deployment owner. It presents that phase separately from financial
health. Its HTTP and browser freshness rules still require the signed dashboard
to claim current data or allow acknowledgement. A refreshing tab identifies
itself and receives an empty retry response while its signed data is
unavailable. A fresh document request may receive the explicit last-known page.
Both surfaces show the owner's current progress when available. The optional
`X-Sentinel-Deployment-Progress` header carries the same URI-encoded phase on
HTML and `/panel.json` responses, including a signed-status retry.

A ready feed from the preceding close cannot establish that new closing work
is underway after the closing plan is scheduled. A verified local PAPER
configuration with an empty reviewed deployment mode reports that financial
activation has not been selected. When the installed authority also confirms
disabled automation and an engaged kill switch, it displays that fence.
A current, unsuperseded plan matching the active cycle, account, rollout and
session may be shown as saved and awaiting adoption while the new generation
checks it. Targets, readiness and execution still require the ordinary bound
plan.

Keep a single operator review entry for one continuing verification failure
with the same scope, financial subject, runtime and diagnostic. Preserve each
distinct original failed attempt in the append-only signed event store,
using a separate account- and scope-bound history for repeated attempts.
A verified result, a supersession, a new subject, changed runtime, changed
diagnostic or a new failure after acknowledgement opens a new review episode.
Existing review and diagnostic receipts remain readable. The review head,
acknowledgement and any current negative financial verdict retain their own
meaning.

The complete Health history card, including its explicit acknowledgement
action, belongs at the bottom of System details. That disclosure is closed
on first load and keeps its state through in-place refresh. The headline
continues to display current operator health when details are closed.

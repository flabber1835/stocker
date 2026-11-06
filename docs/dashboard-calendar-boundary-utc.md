# Preserve market deadlines across the UTC snapshot boundary

Decision: 2026-11-06, before implementation. Calendar APIs correctly return
market-local aware times. Operator health and signed dashboard snapshot clocks
use UTC. Normalize their derived output boundaries to UTC at the same instant;
retain strict UTC validation of input evidence and all original deadlines.

At 14:29:50Z, the finite observer recorded `SNAPSHOT_EXPIRY_INVALID`, followed
by recovery just after the open. A pure reproducer with the actual November 6
calendar and published preparation state produces the same refusal: the next
boundary is `09:30:00-05:00`, which is the correct opening instant but fails the
snapshot's UTC expiry predicate. Before that boundary becomes the earliest,
the short UTC leader lease masks the mismatch. After the open, published
preparation stops being visible and the mismatch disappears.

The duration round-trip hypothesis did not reproduce across 20,000 cases;
retained owner clocks show a live owner well beyond the incident. Preserve
those findings rather than attributing this failure to lease loss or rounding.

Convert the minimum human-health boundary and minimum operational snapshot
boundary using `astimezone(UTC)`. Do not replace their clock, add time, clamp an
invalid caller expiry, accept unzoned/non-UTC row evidence, or change the
calendar API. This also covers a nested plan timestamp expressed in market
time. Public health and signed expiry both retain the exact producer instant.

Test winter and summer offsets, the exact exclusive opening boundary, nested
plan clocks, explicit expiry extension refusal and non-UTC row refusal. Remove
each output normalization to prove the corresponding oracle fails. The
publication/owner/subject transaction and financial authority remain unchanged.

The current local e97a15753 runtime is genuinely running but its installation
remains at APPLICATIONS_STARTED. Preserve that distinction. The next complete
source map may retain its actual 454-module source closure
`c3eb52854101901c854cdf84b944ba5e0abcb0e077824ded15ca714b10161eab`
alongside all twelve unchanged retained maps. This compatibility witness grants
no financial or installation authority. Seal the exact seven reviewed runtime
changes (calendar outputs, independent backup clocks and row expiry, BIL routing,
recovery classification and the still quarantined activity account bracket)
and their source-map checker. Preserve
the original economic compiler and all installed predecessor bytes.

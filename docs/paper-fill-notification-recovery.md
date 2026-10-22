# Paper fill notifications and resting-order display

Decision: 2026-10-22. The unattended paper cycle submitted five orders, but the
notification dispatcher saw no native fill ledger rows. Order-status recovery
correctly learned cumulative fills; the installed adapter deliberately does not
claim complete native fill history. Notification delivery must not depend on
granting that stronger financial authority.

In owner-authorized local PAPER mode, the dispatcher runs a bounded GET-only
collector implemented in the execution layer. Enable it with an explicit,
persisted `SENTINEL_FILL_NOTIFICATIONS_SINCE` timestamp. Deployment selects the
start of today's exchange day, so today's missed fills are recovered without
replaying older trading history. The existing notification activation boundary
also applies. Normal release mode does not acquire this collector implicitly.

Select owned commands with positive cumulative fills not yet covered by fill
notifications. For each, read the exact native order and its paginated FILL
activities. Validate the existing account binding before and after the read,
native account UUID, immutable command/order/asset/side/quantity/terms, native
activity identity, execution time and economic coherence. Reuse the native
activity normalizer and fill integrity checks. A cumulative order average is
never synthesized into a native execution. Missing activities remain eligible
for later collection; partial fills and restarts converge by native activity ID.

The existing alert outbox stores the immutable notification receipt, including
native source evidence, under the same `fill:<order>:<native-fill-fingerprint>`
identity used by ledger-derived notifications. Cross-order reuse or changed
economics refuses. These receipts do not populate `sentinel_fills`, alter cash,
advance execution recovery, or assert complete history, settlement, performance,
or restore authority. Existing financial capability flags remain false. Each
collection has an 18-second deadline, at most three candidate orders, and at
most ten 100-row pages per order. Collection runs at most once per 30 seconds,
independently of order submission. Failures enter the existing alert queue and
do not prevent delivery of already queued notifications.

The dashboard's account and reservation readers run independently. Their
timestamps may differ by more than 60 seconds during an ordinary recovery
pass. Accept their match within the existing ten-minute observation lifetime,
preserving the original reservation timestamp and expiry. Require the exact
cash-minus-buying-power amount, cash-only multiplier, binding, commands and
native order terms. If a newer complete observation exists, it must positively
confirm the same entire working cohort; it cannot renew the old proof's clock.
Changed fills, extra/UNKNOWN orders, replacement, foreign identity, expired
evidence or unexplained cash still refuse.

Local deployment of these notification/display-only changes may preserve an
active generation after the new-submission cutoff while positively known DAY
orders rest. Stop application workers gracefully, require no SEND_PENDING,
UNKNOWN or CANCEL_PENDING commands and no unsubmitted actionable deltas, and
verify unchanged native automation configuration in both images. Preserve the
cycle, plan, binding, command identities/terms and control generation. Restart
the same applications and require native recovery to rediscover the existing
orders. Do not cancel/reissue orders, restart PostgreSQL, reset data, run backup
operations, or claim a new execution qualification from this deployment.

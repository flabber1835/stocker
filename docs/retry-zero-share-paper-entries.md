# Retry PAPER entries that rounded to zero

The November 13 PAPER opening sized MTD at zero whole shares. Wealth Core
could still own the same episode in its shadow book, but the account plan
carried forward zero as a fixed share target. Once the shadow entry became a
held episode, the account also lost the dollar reservation needed to evaluate
a lower price. Recomputing a proportional share count from the marked shadow
holding alone does not recover that reservation.

For new Alpaca PAPER protected-limit plans, record a versioned account sizing
basis. A validated predecessor projection with an explicit zero
BELOW_WHOLE_SHARE outcome can pass the original dollar intent to the next
decision. Require the same security, slot and signal, a positive continuing
shadow episode, no pending exit for the security and a strictly later decision.
The broker observation at plan preparation must show zero shares and no working
order for the retry.
A positive durable account target ends this retry and follows the existing
partial fill, expiry and restart rules. An already established retry remains
eligible after an unavailable price or a missed execution window while the
same episode continues. A same-session replacement may retain a previously
established retry. Historical basis versions keep their original replay.

Carry the original dollar intent into the new plan as a protected opening
proposal with a provisional account target of zero. Give it the same
deterministic slot order, current account scaling, remaining Core allocation,
raw price and share-unit proof, whole-share floor and cash headroom as a new
protected entry. This allows the plan preview and completed outcome to show a
buy or an explicit skip. Keep the scheduled opening window and the existing
cash, binding, commitment and uncertainty checks. Do not revise old plans,
create a Wealth Core order, alter the controller, transfer BIL dollars or add
fractional transactions.

Install through the existing backed PAPER post-trade application handoff
from the exact local 0ca281a receipt. The application source attestation
changes; the Wealth Core and controller identities, account binding, database
and command history retain their established proofs. Qualification covers
same-episode retry, another unaffordable open, later affordability, absence of
a reference, strategy exit, fill continuity, tampering and historical replay.

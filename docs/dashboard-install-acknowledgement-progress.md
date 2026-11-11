# Preserve notification history across supported acknowledgement

Decision 2026-11-09, before implementation. The separately journaled post-trade
verification recovery correctly refused a changed legacy alert-history digest.
The only change was the already-authorized supported exact-view dashboard ACK
after the original installation snapshot. That API updates acknowledgement
metadata in place and records a signed append-only operator-review event; the
installer currently hashes that mutable metadata together with immutable alert
payload. Preserve the refusal and the original receipt and notification digests.

Separate legitimate acknowledgement progress from rewriting history. For a
changed existing alert only, an explicitly selected backed adapter may prove an
UNACKNOWLEDGED/null-to-ACKNOWLEDGED transition. Reconstruct the original digest
using all unchanged current immutable alert fields and the only permitted old
unacknowledged metadata; it must equal the original retained digest. Require the
current full digest to equal the observed notification snapshot. Authenticate
the same-account/scope append-only dashboard ACK event with the existing runtime
review signing contract, and match its alert inventory, actor and exact database
clock to the current acknowledgement metadata and standard dashboard note.
Require delivered CRITICAL history, valid finite clocks and one unambiguous
matching authenticated event. Existing acknowledged metadata cannot be edited,
reverted or re-acknowledged through this allowance. Other notification groups,
including all already delivered receipts, retain exact subset equality.

Bind the retained digest to the current journal or its already-qualified direct
predecessor, with the same deployment and account ownership. Require the event
clock to be at or after the original PREFLIGHT_PASS journal event, which follows
notification capture. An older signed ACK cannot justify a later illicit
reversal to unacknowledged state. A legacy receipt cannot prove an ACK in the
small interval between capture and that journal event; refuse that ambiguity.
During a build draft, the healthy installed predecessor remains the admitted
runtime even though no candidate image has been built yet.

Perform this rare exception proof read-only against the exact admitted healthy
installed panel image, using one coherent bounded transaction. Refuse missing,
malformed, foreign, unsigned or contradictory evidence. No proof runs for an
unchanged digest. Do not remove ACK fields from the legacy digest, rebaseline the
old receipt, acknowledge anything, change financial authority, replay orders,
rebuild or restart services. Keep the proof scoped to existing authenticated
dashboard acknowledgement, rather than accepting arbitrary notification edits.

Qualification must exercise real PostgreSQL digest reconstruction and real
signed review events, including payload/identity mutation, altered or reversed
ACKs, actor/clock/note/scope mismatch, signature failure, missing/duplicate event,
deleted delivered history, and explicit adapter refusal. Retain omission
falsifiers for the original digest and event authentication checks.

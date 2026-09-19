# Rolling daily continuation

This opt-in boundary advances the canonical book established by the rolling
cold start. It calls the existing ShadowObserver and kernel, retains their
immutable genesis/session namespace, and issues no GO, VERIFIED verdict,
execution plan or broker authority. The separate
[rolling runtime](rolling-shadow-runtime.md) now wraps it with post-commit
authority and routes daily shadow-service work; paper automation remains separate.

## Admission before transition

Own an idle connection, require both schemas, take the common behavioral writer
lock and pin the current receipted operational snapshot. Authenticate the latest
checkpoint and require its exact observation, capital, strategy and runtime
identity. The reviewed genesis-publication identity remains part of that runtime
identity; it is not replaced with each day's publication. Independently bind the
current acquisition request to the same strategy. Recheck backup authority and
the source-final/next-open deadline before commit.

Advance exactly the next XNYS session, which must equal the current publication
frontier. Do not backdate current TICKERS into missed sessions. Multi-session
gaps require the separate [missed-session recovery](rolling-missed-session-recovery.md)
contract. Out-of-window anchors and unproven returning identities refuse with
named dependencies. No new genesis, default historical split anchor,
legacy reader fallback or retrospective performance segment is manufactured.

## Current input continuity

Verify both the checkpoint's retained snapshot and the new snapshot against
their sealed manifests. The prior snapshot is a live dependency until the next
checkpoint commits; original genesis price payloads cease to be required after
that handoff. Compare every overlapping price observation through the committed
cursor, including the complete identity key set. Raw prices, volume, split and
dividend economics remain exact. Per-security signal paths and the SPY and BIL
adjusted paths may change only by a proven uniform positive scale; the remaining
BIL fields remain exact. Comparison streams bounded snapshot rows, not all
historical decisions. A missing or unequal economic fact refuses.

Compare canonical metadata/sector facts for all previously known identities;
require them to remain present and unchanged. New identities may be introduced.
Retain historical listing/alias intervals through the cursor; only extensions
beyond the cursor may change their end dates without changing historical identity.
Compare the full historical ACTIONS prefix through the cursor, preserving exact
source siblings and terms. This deliberately conservative first continuation
contract refuses historical reference corrections even when their irrelevance
has not been proved. Future actions are allowed and are resolved by the existing
terminal/spinoff mappers. Validate bar-to-reference identities and retain the
canonical feed's exact per-security signal-anchor dates. Every retained live
feed identity must have its required anchor in the selected snapshot.

A rebase that requires changing historical ACTIONS dividend terms also refuses
under this exact-prefix rule. Allowing that case requires a later economic
reference-equivalence proof; a uniform price ratio alone is insufficient.

Only after these checks compose a versioned rolling continuity proof bound to
the prior state hash/version/cursor, next session and actual current publication.
The pure kernel validates that binding. This is a distinct bounded claim, not a
fabricated legacy whole-history mutation proof, and it does not rewrite the
publication's DATA_ONLY receipt. Commit the proof with exact canonical decision
inputs in the authenticated checkpoint and an append-only, session-addressed
behavioral input row. Each immutable session record binds that row's payload
hash. Rotating the checkpoint must retain every earlier input row for audit.

## Bounded checkpoint and atomicity

Keep the cold-start checkpoint unchanged as origin evidence. After the first
successful continuation, store a versioned signed advancing checkpoint in the
same behavioral cursor table. It names the latest immutable session record,
state/input/publication/snapshot, origin, preceding record/state and strategy
economics, continuity scope, precommit timing and PITR evidence. Use a distinct
HMAC purpose with the existing receipt secret. Update with compare-and-swap
against the authenticated predecessor. The session append, exact input archive
and checkpoint update share one transaction; any failure rolls all three back.
Restart verifies the current input archive against the signed checkpoint without
scanning earlier input payloads. Lost acknowledgement returns
the authenticated current result without another transition.

Extend the existing observer's record validation with an explicit trusted
checkpoint anchor. The rolling adapter supplies that anchor only after signature
and durable binding checks. Reuse the ordinary record/config/state and Core+BIL
economics validators on the anchor and new suffix. Read the immutable genesis
plus at most the anchor and one new record; unexpected later rows refuse.
Earlier decision payloads are audit history, not a routine restart scan. Original
genesis price payloads and historical transitions are never rerun. This changes
no legacy observer default or legacy VERIFIED policy.

Restart is a read-only repeatable-read transaction over the authenticated current
closure. An old cold-start API must refuse once continuation exists, rather than
returning an obsolete first state. Other book/segment/catch-up lineages cannot be
silently adopted. All new semantic modules join the production source identity;
existing deployment state cannot silently acquire this new implementation.

## Evidence required

Real PostgreSQL tests must advance pending first-day instructions into actual
canonical holdings, continue more than once, recover exact state after restart,
and compare the successor against the existing uninterrupted kernel. Falsify
overlap key/value/reference changes, wrong proof/state bindings, missing live
anchors, causal gaps, corrupt checkpoints, unexpected lineage, failed append or
checkpoint writes, stale CAS, deadline expiry and backup refusal. Show that
uniform rebases preserve the canonical successor and that expired origin price
payloads do not prevent later restart/continuation. No NAS or paper result is
implied by synthetic local evidence.

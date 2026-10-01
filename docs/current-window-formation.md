# Book formation with bounded daily inputs

## Decision

Restore 126 broker-free canonical ownership/controller transitions before the
first operational decision. Keep CURRENT_WINDOW_V1 candidate replacement,
isolated missing-candidate tolerance and protected ownership economics. The
production identity additionally names CURRENT_WINDOW_FORMATION_V1 so a previous
cash-only origin cannot be silently reused. Starting capital remains $50,000;
capital search and reserve sizing are deferred.

Startup acquires one immutable 426-session generation: 299 feature-only closes,
126 formation closes ending immediately before the operational decision, then
that decision close. Every formation decision and the operational decision loads
exactly its own trailing 300 sessions; SQL bounds exclude both earlier rows and
future closes. Current-information reference metadata initializes the book; this
does not claim historical vendor-vintage causality. Daily acquisitions return to
300 sessions. Historical 379-session research/startup identities remain distinct.

Reuse canonical Formation, authenticated progress/origin, read-only GO proof and
paper-observation proof. A separate same-generation continuity proof binds each
formation transition to its prior state, adjacent session and feature commitment;
it cannot authorize crossing publications. Keep shares, cash, pending orders,
peaks and controller memory at the handoff. No formation step creates broker
commands. Existing funded-account accounting and execution projection remain in
force; historical shadow gains are not deposits. Restart resumes committed state.

Acceptance must cover real publication to formation to first decision, exact
300-session slices, no future-close effects on earlier transitions, interruption
and restart, daily replacement after formation, unchanged gap/correction policy,
no historical execution commands, and rejection of cold or forged startup proof.
The additive feed migration admits 426-session storage beside 300 and 379.

## Offline provider comparison capture

A separate command downloads Sharadar and Alpaca for an explicit common symbol
set and 300-session axis, stores original response rows and preprocessed rows on
disk, and records coverage and acquisition parameters. It grants no publication,
strategy or broker authority and submits no orders. Sharadar stays production.

Compare raw open/close, split-only signal close and raw volume in separate named
fields. Preserve original prices/metadata/actions and provider identities; do not
infer permanent identity equivalence from matching symbols. Alpaca uses explicit
SIP and adjustment modes; Sharadar raw open is derived with closeunadj/close.
Provider-adjusted levels can have different bases, so subsequent analysis must
compare returns/rebased series rather than assuming equal absolute levels.

Use bounded HTTP timeouts/retries/pagination, environment credentials, secret-free
errors and request manifests. Save each completed response atomically and reuse
only an exact matching request on resume. Never treat an interrupted page chain
as complete. Acquisition is GET-only. Offline preprocessing can be rerun without
credentials or requests. Output stays untracked and no statistical comparison or
strategy simulation is embedded in the downloader.

# Current unattended paper operating contract

Decision: 2026-10-06. This document supersedes the operational timing, input
admission, formation-work and outage-source assumptions identified in the two
local design audits. Historical certification and research profiles retain
their named input semantics. Changes below require the new runtime's ordinary
CI, certified-image publication and deployment admission; they do not change
the running certified installation.

## Boundaries that remain

Wealth Core owns the canonical immutable book and selection rules. Sentinel
owns exposure. Execution alone reads and mutates an Alpaca PAPER account.
The pure alpha/controller transition, capital and whole-share accounting are
unchanged. No ticker exceptions, guessed share conversions, historical broker
orders, automatic book reset or broker-to-strategy feedback are permitted.
Each decision sees exactly its own trailing 300 exchange sessions. Cold
formation still uses 299 feature sessions and 126 canonical transitions from
one 426-session capture. Sharadar data remains available only for research.

## Source readiness and service installation

Installation, operator services and broker-free preparation can start at any
time. Trading activation remains separate and killed-first. Neither source
readiness nor installation uses a fixed 23:45 New York boundary.
The requested operational frontier is the latest *closed* XNYS session.
Preparation starts at market close and retries missing/unstable source input.
Market close is a causal lower bound, not a claim that a provider has finalized
every row. Complete benchmark/session coverage, unique identities, admissible
price domains and consistent inventory/action observations determine whether
an immutable observed snapshot can be published. Later provider corrections
remain possible and must never be described as impossible finality.

Data readiness is useful independently of whether that session's following open
has passed. A ready snapshot may form a book or support truthfully marked late
reconstruction. It does not authorize a historical trade. Actual activation
requires current reviewed inputs, account ownership and reconciliation; fresh
execution applies its own bounded market-session window.

## Canonical formation and reuse

Formation checkpoints are source/strategy/capital/runtime bound and authenticated.
GO preview, installation preparation and durable initialization reuse compatible
canonical formation work. An unavailable execution window must not discard a
formed state or force another identical replay. A moved publication cannot
reuse incompatible cached state by merely changing its hash. Admission and
restart independently authenticate the plan, checkpoint and final state.
Unadmitted preparation is not a shadow decision or broker authority.
An installation during an already-open session may commit its formed origin as
`STATE_ONLY_AFTER_OPEN`, with the actual clock. This origin receives only a
reconstruction receipt. A later fresh decision is required for prospective
paper authority; no receipt is backdated to make startup appear timely.
Operator services and the broker-free worker are installed immediately. The
fenced activation coordinator waits for the first actually attested prospective
decision, which may follow the origin's session. It uses that decision's actual
execution session and keeps the original formed origin and certificate lineage.

## Recovery after an appliance outage

Preserve the committed canonical book, controller, pending decisions and original
genesis. Prefer retained authenticated daily inputs when available. If a missed
day's original publication does not exist, the operational current-information
profile may acquire a new bounded window for that day using the current provider
observation. Record the actual acquisition/publication clock and the recovery
policy; never backdate a receipt or claim historical input availability.
Apply one canonical transition per missed session with durable restart checkpoints.
No missing-day transition creates broker transport. After catching up, execute
only current eligible intent through reconciliation. Input corrections can make
this reconstruction differ from an uninterrupted run; strict PIT research keeps
its previous refusal rather than adopting this policy implicitly.

## Candidate histories and population health

For an unheld candidate, use the contiguous usable tail following its last gap
or uncorroborated price-basis break. Wealth Core's existing minimum signal and
liquidity history decides eligibility; do not demand clean history outside those
dependencies or manufacture missing prices. Protected holdings, applied economic
events and controller witnesses are checked separately and never silently removed.
An unusable held economic input waits for usable authoritative terms and raises
a visible incident; irreconcilable state or authority corruption still refuses.

Distinguish discovered assets, fully classified assets, successfully observed
price responses, deliberate candidate exclusions and unexpected source loss.
Preserve the broad-universe floor and collapse detection. Do not count a known
historical gap as proof that a provider response was truncated.
Display-name changes do not invalidate price partitions. Symbol/UUID, selected
membership, share-unit and price-basis changes invalidate their actual dependencies.
Compatible completed partitions retain their original observation and deadline.

## Free-feed execution availability

Execution uses explicit raw IEX evidence; it never labels it consolidated SIP.
Do not turn a forming minute, temporary read failure or a missing observation for
one security into permanent zero entries for an entire plan. Retry pending
evidence within a bounded execution window and defer unavailable securities.
Retain canonical entry priority and funding dependencies when sizing the usable
subset. Required reductions and broker reconciliation remain independently
permitted. Persist sized quantities and price identities before transport;
UNKNOWN outcomes always reconcile rather than being retried blindly.

Current executable quote evidence may replace an exact first-minute print in the
operational policy. Evidence must belong to the same regular session, correct
instrument and raw-price domain and be fresh at sizing and submission. The
latest-quote API explicitly requests `feed=iex`; asks size entries and bids
value pending sales. A new quote read and available-cash check precede each
Alpaca BUY, with a final no-await timestamp check after mutation authorization.
Missing-price entries retain zero execution quantity and reserve their canonical
priority budget in the immutable projection. They are reconsidered under a later
canonical plan; already transported plans are never resized to chase new quotes.
operational increase window is bounded to the first ten regular-session minutes;
this replaces the old universal two-minute rule. Changed execution timing/prices
can change account quantities and fills and require separate execution evidence,
not a claim of historical performance equivalence. Long-only affordability and
exposure limits remain mandatory.

## Recoverable state and qualification

The formation cache is disposable calculation work, not financial state. An
unreadable, corrupt or incompatible cache is ignored with a visible diagnostic
and canonical formation is recomputed. Cache write failures never replace or
weaken durable database checkpoints. Retain at most four complete plan files;
cache eviction cannot change an admitted book or its database recovery cursor.

Financial book/checkpoint, publication and broker-command writes retain verified
backup/restore authority. Re-downloadable acquisition work is non-authoritative
staging; it must not consume the financial restore proof at every work checkpoint.
Before publishing/admitting its result, require the current verified recovery
boundary and renew through the supported producer when needed. This separation
does not make a corrupt backup, missing archive or unknown financial state safe.

Qualification must demonstrate installation/preparation at arbitrary clocks,
same-input formation reuse, narrow revision recovery, a whole-publisher outage,
old candidate gaps with clean recent tails, sparse free-feed prices, transient
source reads, restart and daily continuation. Compare unchanged pure transitions
on a frozen clean input. Exercise real Alpaca/OpenFIGI acquisition and complete
local GO with broker GETs only in a separate database/Compose project. Do not
interfere with the certified paper installation, invent certificates, submit
diagnostic orders or claim real paper/reboot qualification from fixtures.

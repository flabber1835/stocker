# Owned55 and historical startup at $50,000

Owner decision, 2026-09-22. Base: `ee23c894c97a2c4023654ce3a56a62728f5b061e`
(merged #430). This production change does not merge the research branches.

## Policy and ownership

Select a new `sentinel-compact-champion-owned55-v1` identity. Reuse #432's
independent owned-impairment state machine, changing its active ceiling to 0.55,
as evaluated in #437. Five consecutive closes with Core drawdown <= -0.10,
damaged breadth >= 0.88 and green breadth <= 0.20 enter the cause. Eight
consecutive closes with Core r20 > 0, damaged breadth <= 0.63 and green breadth
>= 0.20 release it. Missing observations never release an active cause.
Final allocation is min(existing champion allocation, owned ceiling). Existing
FAST/SLOW zero causes and REC8 recovery are unchanged. This addresses sustained
damage after acceleration has exhausted its headroom; it does not claim an
optimal policy or an improvement in every episode. No recovery bridge is adopted.

The durable state carries the owned latch, both streaks and the exact processed
session. Old profile states are not relabelled. New installations default to
$50,000 of explicit shadow research capital; broker capital never enters Core
or Sentinel. Existing explicit capital and checkpoint identity must agree on
restart. Execution projects the resulting weights and exposure onto independently
observed account capital; historical shadow returns are not paper deposits.

## Historical startup contract

The intended first-GO path is 252 indicator sessions followed by 126 economic
formation sessions ending immediately before the current decision. These are
trading sessions, not calendar days. The existing 300-session operational price
window remains bounded; formation advances the canonical kernel sequentially
and preserves state when old prices expire. Historical transactions cannot
create execution plans or broker commands. Ordinary restarts never replay or
reset the book. Formation adequacy is an acceptance question, not a claim that
126 sessions erase all path dependence.

Reuse canonical feature warmup and `advance_session`; no parallel strategy.
Require exact exchange-calendar coverage, dated benchmark history, permanent
security identities, explicitly identified security-type and first-observation metadata,
and complete action inputs including independently supported terminal terms.
Bind the formation policy, capital, strategy/source identity and every input to
the result. Checkpoint/resume must equal uninterrupted replay. Missing, changed,
future-dated or incomplete input evidence refuses before advancing state.

A hash or a claimed completeness boolean is not source authority. Production
admission requires an approved producer contract and retained evidence. A
locally constructed synthetic replay establishes mechanics only. It cannot be
installed as a live genesis or turn a research export into a certified input.
The ordinary shadow genesis still accepts only a cold book. The distinct
authenticated formed-origin contract binds formation evidence, live-window
continuity, publication identity and independent paper capital. Existing backup,
account, timing and execution gates remain required.

## Confirmed input dependency

Sharadar's [TICKERS documentation](https://sharadar.com/docs/tickers), inspected
2026-09-22, states that its bulk export is a snapshot and that all requested
history lengths return the same full table. Its schema keys are table,
permaticker and ticker; `lastupdated` filters updated rows, not past vintages.
This does not establish historical versions of category, sector or related
tickers. The production snapshot loader therefore correctly supplies prospective
metadata only. The legacy dated loader can read retained observations, but
cannot manufacture observations preceding its first collection.

The selected champion/Owned55 profile uses residual-correlation peers after
removing SPY's market contribution (`median5_breadth`), not sector membership.
The generic loader still carries sector labels for legacy profiles, but the
canonical kernel replaces their breadth calculation for this strategy. Historical
sector classifications are therefore not a startup decision dependency here.
The selected Median-5 eligibility route also does not use exchange membership
or `last_session`; its checks include common-equity category, `first_session`,
available price/volume history and signal validity. Admission keys are security
IDs (`SID:<id>`), not the legacy issuer-group diversification rule. Operational
source/anchor validation still needs permanent identities and related-ticker
evidence; this is not evidence that historical issuer groups drive selections.
The historical decision dependencies are permanent security/ticker identity,
eligible security type, first available session and dated price/action coverage.
First-session values also participate in stable peer tie-breaking. Do not
confuse fields carried by a shared loader with fields used by the selected
economic policy. Historical sector or exchange-membership archives are not
requirements for this profile.

Ticker continuity must use provider permanent identities and dated mappings,
not matching names or symbols alone. Sharadar documents `permaticker` as a
unique, unchanging security/share-class identifier and supplies first/last price
dates. Unambiguous source-backed mappings do not require daily archived names.
Do not extrapolate this identity guarantee into an undocumented guarantee that
today's category was known and valid on every earlier decision date. This
narrows the historical-vintage question to actual decision attributes and any
unresolved source mapping, rather than requiring arbitrary daily metadata dumps.

Alpaca's [asset catalogue](https://alpaca.markets/sdks/python/api_reference/trading/assets.html)
does not document historical as-of sector or issuer-classification queries.
Its [corporate-actions endpoint](https://docs.alpaca.markets/us/reference/corporateactions-1)
warns that record-creation timing is not guaranteed. Neither establishes the
missing historical metadata authority. Sharadar remains the production source.

Following the owner's instruction to proceed, fresh GO selects
`CURRENT_INFORMATION_INITIALIZATION_V1`: the admitted current Sharadar snapshot's
classification and first-price dates, permanent identities and dated symbol
mappings are applied to historical prices. This can change initial holdings and
controller state relative to a historical metadata archive. It initializes a
portfolio using information available at startup; it does not claim historical
PIT reconstruction. The separate `HISTORICAL_PIT_V1` research candidate policy
continues to require dated metadata. The policies have different commitments.

The twenty-year research export has known classification/issuer defects and
does not close the production evidence gate. Production must use the admitted
Sharadar producer with actual coverage and action terms checked across the full
formation interval. No silent fallback to cold formation is allowed.

## Fresh GO integration decision

First acquisition uses a distinct, exactly 379-session startup window: 252
feature closes, 126 economic formation closes, and the current decision close.
This window is permitted only for a fresh Owned55 lineage. It reuses the normal
Sharadar export generation, identity, action, completeness and publication
checks. Ordinary rolling acquisitions remain exactly 300 sessions. The initial
379-session generation is retained until ordinary retention can retire it; the
canonical strategy's bounded feed state remains unchanged. This avoids joining
two independently refreshed 300-session generations into a fabricated source.

Formation is a broker-free preparatory operation. It runs the canonical kernel
against the sealed startup generation, retaining authenticated progress bound to
that generation, the initialization policy, strategy, capital and runtime. A
changed source or configuration cannot continue an old candidate. An interrupted
candidate resumes only after its authenticated state and input binding verify.
The final genesis admission additionally requires an empty execution/strategy
lineage, current publication, next-open timing and backup authority. The
formation state is never accepted through the existing cold-seed exception.

The formed Core keeps its historical shares, cash and high-water marks; Sentinel
keeps its formed controller memory. The independent live strategy accounting
starts at the configured $50,000 baseline and execution projects weights onto
the paper account's available capital. Historical shadow gains are not deposits,
and historical formation decisions cannot create broker commands. Restart reads
the committed origin rather than replaying or rebasing it. Formed-origin identity
must survive ordinary advancement, restore and rolling retention.

Funding the formed holdings uses the existing decision-close, whole-share
basket projection. Already-held Core positions are not relabelled as new
Wealth Core dollar-entry intents. Actual pending Core entries retain their
ordinary opening-price sizing rules. Opening gaps, integer residuals and fills
can therefore differ from the scalar Core+BIL return model; the broker ledger
remains actual paper P&L authority. Startup does not change this execution policy.

Before admission, a newer source publication may replace an interrupted
formation attempt. Verify the old progress signature and canonical state first,
preserve it in a previous-attempt slot, then start a fresh replay against the new
generation. Never splice generations or reuse the old economic state. Keep one
active and one previous slot per observation; normal authenticated backup/PITR
retains earlier revisions. A capital, strategy or runtime change requires
explicit investigation and remains a refusal. After origin commitment, normal
restart always uses the origin and never starts another formation attempt.

The first funded open needs a distinct scalar accounting boundary. Undo that
day's hypothetical Core BUY/SELL fees, then charge the frozen 10bp entry model
once on the post-open Core holdings, using their actual raw opens and canonical
shares. Charge BIL's entry once as well. Core's internal cash is not purchased
and attracts no entry cost. This removes imaginary sales of a shadow portfolio
the new account never owned, and avoids both free entry and double counting.
Retain the dated opening marks in the authenticated observation. Subsequent
closes use the existing Core+BIL accounting contract. This scalar model remains
distinct from actual paper P&L, whose authority is broker fills and cash.

GO's read-only strategy proof must run this same current-information formation
before comparing the current transition with its restored-state transition.
The proof reports `ROLLING_FORMED_STARTUP_AND_RESTART`, its 126-session chain,
initialization policy and state commitment. A 252-feature-only proof cannot
qualify fresh Owned55 deployment. The read-only proof grants no origin authority;
the durable GO caller independently applies the authenticated admission path.

The dual deployment wait uses a separate bounded data-work budget, defaulting
to 7,200 seconds (`SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS`, range 30–7,200).
Process health retains its existing short budget. A verified shadow-status read
may take up to 300 seconds, capped by the remaining data-work deadline; success
after that deadline is refusal. This accommodates the measured 49-minute
formation and 78-second status read without extending the source-final or
next-open admission cutoffs. Startup that exceeds a causal cutoff remains
unadmitted, and authenticated progress is retained for investigation/resume.

The owner subsequently selected July 31, 2026 as the local bootstrap endpoint
and authorized reuse of the retained backtest data. Its exact 378-session axis
is January 29, 2025 through July 31, 2026: feature warmup ends January 29, 2026;
126 formation transitions start January 30, 2026. The slice has 2,345,187 rows
and 7,201 identities. SILV's known wrong metadata occurs on 12 warmup sessions;
its effect must be evaluated, not silently corrected. The archive uses
SEP-tape identities and SEC-derived issuer/FF12 metadata, not Sharadar's
permaticker and sector domains. It is a local mechanics fixture only.

Owner clarification: first GO on a new computer fetches fresh inputs and forms
its own book through the latest eligible session. No July research book or
checkpoint is deployed. The durable checkpoint is created only after that
local formation and is used by subsequent restarts. Consequently no operational
crosswalk from the research archive is part of the requested deployment path;
the production historical source must natively maintain its permanent identity
and metadata contracts. The July endpoint applies only to local validation.

The broker-free canonical formation component produces a source/plan/state-bound
candidate checkpoint. Input/session commitments form an append-only chain.
Preview/research callers use this component without granting trading authority.
Only the separate durable startup caller may admit its complete result through
the authenticated formed-origin contract. Existing GO continues rejecting a
pre-populated seed presented as an ordinary cold start.

## Finite Stage 1 acceptance ledger

The canonical GO composition audit must observe both legacy seed publications
and the new rolling publication through the version-dispatched authenticated
reader. Its synthetic source covers at least 379 closes and uses $50,000. The
successful path remains the real shell entrypoint, PostgreSQL, local-full test
lens, read-only formation proof, promotion and panel handoff; no broker keys
are supplied. The audit's outer deadline is three hours and the manual CI job
budget is four hours, accommodating the test lens and formation separately.
Production ingestion, source-final and execution admission deadlines are unchanged.

Manual composition dispatch may select `positive` to run that successful path
once without the four repeated sensitivity campaigns. The existing `all`
default still runs every campaign; normal PR CI retains its current smoke and
authority checks. Positive-only evidence has an empty sensitivity list and is
labelled explicitly; it cannot claim full stage-fault coverage. Rolling feed
preparation and readiness fault hooks must target the actual rolling callers,
with executable call-site witnesses that detect a disconnected hook.

| Gate | Required evidence | Current status |
| --- | --- | --- |
| Policy | Frozen-rule parity, exact entry/release boundaries, independent zero causes, missing signals, restart and identity falsifiers | Locally passed; eight targeted mutations killed |
| Capital | $50k default wiring; independent whole-share affordability and scaling witnesses | Locally passed; explicit existing capital preserved |
| Replay mechanics | 252+126 causal synthetic sessions, canonical Core, bounded state, action and identifier transitions, uninterrupted/resumed parity | Locally passed synthetic path; real archive preview remains unqualified |
| Historical producer | Selected initialization policy, required metadata and full action terms for the interval | Current-information initialization selected and implemented; real startup-generation coverage/actions must pass ordinary publication admission on deployment. Historical PIT reconstruction is not claimed. |
| Formed GO admission | Empty PostgreSQL to authenticated formed genesis, current publication/overlap, actual GO caller and independent paper baseline | Implemented; isolated PostgreSQL positive acceptance and full read-only GO formation proof pass |
| Failure recovery | Interruption, changed source, lost acknowledgement, duplicate start/order rejection | Authenticated progress, acknowledgement loss at 0/1/63/126, immutable origin restart and first funded daily resume pass; complete runtime regression retained in evidence report |
| CI and mutations | Relevant regressions, meaningful guard-removal faults, syntax and ownership checks | Twenty-two mutations killed (eight controller/candidate, five integration/accounting, three deployment timing, two price domains, four audit-only); final-head CI and full canonical GO positive campaign remain gates |
| Deployment | NAS backup/restore/resource evidence and paper transport qualification | NAS-only; outside local certification |

Local implementation acceptance does not close provider or deployment gates.
Do not report economic certification complete while required gates remain open.

Exact commands, intermediate failures, limitations and the qualification handoff
are retained in [the local evidence report](../audit/owned55-startup/README.md).

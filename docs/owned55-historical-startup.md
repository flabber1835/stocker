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
security identities, causally available classification/sector/issuer metadata,
and complete action inputs including independently supported terminal terms.
Bind the formation policy, capital, strategy/source identity and every input to
the result. Checkpoint/resume must equal uninterrupted replay. Missing, changed,
future-dated or incomplete input evidence refuses before advancing state.

A hash or a claimed completeness boolean is not source authority. Production
admission requires an approved producer contract and retained evidence. A
locally constructed synthetic replay establishes mechanics only. It cannot be
installed as a live genesis or turn a research export into a certified input.
The current shadow genesis deliberately accepts only a cold book. Do not relax
that guard until a distinct formed-genesis contract binds admitted formation
evidence, live-window continuity, publication identity and independent paper
capital. Existing backup, account, timing and execution gates remain required.

## Confirmed input dependency

Sharadar's [TICKERS documentation](https://sharadar.com/docs/tickers), inspected
2026-09-22, states that its bulk export is a snapshot and that all requested
history lengths return the same full table. Its schema keys are table,
permaticker and ticker; `lastupdated` filters updated rows, not past vintages.
This does not establish historical versions of category, sector or related
tickers. The production snapshot loader therefore correctly supplies prospective
metadata only. The legacy dated loader can read retained observations, but
cannot manufacture observations preceding its first collection.

The twenty-year research export has known classification/issuer defects and
does not close this recent-period evidence gate. Obtain retained dated Sharadar
snapshots or a separately reviewed authoritative interval export, with actual
coverage and terms checked for the chosen start/end. Do not use today's
classification retrospectively or silently fall back to cold formation.

## Finite Stage 1 acceptance ledger

| Gate | Required evidence | Initial status |
| --- | --- | --- |
| Policy | Frozen-rule parity, exact entry/release boundaries, independent zero causes, missing signals, restart and identity falsifiers | Pending local tests |
| Capital | $50k default wiring; independent whole-share affordability and scaling witnesses | Pending local tests |
| Replay mechanics | 252+126 causal synthetic sessions, canonical Core, bounded state, action and identifier transitions, uninterrupted/resumed parity | Pending local tests |
| Historical producer | Dated metadata and full action terms for the actual formation interval | BLOCKED: input not available |
| Formed GO admission | Empty PostgreSQL to authenticated formed genesis, current publication/overlap, actual GO caller and independent paper baseline | Pending producer contract |
| Failure recovery | Interruption, changed source, lost acknowledgement, duplicate start/order rejection | Pending integration |
| CI and mutations | Relevant regressions, meaningful guard-removal faults, syntax and ownership checks | Pending |
| Deployment | NAS backup/restore/resource evidence and paper transport qualification | NAS-only; outside local certification |

This ledger must be updated with exact commands and results. Do not report
Stage 1 or economic certification complete while required gates remain open.
An incomplete integration is delivered as a draft PR, explicitly not deployable.

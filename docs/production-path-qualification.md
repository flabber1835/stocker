# Production execution path audit and attended qualification

Decision recorded 2026-10-16 before implementation. The owner authorized a
comprehensive audit of the boundaries omitted by the October 15 rehearsal,
real Alpaca PAPER trades with at most USD 5,000 in open test exposure, no margin
or shorts, flat completion, and up to three reviewed merges.

## Incident

The October 16 cycle started at 13:31 UTC and created no commands. The active,
tradable PBR.A asset has the expected UUID, but the adapter converted its dot
to a hyphen before the authenticated source lookup. PBR.A resolved; PBR-A did
not. Retries exhausted the existing opening cutoff. Preserve that cycle.
The prior successful 11-stock rehearsal used a plan-derived reverse lookup
instead of the production feed resolver and contained no dotted class ticker.
Its native fills and recovery results do not qualify this omitted boundary.

## Decisions before implementation

1. Bind symbol spelling to the authenticated source provider. Alpaca operational
   inputs retain exact native symbols; legacy Sharadar inputs retain their
   reviewed conversion. Preserve dated permanent identities, native asset IDs,
   alias rejection and ambiguity refusal. No ticker-specific or fuzzy fallback.
2. Preparation/readiness must exercise the production resolver and broker
   factory for every proposed instrument. A dated GET-only admission check is
   not order authority: execution still rechecks account, tradability and fresh
   quotes. Saving targets alone cannot claim transport readiness.
3. Audit every replaced rehearsal boundary: source/account identity, broker
   construction and guards, opening quotes and quantity projection, cash/fees,
   immutable plan and pending evidence, before-send checks, commands, UNKNOWN,
   cancellation, service forks and restart. Preserve the one canonical book.
4. The attended profile may vary only its explicit grant, purse and intraday
   schedule. Reuse actual production input/resolver/factory and applicable paper
   gateway decisions. Name, justify and qualify any remaining replaced edge;
   matching source hashes do not prove matching callback wiring.
5. Pause production through supported controls before test mutations. Use an
   isolated test journal and attributable keys, preserve the book/failed cycle,
   cancel only this run's orders and close only its positions. No retrospective
   production buy, extended production window, account reset or cash constant.
6. Cover dotted/legacy classes, rename/reuse, wrong/ambiguous IDs, BIL, stale or
   partial quotes, delayed fees, cash restrictions, pre-transport refusal,
   accepted acknowledgement loss, partial-fill/cancel races and process death.
   Falsify new guards. Native race claims require observed provider evidence;
   deterministic fault coverage remains separately labelled.
7. Keep durability policy and daily backup cadence. Reuse one isolated current-
   book copy; retain failed attempts. Final CI, protected image certification
   and supported installation remain mandatory. Preserve the current book and
   report the actual deployed identity, account state and next eligible session.

The existing exact execution compatibility profile will additionally pin
`config.py`, `execution/feed_inputs.py` and `paper/targets.py`, alongside the
already pinned preparation module. Predecessors are committed source hashes;
successors are only the reviewed bytes in this change. This admits an execution
repair over the retained book without changing holdings, financial history,
source/date ambiguity rules or signed production authority. Update the named
paper lifecycle delta commitments for preparation and instrument mapping; keep
the historical equivalence manifest unchanged.

## Native audit finding: quote availability must not starve other names

The first October 16 native campaign proved correct PBR.A and PBR transport and
recovered its first accepted order without a second POST. It then found an
additional omission: no fresh IEX quote for ATEX aborted the remainder of the
sequential basket. Six names filled, later names were never attempted, and the
unchanged cutoff superseded the cycle. Retain this failure and flatten it.

Introduce a narrow typed quote/funding-not-ready refusal before transport.
Only the canonical membrane's consumed, exact, single-use no-transport proof
may restore that command to PLANNED and defer that security while attempting
the other independently authorized names. Never continue on UNKNOWN, rejection,
changed identity, stale lease, kill, malformed evidence, an arbitrary exception,
or an inner transport's imitation of that refusal. Preserve the same immutable
quantity/key for retry and the existing deadline. A deferred leg prevents basket
success; the UI and notifications must retain its actual reason.

The full-gateway attended campaign uses the unmodified ProductionAutomation
prepare/recover/execute callbacks and the public paper gateways. Its explicit
fixtures replace signed release authority and provide the authenticated retained
runtime context, bounded purse and intraday quote/schedule. It cannot receive
production certification. Signature/retained-source/fresh production authority
checks are qualified separately, then re-earned by the certified installation.
No simulated fixture may be reported as observed native exchange behavior.

The copied production physical anchor and an intraday-started private PostgreSQL
server must initially refuse increases; retain both negative results. Initialize
only the new, command-free attended fixture namespace. Its intraday startup
exception is limited to the exact private database/system identifier, unique
attended deployment and recorded real postmaster start, after a flat native
account observation and exclusive test ownership. A later database restart,
foreign namespace, restore mismatch or lost production fence must still refuse.
This is part of the owner-authorized test timing grant; production restart and
restore policies are unchanged and receive no exception.

## Callback publication lifetime

The full callback audit also exposes redundant integrity scans: preparation and
recovery construct the broker outside the paper gateway's publication pin, then
verify the same immutable snapshot again inside that gateway. Preparation's
postcondition starts another unscoped read. Execution already retains one
callback-wide publication pin. Apply that same lifetime to operational
preparation and recovery. The existing readiness-scope verifier reuses only a
completed content scan under the exact live PostgreSQL pin and manifest; it
rechecks receipts and lock ownership on every reuse. Do not cache readiness,
broker observations, signatures or grants. Release the pin on success and every
failure; writer acquisition remains nonblocking. Qualify the actual callback
wiring and measure the full native callback, including its postcondition.

## Returning the paper account after qualification

The owner authorized real paper tests without an account reset. Their realized
gain/loss belongs to the broker account and must not be hidden in Wealth Core,
copied into the production command journal, or corrected with a cash constant.
The production plan was never sent and its cycle is already terminal. Provide
an attended handback tool which verifies the approved test keys against native
terminal orders, zero net test shares, a flat account/no working orders, and
starting cash plus native fill cash flow against current cash. The starting
observation must agree with the old unsent plan within the existing one-dollar
cash tolerance; no new tolerance or activity-completeness claim is introduced.

While production is disabled/killed, an exclusive attended owner and the normal
backup-protected writer lock may record an HMAC-bound handback receipt and retire
only that exact unsent plan. Require no production commands/fills and a terminal
cycle; preserve the old plan, failed cycle, source publication and canonical book.
Ordinary preparation can then establish a fresh account basis; the scheduler's
missed-open rule still prevents a new late production buy. Refuse an unexplained
balance, foreign key/order, incomplete terminal evidence, net shares, active
lease, trading production account or changed plan. This is a narrow return from
the authorized rehearsal, not a general cash-rebasing or recovery override.

## Acceptance ledger

Record source, inputs, callback path, expected/observed transitions, native
methods/orders, preservation, cleanup, falsifiers and remaining limits for each
scenario. Cover today's entire instrument set and the actual scaled basket.
A terminal cycle without intended native orders is not basket success. Append
the audit findings and measured qualification before PR review or merge.

### Observed on October 16

The installed opening cycle was SUPERSEDED after its existing nine-minute
execution window, with zero commands and fills. The original cycle, plan and
canonical book remain retained. Production was disabled and killed at 13:49 UTC
before the first test order. No production order was replayed late.

| Boundary | Qualification and observed result |
| --- | --- |
| Production source to broker | Actual `ProductionAutomation._broker`, authenticated `ALPACA_OPENFIGI` resolver and native GETs resolved all 14 positive production instruments, including PBR and PBR.A. A separate native GET at 15:33 UTC also verified the canonical defensive BIL identity. No broker mutation in these preflights. |
| First service campaign | Six native buys and six closing sells filled. Accepted first DAR buy survived actual process death before local acknowledgement, with exactly one POST. Missing ATEX quote exposed starvation; preserve this failed/SUPERSEDED campaign rather than treating it as a pass. |
| Full production gateway | Actual prepare/recover/execute callbacks and paper gateway bodies; 12 stocks survived whole-share scaling to the USD 5,000 purse. All 12 buys filled; cycle SUCCEEDED, and a repeated service tick created zero commands. All 12 closing sells filled. |
| Quote deferral | ECPG and ETON lacked fresh native IEX quotes on the first execution. Ten other buys proceeded, including later basket entries. Both deferred names filled on the next execution within the unchanged cutoff; identical command keys and quantities were retained. |
| Direct API lifecycle | Four SPY market orders filled, one resting limit order was canceled with zero fills, and accepted acknowledgement loss recovered by exact key without another POST. The account ended flat. |
| Independent provider verification | All 41 native orders matched attributed keys and IDs: 40 filled, one canceled unfilled; no duplicate POST, positions or working orders. Both execution journals matched native quantities, prices, asset IDs and terminal states. |
| Account effects | Cash USD 49,988.72 before tests to USD 49,974.83 afterward: realized test loss USD 13.89. Exact fill arithmetic predicts 49,974.830004; native cents rounding accounts for the difference. This is paper test PnL, not strategy performance. |
| Adversarial guards | Wrong/foreign/ambiguous identities, legacy symbol domain, renamed securities, stale/malformed quotes, forged post-transport refusal, deadline expiry, lost lease/kill, wrong database/system and later restart are covered by targeted tests and new falsifiers. |

The full callback campaign began at 14:52:33 UTC; preparation, including its
postcondition, completed at 14:56:05. Its first execute returned at 15:00:00,
the deferred names were submitted by 15:04:26, the cycle succeeded at 15:06:12,
and cleanup completed at 15:08:24. Direct API probes ended at 15:14:14;
independent verification completed at 15:15:25. This demonstrates the attended
gateway under observed daytime conditions; it does not establish a latency SLA
at tomorrow's opening auction.

Private native records and failed attempts are retained under the operational
`production-path-audit-20261016` evidence directory. Its independent completion
record and native order list are the handback inputs; no account identifiers,
credentials or native order IDs belong in the repository. The handback must
run only after flat completion and review of this tool, before ordinary
preparation establishes a fresh broker cash basis.

### Reproducibility and limits

`tools/production_gateway_rehearsal.py` requires an isolated retained-source copy
and a fresh private execution namespace. Archive only copied scheduler history
before starting; preserve its source book and original production evidence.
The private cluster needs its own canonical database incarnation and verified
test backup media. A copied production physical anchor and a newly started
intraday postmaster must refuse before fixture initialization. Do not run this
driver against the production DSN or reuse a namespace containing commands.
Its owner/fence, database identity and command-empty checks are mandatory.

Native partial fills and cancel/fill races were not forced in this bounded
campaign; deterministic adapter/executor tests cover them. The actual production
opening auction, future liquidity, provider availability and future prices
cannot be promised by daytime tests. Signed image certification, retained-book
compatibility and supported production activation are separate release gates,
not consequences of an unsigned attended test. No test changed the daily
backup cadence or integrity-proof reuse policy.

### Targeted commands and results

All commands used Python 3.12 in the offline test image with `pytest -q -x
-p no:cacheprovider --tb=short`; paths below are under `tests/sentinel/`.
These groups overlap and must not be added as a unique-test total.

* **209 passed**: `test_quote_starvation.py test_guarded_execution_broker.py
  test_issue_183_alpaca_hardening.py test_opening_submit_freshness_boundary.py
  test_alpaca_execution_entrypoint.py test_paper_activation.py
  test_paper_package_architecture.py test_paper_composition_upgrade.py`.
* **175 passed**: `test_callback_publication_lifetime.py
  test_alpaca_source_codec.py test_paper_composition_upgrade.py
  test_operational_liveness_upgrade.py test_retained_readiness_upgrade.py
  test_automation_runtime.py`.
* **115 passed**: `test_paper_cli.py test_preopen_paper_gate.py
  test_paper_observation_authority.py test_alpaca_name_change_continuity.py
  test_published_alpaca_identity.py test_action_source_identity.py
  test_alpaca_restart_day_fence.py`.
* **184 passed**: `test_alpaca_execution_entrypoint.py
  test_alpaca_simulation_cash.py test_alpaca_simulation_review_regressions.py
  test_opening_submit_freshness_boundary.py test_v5_opening_execution_freshness.py
  test_paper_composition_gateway.py test_cash_grace_identity.py
  test_paper_plan_preview.py test_paper_plan_notifications.py`.
* **6 passed, 33 deselected**: `test_rolling_paper_inputs.py -k
  'production_alpaca_dual_preparation or preparation_cannot_report_ready or
  real_paper_preparation'`; **1 passed, 39 deselected** for its preparation
  preflight falsifier. Both fresh and restarted preparation refuse an invalid
  instrument instead of reporting ready.
* **17 passed**: `test_paper_rehearsal_handback.py`, including real PostgreSQL
  atomic receipt/retirement and rollback, immutable book and plan preservation.
* **57 passed**: `test_paper_service_rehearsal.py
  test_native_paper_rehearsal.py test_live_paper_rehearsal.py
  test_attended_gateway_boundary.py test_alpaca_source_codec.py`. These test the
  test boundary; they do not replace the native results above.

Final adjacent-path audit also removed the old saved-system rehearsal resume
branch's reverse ticker dictionary. Fresh preparation, saved-run resume and
service callbacks now all construct the authenticated production source broker.
The saved-run regression enters the actual resume body and proves the read-only
source factory is reached before any possible transport.

The new source-domain, quote-deferral, callback-pin and preparation guards each
have a falsifier. Local qualification deliberately did not rerun Wealth Core
tests: its implementation and economic accounting were not changed. Required
repository CI remains the exact-head release gate.

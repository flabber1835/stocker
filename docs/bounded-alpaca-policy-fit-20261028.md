# Bounded Alpaca/OpenFIGI controller fit

## Frozen design before numerical fitting

The owner authorized proceeding after explicitly acknowledging that parameter
optimization is historical fitting. This is one finite parameter family of the
existing Owned55 controller, not another return forecaster or a production change.
Use research branch `codex/capital-risk-research` and PR 542 only. Verified main
base: `bbcb728a972f483c9f76f2b0db2599b2134ab1bb`; initial research head:
`6bace0dc09efc8ea462df26854e82fae04ef3e9d`.

Keep canonical Wealth Core selection, admissions, holdings, stops, reviews,
cooldowns, native Sentinel and champion recovery unchanged. Compute that canonical
history once. The one-way architecture permits the final Owned55 parameter
variants to consume that same history without changing Core or parent decisions.
Each variant still owns its complete formation/controller and funded-account state.

Exhaust all 108 combinations:

| Existing Owned55 parameter | Registered values |
|---|---|
| entry damaged breadth | 0.50, 0.63, 0.75, 0.88 |
| entry confirmation closes | 1, 3, 5 |
| recovery confirmation closes | 3, 5, 8 |
| active exposure ceiling | 0.25, 0.55, 0.75 |

The existing 0.88/5/8/0.55 setting is included. All other predicates stay fixed.
These are deliberately limited numerical bounds, not a claim that this is the
best architecture or that continuous global optimality has been established.
New parameters have distinct private research identities. Never override a
production module, relax a source guard or relabel a checkpoint.

## Sources and history

Use only Alpaca bars/actions and anonymous free OpenFIGI mapping. Freeze the
whole retained 2026-10-03 Alpaca feed roster before fetching new prices, then
recheck exact asset ID/ticker/catalog identity and the production mapping contract.
Do not substitute the old 56-stock sample. Exclude unsupported/currently absent
identities explicitly, without replacing them based on performance.

Acquire 2023-04-03 through 2026-10-27 daily raw/split stock prices, and raw/all
SPY/BIL references, plus the corporate-action history needed to interpret them.
Use the canonical feature, eligibility, action and identity rules. Do not infer
split terms or use total-return stock prices for signals. Unsupported economic
actions or an unidentifiable owned instrument must refuse, preserve evidence and
prevent an admitted performance result rather than become a skipped trade.

The retained/current cohort and current metadata are survivor-conditioned.
Revised historical provider bars are not publication-time archives. Report these
as known-history limitations, not unseen validation. Current mappings do not
establish historical membership. No paid or additional vendor is introduced.

Each book has its own fresh 299-feature/126-formation history before the first
measured session, 2025-01-02. Train/select on 2025 target sessions only. The
subsequent 2026-01-02..2026-10-27 period is a locked chronological diagnostic,
not a fresh holdout. Selection code cannot consume its candidate return metrics.
Baseline and candidate use the same capital (50,000), timing and measurement anchor.

## Account and objective

Use a separately identified persistent-quantity research account: whole-share
BUYs, ordered cash funding, actual raw marking, exact action entitlements and
explicit fees. The historical fill model is idealized next-published-raw-open
execution. It is not production's 09:31 protected LIMIT/DAY order outcome.
Never compare its level to a differently modeled legacy baseline to claim gain.
The baseline must be reproduced under this same source/execution/account contract
before candidate scores are admitted. Stock/account fees must not duplicate
shadow rotation fees. BIL treatment must be explicit and independently checked.

The selected first account reference is the existing qualified persistent-stock
prototype with its declared defensive cash-factor proxy, now fed only by Alpaca
SPY/BIL adjusted references. Cash compounds by same-publication BIL all-adjusted
open/previous-close and close/open factors, with no second BIL dividend payment
or separate BIL shares. This is a modeled defensive sleeve, not bank cash or the
production ETF/order ledger. Retain its exact-fraction accounting and documented
rounding bound. The old date-bound 2008 runtime remains unchanged: a new versioned
adapter owns the 2025 origin and must separately qualify its initial projection.
It starts with 50,000 immediately before the first funded 2025-01-02 open, uses
the last formation close's known intent, skips any unfunded preceding overnight
return, and includes first-day trades/costs in reported performance. The baseline
and every variant use that same anchor. A variant owns its own exposure/account
state throughout formation and training. This model cannot be described as
reproducing protected PAPER fills.

Fit the growth/drawdown frontier on 2025. Report maximum attainable net growth
within the finite class at drawdown budgets equal to 0.50, 0.75 and 1.00 times
the matched baseline's training drawdown. Keep at most three distinct frontier
points, plus any strict joint improvement selected by maximum growth, with
deterministic ties by less turnover then profile ID. Lock the selection before
calculating selected 2026 returns. Preserve all 108 training outcomes, including
ties, no-treatment cases and refusals. A no-treatment setting cannot be evidence
of efficacy. Do not require improvement in every subperiod to report full-period
joint improvement; report stability separately.

## Bounded execution

Market-only acquisition can run privately on the existing host, reading only the
two named provider keys from the exact existing provider configuration. It may
call only asset catalog, market bars/actions and free mapping. It starts no
container, replay, database or service. Gzip raw replies; retain hashes, request
receipts and complete pagination. Bound request bytes, disk, elapsed time and
retries. No secrets in output.

Resource amendment before capture: observed host free space is only about
700 MB. Do not retain a broad plaintext capture on that disk. The collector may
instead send length-bounded binary response frames to a private Windows parent.
That parent streams an AES-GCM sealed archive into at most one 16 MiB temporary
ciphertext chunk, uploads each chunk to the existing approved encrypted research
release, verifies the server's exact size/SHA256, then removes only that exact
new spool file. No recursive or protected-file cleanup. Alpaca keys remain only
in the collector process and are never part of frames, payloads or cloud secrets.
The encryption key remains separately DPAPI-protected locally and in the already
approved research secret. There is no unencrypted financial cloud payload.

The stream's final manifest is necessarily last. A dedicated receiver must first
authenticate the complete ciphertext/GCM, then check every archive member and
the final inventory before exposing any inputs to a worker. The old first-
manifest extractor is not silently relaxed. Incomplete captures retain explicit
failed metadata and can never be admitted as complete financial inputs.

All canonical Core/account execution is on isolated GitHub-hosted compute. Source
and inputs are read only, outputs disjoint, network disabled in the financial
worker. Existing approved research encryption/key separation applies; no plaintext
market or financial payloads in public logs/artifacts. No local financial replay.

Before a full financial run, qualify actual input/source identity and feature
equivalence, then time the first five real formation transitions as a retained
prefix of this baseline. Use that measurement to bound the remaining runtime;
do not restart it as a new warmup. The initial processing ceiling is 3,600 seconds
within a 90-minute hosted job. Do not launch a knowingly over-budget full replay.
Stop/export receipts must be written inside the driver's finally block, including
on timeout. UNKNOWN workers never produce financial snapshots.

Reuse completed proofs where their source/model scope still matches. New work
needs only relevant input, baseline, accounting and continuation gates, not old
backup/restore campaigns. Preserve all prefixes and exact next-session adjacency.

PAPER, broker financial endpoints, production databases, main, deployment, shared
Docker/WSL/services/pagefile and protected historical evidence remain untouched.
No merge, promotion, PR 541 activity, new forecast fit or automatic expansion to
another rule family is part of this protocol.

## Input adapter and staged admission

The hosted input adapter owns a distinct immutable research publication, not a
production database or GO receipt. It verifies captured raw response hashes and
pagination before constructing packed, date-indexed price arrays. Every date's
eligible tail is determined from information no later than that date using the
existing `admissible_history` price/action rules. No future action removes a
security from an earlier universe. Current asset identities and mappings remain
an explicitly retrospective cohort limitation.

Reuse canonical `alpaca_bar`, `_vendor`, `feature`, `WindowFeatures`, `Formation`
and `advance_session`. Qualify the packed current-window feature assembly against
the uncached canonical `compile_rows` on actual broad inputs before admitting
financial transitions, and at subsequent boundary samples. Each publication
commits its actual date, source manifest, protected historical economics and
feature material. Formation uses its canonical same-version proof; measured
sessions use strictly increasing current-window versions. No financial kernel,
config guard or serialized source identity is patched.

Structural events without supported terms reset an unowned candidate's history
only from their dated occurrence onward. An affected protected dependency, an
unknown economic date, or an unavailable owned price refuses with its exact
predecessor. Cash dividends and explicit forward/reverse splits use the canonical
normalization and settlement model. This first adapter does not manufacture
merger/spinoff proceeds or silently reinterpret unsupported terms. BIL split-only
corroboration is a separately bound market-only supplement before admission.

The first hosted stage authenticates inputs/runtime, qualifies the new input
adapter, and advances the canonical baseline's first five actual formation
transitions. It preserves its warmup origin, checkpoints, append-only journals
and exact prefix commitments. A measured throughput refusal is a saved incomplete
baseline, not an optimization result. Only a complete admitted Core trace may
feed the 108 private controller/account trajectories. Their selection and
accounting qualification remain separate gates; an input/timing success alone
does not mean a performance candidate was evaluated.

The new canonical worker has its own exact selector and resource contract:
8 GiB memory with no swap, two CPUs, 64 PIDs, read-only root/source/inputs,
no network, no added capabilities, no new privileges and no credential
environment. It does not broaden the older two-GiB worker selectors. It records
and fsyncs the exact stopped identity inside `finally` before timeout propagation.
Full stopped evidence and a separate bounded encrypted summary are exported;
the small local disk must not force downloading a large full archive. A separate
stopped-evidence review is still required before numerical interpretation.

The stopped-baseline reviewer is a separate offline process with the financial
output mounted read only. It checks append-only journal framing/chains, every
retained canonical checkpoint and controller state, source price preimages,
ledger cash/share/claim movements and raw close marking. It replays only the
small registered controller leaves from recorded source observations; it does
not create another Core or advance an account. This gate may admit a preserved
partial prefix for continuation while explicitly refusing a complete-run or
performance claim. A complete reviewed Core input trace still is not a funded
account result.

## Market-capture TLS recovery, before any financial origin

The first collector stopped after 1,321 replies on a TLS read error not covered
by its transport retries. Its 188,579,876-byte ciphertext is complete/GCM-sealed
and server-hash verified, but its manifest is FAILED and its capture INCOMPLETE.
Never relabel it COMPLETE. No financial job began.

A separate price-suffix collector may reuse only that exact authenticated
prefix. It re-requests the last completed page and requires its exact raw
SHA256/length before learning the next page token; a changed predecessor refuses.
That corroboration is explicitly marked and cannot count as a second price page.
It then acquires only remaining frozen-query pages/groups and benchmark replies,
with bounded TLS retries and 900 seconds of additional acquisition time. Completed
classification/actions/raw-price requests are not repeated. The original source,
failure, receipts, payload and encryption inventory stay immutable.

The receiver has a separately selected failed-prefix scope; its ordinary
COMPLETE-only extractor remains strict by default. Complete financial input
admission requires both full GCM/inventories, the exact successor binding and
predecessor corroboration, complete combined pagination/query-plan coverage and
all source price/action checks. A composite dataset digest binds both captures,
the BIL supplement, the roster and unchanged protocol. It does not claim atomic
provider publication or publication-time history.

The first suffix attempt correctly refused a changed wire SHA with equal byte
length. Before any relaxation, independently authenticate both complete encrypted
archives and inventories and compare the actual entire JSON values, preserving
array order and scalar types. A two-pass streaming verifier first authenticates
without parsing, then extracts only the required preimage into bounded memory;
it creates no broad local plaintext archive. Only a proven JSON object-order
difference may support a separately documented successor rule. Any changed
number, field, list order or continuation token still refuses. The original
byte-exact refusal remains evidence and is never relabelled as a pass.

Actual comparison passed: the two full authenticated preimages have identical
typed JSON values, ordered arrays and next-page token; only object serialization
order changed. Capture 002 remains a failed byte-exact attempt and serves only
as an authenticated corroboration witness. The next suffix uses that already
proved cursor, rather than repeatedly requesting an order-unstable JSON page.
Hosted admission must independently recompute the equality from both ciphertexts
and bind the witness into the composite dataset before any financial origin.
The second attempt's literal transport/manifest status is `INCOMPLETE` (exit 1),
not `FAILED`; preserve those exact bytes and the underlying refusal. Its explicit
witness extractor scope requires that literal status and grants no financial
admission by itself. The first TLS prefix remains literally `FAILED`.

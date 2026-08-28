# Backtester context checkpoint 02 — 2026-08-28

This supplements `backtester/CONTEXT_CHECKPOINT_2026-08-28.md`. It records all developments after that checkpoint. Read both files when continuing in a new context window.

## Frozen production boundary

Production/main remains untouched. All research work is on `research/backtester` and continues to pin exact production source:

`c502d077cae9c494f8b74a41ee8be7f40b25837d`

A/D semantics are unchanged: Wealth Core must be identical in A and D; A uses current Sharadar sector grouping at Sentinel, D uses strict-prior SEC SIC -> frozen FF12 at Sentinel.

## Focused diagnostic completed: second unresolved-open boundary

Run `33191669062`, job `98918416889`, completed successfully as a diagnostic.

It proved the original CIT/Litton repair works and then captured the next boundary:

- failing session: `2001-11-14`
- unresolved security: GPU, security_id `121383`
- held shares: `204677`
- entry: `2001-10-25`, raw open `$40.20`
- prior Wealth Core close: `207153688.41`
- failing-session Wealth Core close: `207642156.26`
- Wealth Core open: unresolved/null
- A effective exposure before open: `0.55`
- A pending target for the failing open: `1.00`
- A NAV before session: `2.530800935565071`
- nearby Sharadar ACTIONS: GPU `delisted` and `acquisitionby` on `2001-11-06`, vendor value `4828.2` (aggregate deal value, not per-share consideration)
- last normalized GPU bar: `2001-11-06`, open `40.50`, close `40.39`

The error remains the intentional exact-accounting guard:

`A allocation transition coincides with unresolved Wealth Core open; exact next-open attribution is impossible`

## GPU / FirstEnergy merger research and economic treatment

Source research established:

- FirstEnergy/GPU merger became effective November 7, 2001.
- GPU shareholders could elect cash or FirstEnergy stock.
- Cash consideration was `$36.50` per GPU share.
- Final stock exchange ratio was `1.2318` FirstEnergy shares per GPU share.
- Aggregate transaction consideration was constrained to 50% cash / 50% stock.
- Actual stock elections were oversubscribed.
- The merger agreement specifies that under oversubscribed stock elections, **No Election Shares receive $36.50 cash per GPU share**.

The strategy/backtest made no shareholder election. Therefore its deterministic contractual entitlement is the No Election Share treatment: `$36.50` cash/share. Do not model a FirstEnergy stock election for this strategy holding.

For the exact diagnostic holding:

`204677 * 36.50 = $7,470,710.50`

Do not state that every GPU shareholder received cash. The cash treatment is specifically correct for the strategy's no-election shares under the actual oversubscribed-election outcome.

Frozen GPU record was added to:

`backtester/data/causal-terminal-terms-v1.json`

Record semantics:

- ticker `GPU`
- security_id `121383`
- kind `CASH_MERGER`
- effective_session `2001-11-07`
- known_by `2001-11-07`
- cash_per_share `36.5`

Commit adding GPU record:

`fedabeaafe1a2cbaea055b8113d60d63908fdd3a`

Current frozen terms digest:

`9e3ae3944a1806a659afeca9e52b7b6d0f673d9c7355a242e50099a906e6556d`

Checksum commit:

`11c3e499a5d956063262db1112808c1fcdcfa155`

The checksum was exercised by the loader in GitHub Actions and passed before later harness-specific failures.

## Terminal verification updates

The previous causal-terminal integration workflow assumed the frozen term file contained only May/June 2001 events and passed a replay axis containing only `2001-05-30` and `2001-06-01`. After adding GPU, the strict loader correctly rejected GPU `2001-11-07` as off-axis. This was a verification-harness defect, not a settlement defect.

The integration workflow has been rewritten to include all three repaired events and exact production settlement checks:

- LIT1 `$80/share` cash merger
- CIT.A `0.6907 TYC/share` conversion with `$49.91256` exact fractional cash for 295,584 CIT shares
- TYC `2001-06-04` open valuation
- GPU 204,677 shares -> exactly `$7,470,710.50` cash, holding extinguished

Workflow:

`.github/workflows/backtester-causal-terminal-integration-verify.yml`

Update commit:

`2f18e7bfb4cedf8207bd207521a4b165eb8b29d4`

A dedicated GPU verification workflow was also added:

`.github/workflows/backtester-gpu-terminal-verify.yml`

Its first launch failed during Python package setup because the minimal workflow omitted the pinned production dependency closure; no GPU settlement code executed. The workflow was then corrected to install exact `main-src/sentinel/requirements.lock` plus the shared package.

Corrected GPU workflow commit:

`fee0cad421825ff41e1d26ee1c6d94d583aac8b9`

Do not treat either pre-fix workflow failure as evidence against the GPU terms.

## Updated A/D v2 digest guard

`.github/workflows/backtester-sector-ad-v2.yml` previously hardcoded the old two-record digest `f93a3ac...`.

It now pins the new three-record digest:

`9e3ae3944a1806a659afeca9e52b7b6d0f673d9c7355a242e50099a906e6556d`

Commit:

`89d70f046862c5fde8df1856bb9fd44ee0ffbab3`

This workflow change itself triggers a fresh v2 replay. It is still the unoptimized authoritative-style runner; do not substitute its partial output for a final result.

## Shared-Wealth-Core acceleration

Optimization file:

`backtester/run_sector_ad_shared_wealth_core.py`

Design remains:

1. A enters production `plan_session()` with canonical Wealth Core inputs.
2. Complete pre-plan Wealth Core mutable state is deep-snapshotted.
3. A executes the real frozen-main Wealth Core plan once.
4. Exact post-plan Wealth Core objects and the returned `LiveSessionPlan` are deep-snapshotted.
5. D reaches the same `plan_session()` call.
6. D must have exactly equal pre-plan Wealth Core inputs; any difference fails closed.
7. D receives exact deep-copied A post-plan Wealth Core objects and plan.
8. D continues through normal production Sentinel breadth/controller/Concordance/LD-RC using D's FF12 sector map.
9. Existing base-runner session-by-session Wealth Core parity remains active.

No approximation, sampling, skipped sessions, reduced universe, changed price, changed accounting, or prerecorded decision path is allowed.

## Equivalence harness failure and repair

Run `33196651817` executed all 252 baseline sessions through `1998-12-31`, then failed in the base runner's final full-corpus split audit because a deliberately truncated one-year replay had 19 unresolved split reconciliations. The optimized phase never ran.

Baseline elapsed time from that failed harness:

`1699.01 seconds` (~28.3 min for 252 sessions on that GitHub runner).

The bounded equivalence harness was corrected so both baseline and optimized paths suppress only the **post-replay final split certification audit**. All 252 session normalization/economic computations remain unchanged. The harness still requires byte-identical deterministic economic output.

Runner support commit:

`55d2556d356b36bb3765bcf946303b7b0792d6e0`

Workflow repair commit:

`d053d7d63929a274e322ab0ac0786dc125ba8ce4`

Fresh corrected equivalence run:

- run `33210057040`
- job `98980827065`
- last checked status: `in_progress`, baseline 1998 phase running

Acceptance gate remains:

- baseline and accelerated `daily.csv.gz` byte-identical
- baseline and accelerated `metrics.csv` byte-identical
- exact 252 sessions
- shared-WC runner's input-equality and state-parity assertions stay active
- measure baseline and optimized wall-clock time

Do not call shared-Wealth-Core optimization certified until this passes. A 1998-only pass is a strong implementation check but should still be supplemented by a period where A/D Sentinel states diverge or by the complete replay with all parity gates active.

## Full unresolved-open scanner

Corrected scanner run:

- run `33196508963`
- job `98934905157`
- last checked status: still `in_progress`, step `Scan full chronological A path`

The scanner was launched before GPU was added to the frozen terms. Its purpose is to discover the historical list of unresolved-open boundaries while continuing production-state traversal. It explicitly marks overlay NAV non-authoritative after the first unresolved boundary. Production strategy state does not consume that research overlay NAV.

When it completes, extract every recorded session/security. Use the output as a repair queue. Re-run a scanner with the expanded terminal bundle after those repairs to prove the queue is cleared.

## Latest known active/relevant runs

- `33196508963` — full unresolved-open scanner — in progress at last check.
- `33210057040` — corrected shared-Wealth-Core equivalence — in progress at last check.
- `33210465708` — corrected dedicated GPU verification — launched after dependency fix; inspect current status.
- terminal integration workflow triggered after commit `2f18e7...`; inspect its new run and require PASS.
- fresh v2 A/D replay(s) were automatically triggered by terminal-term and workflow changes. They are secondary until the historical blocker queue and acceleration certification are resolved.

## Immediate continuation steps

1. Check corrected GPU verification. Require exact `$7,470,710.50` production cash settlement and position extinction.
2. Check rewritten terminal integration workflow. Require LIT/CIT/TYC/GPU all PASS under exact pinned production source.
3. Check equivalence run `33210057040`. If baseline and optimized both finish, extract elapsed seconds and byte-equivalence result. Investigate any divergence before relaxing a gate.
4. Check scanner `33196508963`. If complete, download/read its artifact and enumerate every remaining unresolved-open boundary.
5. For each scanner boundary, research authoritative historical settlement terms and append only source-backed causal terms. Never use Sharadar aggregate deal value as per-share settlement.
6. Re-run a full scanner after the term bundle is expanded and require zero unresolved-open allocation boundaries.
7. Once shared-Wealth-Core equivalence is proven, use the accelerated runner for the full A/D replay with all existing parity, exact-open, causal-data and provenance checks active.
8. Add exact checkpoint/resume after acceleration validation so a late infrastructure or new-data failure does not require replay from 1998.
9. Consider immutable hash-bound pre-normalized SEP input caching only after the shared-WC optimization is certified.

## Final-result rule

No partial or failed run's CAGR is authoritative. Final A/D metrics require a complete chronological replay through `2026-07-31`, exact next-open accounting, complete source-backed terminal settlement for held path-dependent securities, active A/D Wealth Core parity, frozen input hashes, exact production source pin, and successful result-bundle verification.

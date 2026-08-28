# Backtester context checkpoint 03 — 2026-08-28

Read this after `CONTEXT_CHECKPOINT_2026-08-28.md` and `_02.md`. This file supersedes any stale status/digest details in checkpoint 02.

## Immutable production boundary

All research remains on `research/backtester`. Production/main is untouched.
Exact production source remains pinned to:

`c502d077cae9c494f8b74a41ee8be7f40b25837d`

A/D contract remains:
- Wealth Core economics/path identical in A and D.
- A Sentinel grouping = current Sharadar sector.
- D Sentinel grouping = strict-prior SEC SIC -> frozen FF12.
- No sampling, skipped sessions, reduced universe, approximate prices, prerecorded decisions, or changed accounting is permitted.

## Current frozen terminal bundle

File: `backtester/data/causal-terminal-terms-v1.json`
Current SHA-256:

`b9a143e84548e2569391aa8080d75b97034d61187c81f40319f640480fb16a4a`

Events:
1. LIT1 sid `120448`: CASH_MERGER, effective `2001-05-30`, `$80/share`, known_by `2001-04-30`.
2. CIT.A sid `122131`: CONVERSION, effective `2001-06-01`, `0.6907 TYC/share`, delivered TYC sid `573113`, fractional CIL price `$57.45`, known_by `2001-05-31`.
3. GPU sid `121383`: CASH_MERGER, effective `2001-11-07`, `$36.50/share`, known_by `2001-11-06`.

GPU causality rationale: merger agreement election deadline was 5:00 p.m. on the business day before the effective time. With effective date Nov 7, the election population was fixed after Nov 6 close. Actual stock elections were oversubscribed. The agreement sends No Election Shares to `$36.50` cash. The strategy made no shareholder election, so this is its contractual treatment.

Diagnostic GPU holding: 204,677 shares -> exactly `$7,470,710.50` cash.

## Current terminal certification evidence

### Dedicated GPU production verification
Run `33210898244` completed SUCCESS on the current tightened digest.
Verified:
- checksum OK
- sid `121383`, ticker GPU
- effective session `2001-11-07`
- 204,677 shares
- `$36.50/share`
- exact cash proceeds `$7,470,710.50`
- GPU holding extinguished

### Expanded production integration verification
Run `33210898223` completed SUCCESS on the current tightened digest.
Verified together:
- LIT1: 10 shares -> `$800` settlement proceeds
- CIT.A: 295,584 shares -> 204,159 TYC shares
- CIT fractional cash-in-lieu: `49.912559999802035`
- TYC 2001-06-04 raw open: `56.9`
- GPU: 204,677 shares -> `$7,470,710.50`
- current terminal bundle digest `b9a143...`

### Current term-bundle schema/terms verification
Workflow `.github/workflows/backtester-causal-terminal-terms-verify.yml` was rewritten for the current three-event bundle.
Run `33211232016` completed SUCCESS.

### Obsolete June-only boundary workflow
`.github/workflows/backtester-causal-terminal-boundary-verify.yml` assumed a two-event bundle and a replay axis ending 2001-06-04. A strict loader cannot load the later GPU event onto that axis. It has been retired from automatic push triggering and now documents that expanded integration verification supersedes it.
Retirement commit: `6a3b2bb0560da4031e11d7f71bcb33dfde359137`.

Do not treat historical red runs from the two-event harnesses as terminal-economic failures.

## Original A/D failures and repaired boundaries

Original 2001-06-04 unresolved-open failure was CIT.A/LIT1 related. Current terminal bundle resolves that boundary exactly; observed repaired open equity:

`242839480.805039`

Focused diagnostic run `33191669062` then found the next hard boundary:
- session `2001-11-14`
- GPU sid `121383`
- 204,677 shares
- A effective exposure before open `0.55`
- pending exposure for that open `1.00`
- Wealth Core open unresolved because GPU settlement terms were missing

GPU is now source-backed and production-verified as above.

## Shared Wealth Core acceleration

File: `backtester/run_sector_ad_shared_wealth_core.py`

Design:
- A executes exact frozen-main `plan_session()` once.
- Complete pre-plan state is deep-snapshotted.
- Complete post-plan mutable Wealth Core state plus returned `LiveSessionPlan` is deep-snapshotted.
- D must present byte/equality-equivalent pre-plan Wealth Core inputs.
- D receives exact copied A post-plan state and then continues through the normal production Sentinel/controller/LD-RC path with D's FF12 sectors.
- Base runner's session-by-session Wealth Core parity assertion remains active.

Bounded equivalence harness fixed the earlier post-replay split-audit problem without altering any simulated-session economics.
Current corrected equivalence run:
- run `33210057040`
- job `98980827065`
- last checked: still `in_progress`, baseline through 1998 running; optimized phase pending.

Historical failed harness `33196651817` completed all 252 baseline sessions and then failed only in the truncated-run final split audit. Measured baseline elapsed there: `1699.01 seconds`.

Do not call the optimization certified until run `33210057040` completes and baseline/optimized economic outputs are byte-identical.

## Scanner state

### Original allocation-collision scanner
Run `33196508963`, job `98934905157`.
Last checked: `in_progress`, full chronological A scan active.
It was launched before GPU was added. Preserve it; it may provide a useful earlier repair queue.
Limitation: it records unresolved opens at allocation-transition collisions.

### Comprehensive held-terminal-gap scanner
New file: `backtester/diagnostics/scan_all_held_terminal_gaps.py`
Workflow: `.github/workflows/backtester-scan-all-held-terminal-gaps.yml`
Run: `33211049538`, job `98984067249`.
Last checked: `in_progress`, full chronological A scan active.

This scanner is broader and uses the current GPU-inclusive bundle. It records every held security in Wealth Core's `open_unresolved_security_ids`, even when Sentinel does not change exposure. It groups gaps by security/entry episode, records first/last unresolved session and collision sessions, and continues production-state traversal. Research OverlayAccount NAV is marked non-authoritative after the first unresolved allocation collision. Production SessionState remains the exact state being scanned.

This comprehensive scan is the preferred repair queue.

## Latest unoptimized A/D v2

The v2 workflow digest guard now pins current digest `b9a143...`.
Latest run from that update: `33210946520` (last known in progress).
This is unoptimized and is not expected to be the final efficient execution path.

No partial CAGR from any active/failed run is authoritative.

## GitHub-hosted runtime ceiling / checkpoint requirement

A practical constraint is now explicit: GitHub-hosted jobs have a finite multi-hour job ceiling, and the original dual replay can approach/exceed it. Even if shared-Wealth-Core acceleration gives the expected material speedup, restart checkpoints remain desirable for financial-grade recoverability.

Exact checkpoint/resume design must persist all path-dependent simulation state, including:
- production `SessionState` for each distinct Sentinel arm
- research OverlayAccount state (NAV, effective/pending exposure, transition counts/costs)
- last Wealth Core close used for interval accounting
- cumulative split factors
- seen-security counts used for feed anchors
- prior signal-close anchors/indexes
- latest causal ticker labels by security
- chronological session pointer
- cumulative daily output needed for final metrics
- exact input hashes, production SHA, runner SHA, terminal-bundle digest

Resume must re-read/verify the frozen corpus and continue only after a checkpoint identity/hash match. It must not use prerecorded strategy decisions. A restart-equivalence test must compare uninterrupted and checkpoint/resumed runs session-by-session before this is trusted for final results.

## Immediate continuation order

1. Check equivalence run `33210057040`. Extract baseline/optimized elapsed time and byte-equivalence result.
2. Check original scanner `33196508963` and comprehensive scanner `33211049538`.
3. Use comprehensive scanner output as the source-backed corporate-action repair queue. Research each held gap using authoritative historical terms. Never treat Sharadar aggregate deal value as per-share settlement consideration.
4. Re-run comprehensive scanner after repairs and require zero economically relevant held unresolved terminal gaps.
5. If shared-WC equivalence passes, run an additional equivalence interval that reaches an actual A/D Sentinel divergence, then promote the shared-WC runner for full A/D work.
6. Implement exact checkpoint/resume with an uninterrupted-vs-resumed equivalence gate so the full chronology can be split safely across bounded jobs.
7. Final A/D replay must reach `2026-07-31` and pass output hashes/provenance, exact next-open accounting, full Wealth Core parity, PIT causality rules, and terminal-gap clearance.

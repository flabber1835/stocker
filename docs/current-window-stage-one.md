# Current-window Stage 1 revalidation

Review baseline: PR #461, `afa2242b9c921f0a2db7a23ce827fa853bd31952`,
based on main `13bc3c987e839b6ce2d5d699bcb3b5bfd208d739`.
This is bounded revalidation of the changed input/startup policy, not a new
historical performance certification. The 300-session/fresh-capital decision is
in [current-window-production.md](current-window-production.md).

## Scope and acceptance plan

| Stage 1 item | Changed claim and required evidence |
| --- | --- |
| L01 | Correct failing CI fixtures and rerun their owning checks; final GitHub CI remains required. |
| L02 | Independently recompute current-window momentum, log-return volatility, score and liquidity; reconcile first funded-open cash, fees, shares and NAV to published raw prices. |
| L04 | Reuse unchanged command-identity tests; revalidate new state through absence/recovery and compare with uninterrupted execution. |
| L05 | Reuse the new split/rebase, protected cash-event, unheld revision and observed/renamed anomaly tests; preserve long-only ownership and entry-price units. |
| L06 | Verify new feature-bearing checkpoints after real physical PostgreSQL restore, advance the restored book, and reject corruption without mutating the original. |
| L08 | Exercise retained dated snapshots and retention during missed-session recovery; old-policy prepared snapshots require replacement before GO. |
| L10 | Record production callers, exact commands, outcomes, falsifiers and explicit limits in this document. |

L03 native broker cash/fill classification and L07 notification/supervision
implementations are unchanged. Reuse their existing acceptance and PR #461's
automation/authority regressions. L09 resource/latency qualification, provider
guarantees, NAS qualification and the Stage 2 backtest remain separate.

## Harness boundary

The internal-state campaign uses the legacy full-corpus reader and its existing
252-session synthetic seed. Bind that campaign explicitly to the historical
Owned55 identity it actually supplies; it must not claim to exercise the new
current-window loader. Its accounting, command recovery and physical-storage
claims remain useful at that declared boundary. New-policy acceptance uses the
real rolling acquisition, runtime, checkpoint and paper-plan paths instead.
Do not weaken the production requirement for authenticated window features to
make a legacy harness pass.

The operator CI failure is a CRLF terminator committed on the changed import in
`research/bounded_20y/run.py`; check the entire PR diff using Linux whitespace
rules as well as the Windows worktree check.

## Results

Revalidation in progress. Existing PR #461 local evidence is retained in the
input-policy design and PR description; it is not relabeled as a new run.

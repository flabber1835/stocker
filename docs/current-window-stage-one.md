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

**LOCAL PASS for the changed policy boundary, 2026-09-30.** No additional
production defect was demonstrated. Two CI integration defects were corrected:
the legacy harness selected an input policy it did not supply, and its operator
diff contained a CRLF-only whitespace failure. No production safety guard was
relaxed. Required CI/merge and the previously open external gates remain open.

| Claim | Caller and evidence |
| --- | --- |
| L02 signals | `window_signals.feature`: 12 independently computed momentum, recent-return, sample log-volatility and score cases pass; changing older candidate history cannot change these features; raw-price eligibility remains enforced. |
| L02 funded economics | Real `rolling_runtime.advance` at $50,000: independent Decimal accounting from published raw opens/closes verifies 20 whole-share purchases, intended-dollar affordability, fees, cash, positions, Core NAV and combined Core/BIL first-open NAV. Invented cash, shares and fees are each detected. |
| L04/L08 absence | `service_advance -> rolling_recovery.advance_one -> rolling_daily.commit_next`: normal and falling-market interrupted paths equal uninterrupted state at every recovered session. Retention preserves needed dated snapshots; intermediate reconstruction cannot authorize execution. Stop exits and cooldowns have explicit expected outcomes. |
| L04 durable retry | Crashes after candidate commit and after receipt commit each recover the exact candidate without a second canonical transition or duplicate fills. |
| L06 restore | `pg_basebackup`, `pg_verifybackup`, separate PostgreSQL 17.11 instance, read-only restore validation, status restore and next-session advancement preserve the new book. Changing its archived feature binding is rejected as `DAILY_INPUT_ARCHIVE_CHANGED`. The original cluster remains unchanged. |
| L05 reuse | PR #461's actual/renamed omission, unheld revision, protected cash-event, split, uniform rebase and missing-held-witness tests remain applicable: this review changes no production source. |
| L01/L10 harness | Linux whole-PR whitespace and test-responsibility validation pass. All 126 internal-state contract cases have passing results. Four bounded composed legacy lifecycles pass, including real process death during catch-up, subsequent restart, execution, fills and reconciliation. |

Exact commands (pytest also used `-q -p no:cacheprovider --tb=short --show-capture=no`):

```text
python -m pytest tests/sentinel/test_current_window_stage_one.py
python -m pytest tests/sentinel/test_current_window_stage_one.py::test_funded_cash_oracle_and_physical_restore_continue_same_book
python -m pytest tests/internal_state
python -m pytest tests/internal_state/test_evidence.py
python tools/internal_state_harness.py --output /evidence/lifecycle --seeds 0 --scenario populated_lifecycle --scenario interrupted_multi_session_catchup
python tools/validate_test_responsibility.py --base 13bc3c987e839b6ce2d5d699bcb3b5bfd208d739 --output /evidence/test-responsibility.json
git diff --check 13bc3c987e839b6ce2d5d699bcb3b5bfd208d739 be311921
```

The new suite passed 16 cases initially; the physical restore case then passed
separately (65.62 seconds) after correcting its connection/clock handling.
Restore inspection intentionally leaves its connection read-only; advancement
uses a new writable connection, and the source cluster's retained state is read
without claiming fresh execution authority after the simulated clock advances.
The internal-state run passed 102 cases; 24 evidence-fixture setups hit the local
Docker Git-directory override. Rerunning that module without the override passed
all 43 cases, including those 24. These were harness/environment corrections.
No known failing acceptance case remains.

The four lifecycle reports bind clean commit `be311921` and both simulated
account profiles; `live_cash` is a simulator profile, not a real account.
Their scope is the declared legacy input profile. New-policy acceptance is the
17 cases above plus the retained PR #461 production tests and eight detected
guard mutations. Local execution used Python 3.12, network-disabled containers
and at most two 2-GiB test containers. This does not qualify PG16/Synology restore,
resource headroom, provider guarantees, investment performance or live trading.

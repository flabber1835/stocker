# Experiment 4 — Wealth Core symmetric deterioration exit

Status: frozen pre-run design.

Research branch only. `main` remains read-only.

Economic experiment budget before this run: **3 / 10 consumed**. This candidate consumes experiment **#4** only if its full measured economic replay completes. The fresh E3 control replay does not consume budget.

## Structural evidence

The zero-budget observational run `33917445284` found that in 2018, held securities that had already fallen outside the existing top-10% momentum pool while also having a negative existing recent-21 return accounted for 76.19% of gross negative holding P&L. The 12 episodes first detected in 2018 remained held for a median 65.5 sessions and a maximum 115 sessions after the condition was observable.

This is an admission/retention asymmetry: Wealth Core requires non-negative recent-21 performance for new admissions, but an existing holding can remain outside the admission-quality set for months until the age-119 underwater review or 30% trailing retention stop acts.

## Candidate rule

Keep all Strategy 9 Wealth Core mechanics and E3 Sentinel mechanics frozen except for one additional Wealth Core exit condition evaluated at the close:

```text
if existing trailing stop fires:
    exit as today
elif holding is outside the existing top-10% momentum pool
     AND existing recent-21 return < 0:
    schedule deterioration exit for next open
else:
    preserve the existing age-119 review logic
```

The existing 21-session cooldown after an exit remains unchanged. Replacement admission remains at most one new security per day after initialization. Position sizing remains 4% of current equity. E3 cross-surface recovery concordance remains the downstream Sentinel overlay.

## Parameter discipline

- Top 10% is the existing admission pool; no new rank threshold is introduced.
- Recent 21 sessions is the existing admission-quality horizon; no new lookback is introduced.
- Zero is a sign boundary already used by Wealth Core admission.
- Existing 30% trailing stop remains first priority.
- Existing age-119 review remains as a backstop.
- Existing 21-session cooldown remains unchanged.
- No crisis dates, market regime labels, new exposure levels, fitted constants, or additional indicators are introduced.

## Replay construction

The workflow performs two fresh chronological full-history replays against the same pinned inputs and runtime:

1. **CONTROL_E3** — the exact Experiment-3 surviving architecture.
2. **E4_SYMMETRIC_EXIT_E3** — identical E3 architecture plus the one Wealth Core deterioration exit rule above.

Each replay is independently chronological and causal. No prerecorded decisions, historical candidate outputs, or prior result tapes may drive either replay. The control is rerun solely for same-head parity and comparison and does not consume experiment budget.

## Acceptance / falsification

Experiment 4 survives only if:

1. fresh CONTROL_E3 reproduces the accepted E3 control path and metrics;
2. candidate changes are confined to the declared Wealth Core exit rule and downstream causal consequences;
3. 2018 Wealth Core drawdown and/or June-December 2018 loss materially improve;
4. 20-year and max-history drawdown do not materially worsen;
5. long-horizon CAGR and Sharpe are not materially degraded;
6. turnover does not explode into a mechanically unstable churn regime;
7. benefits are not confined to 2018 alone;
8. no result-driven threshold adjustment is made inside Experiment 4.

If the rule improves 2018 but materially damages long-run economics, it is rejected and the next investigation moves to the one-new-admission-per-day rebuilding bottleneck rather than tuning this exit threshold.

# Slot-capacity counterfactual v17

Diagnostic only. No strategy promotion is authorized.

## Question

How much of Median-5 and Caesar 20's certified path depends on the frozen rule that a slot may be opened with whatever cash remains, even when that cash funds only a small fraction of the nominal 5% entry target?

## One-factor counterfactual

At the decision close, compute the ordinary whole-share quantity from `equity * ENTRY_W`. Reserve the slot only when current book cash can fund that full whole-share quantity at the decision-close price plus the frozen side cost.

Everything else is unchanged, including next-open timing, next-open affordability clipping, ranking, Median-5 hardening, Caesar 20 ranking, 21-session cooldowns, one steady-state admission per session, review/stop rules, classifier, corpus, dividends, terminal rules, costs and Sentinel overlay.

This is not asserted to be the correct strategy. It is a preregistered counterfactual to measure the economic importance of the cash-starved-slot rule.

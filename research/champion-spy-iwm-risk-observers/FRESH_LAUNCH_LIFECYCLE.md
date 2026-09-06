# Fresh launch: retain prior security lifecycle knowledge

Status: RESEARCH / NOT CERTIFIED. Correctness refinement identified before any experiment economic result was examined.

The original 20-year experiment continues at https://github.com/flabber1835/stocker/actions/runs/34012654549 (full20 job 101431000914). Its harness and initialization are unchanged.

The fresh5 job of that initial run is superseded by the dedicated lifecycle-aware fresh5 workflow. Its result is preliminary and must not be used as the accepted independent-launch result.

## Finding

A bounded indicator warmup must still know which securities had retired before that warmup began. The original source harness builds its retired-security set by processing canonical terminal events during the replay. Starting that loop in the five-year launch's warmup year omitted earlier terminal events from this derived eligibility state. This can matter if an old security retains later bars or metadata. Its economic effect is not assumed.

## Correction

The fresh-only wrapper reads the already frozen canonical terminal ledger and initializes retired-security IDs from events effective strictly before the warmup start. Dates at or after that boundary continue through the ordinary chronological loop. This reads historical input events, not prior strategy decisions or portfolio states. No new data source or classification policy is introduced.

Portfolio initialization remains all-cash with zero holdings, pending orders, receivables and cooldowns. Controllers and raw portfolio drawdown/return history still start afresh on August 2, 2021. Price indicators retain 260 sessions of warmup. Native/Wealth Core classes are bytecode-AST equivalent to the frozen classes.

The initializer emits prewarm-lifecycle-state.json with the number and hash of input-derived retired IDs and the cutoff. Four added tests verify prior-only timing, future-event mutation invariance, deterministic event ordering, malformed-date refusal, source assembly and duplicate-install refusal. Combined observer/lifecycle suite: 31 tests passed locally; CI reruns against the actual frozen runtime.

## Reproduce the accepted independent launch

```bash
python -m unittest tests.backtester.test_research_champion_spy_iwm_observers tests.backtester.test_research_champion_spy_iwm_fresh_launch -v
python backtester/research_champion_spy_iwm_fresh_launch.py --output output/fresh5 --mode fresh5 --input-root observer-data
```

The full20 command in EXECUTION.md remains unchanged. The five-year command above supersedes its original five-year command. No 20-year rerun is required for this fresh-only initialization refinement.

# LLM Boundaries

## Allowed LLM Responsibilities

The LLM may:

```text
convert natural-language prompts into strategy YAML/JSON
explain rankings
summarize news
classify thematic exposure
suggest strategy changes
generate reports
explain trade signals
vet stocks for risk signals and positive catalysts (llm-vetter) — its
  exclusions are binding (remove tickers from the candidate pool), but it can
  only exclude; it never sizes, scores, approves, or submits orders
```

## Forbidden LLM Responsibilities

The LLM must not:

```text
submit orders
bypass risk-service
change live config without validation
invent missing data
override safety limits
directly decide position sizing without deterministic checks
directly modify approved strategy registry
apply positive-conviction score boosts or otherwise change the ranker's
  scoring/ordering (the vetter may exclude tickers — a binding hard gate — but
  the deterministic ranker still owns the final score)
```

## Correct Pattern

```text
LLM proposes
Python validates
Backtester tests
Human/system approves
Risk-service gates
Trade-executor executes
```

## Config, Not Code

The LLM should create structured strategy configs, not arbitrary Python code.

Example:

```yaml
portfolio_strategy:
  rebalance: monthly
  ranking:
    quality: 0.35
    momentum: 0.25
    value: 0.15

trading_behavior:
  rules:
    - name: trim_big_winner
      trigger:
        intraday_return_gt: 0.06
      action:
        type: trim
        percent_of_position: 0.25
```

## Provider Abstraction

The system should support API LLMs or local LLMs through `llm-gateway`.

Other services should not care which model is behind the gateway.

## LLM-Tunable Strategy File (partition + diff gate)

The strategy YAML is the surface an automated/LLM tuner is allowed to edit — but not
every field. This is enforced, not advisory.

**Partition** (`shared/stock_strategy_shared/schemas/strategy.py`, `PROTECTED_PATHS`):

```text
LLM-tunable  : factor weights, factor-engine params, universe filters (min_price,
               min_avg_dollar_volume_20d), portfolio caps, vetter scope
               (candidate_count, strictness, …), delta timings, max_positions, …
Protected    : strategy_id          (identity — forks the registry)
  (human-only) universe.source      (structural data-source switch)
               vetter.falling_knife (crash-protection thresholds — must not be loosened)
```

A protected entry guards its whole subtree (prefix match), so every threshold under
`vetter.falling_knife` is protected.

**Gate** — `strategy-validator` `POST /validate-llm-change` with
`{baseline, proposed}`. A proposal is accepted only if it (a) passes full schema +
hard-safety validation AND (b) changes ONLY tunable fields. Any change to a protected
path returns 422 with `changed_protected_fields`. This is what makes direct LLM edits
to the strategy file safe: `validate_llm_tunable_diff(baseline, proposed)` is the
deterministic check, the LLM only ever proposes.

**Hard risk gates stay outside the file.** The risk-service env limits (kill switch,
daily-loss, max-position, turnover, staleness) are never in the strategy YAML and are
unreachable from this surface by construction. The partition is the second line for
the few safety-relevant knobs that DO live in the file.

### Falling-knife thresholds migrated into the file (env = fallback)

The veto thresholds (`DRAWDOWN_BACKSTOP_PCT`, `DRAWDOWN_EXCESS_PCT`,
`DRAWDOWN_BETA_LOOKBACK`, `DRAWDOWN_VOL_SCALING/ANCHOR/MIN/MAX`, `DRAWDOWN_WINDOW_DAYS`)
are now expressible in the validated, version-tagged strategy file under
`vetter.falling_knife`. Every field is OPTIONAL: an omitted field falls back to the
service env value, so a config without the block behaves byte-identically to the
env-only setup. Both the vetter (real veto) and the pipeline (display
`excess_dd_limit`) resolve the SAME way (`_apply_falling_knife_config`, applied in
each service's `_reload_strategy`), preserving card == veto parity. They are PROTECTED
in the partition — in the file for validation/versioning, not for a tuner to loosen.

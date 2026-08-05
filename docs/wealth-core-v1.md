# Wealth Core v1 (`stocker_wealth_core_v1`)

A **stateful ownership** strategy. It is not a target-portfolio strategy with
different parameters — it is a different kind of thing, and most of the design
below follows from that one fact.

## Why it cannot run on the existing chain

The rest of Stocker is a *target-portfolio* system: rank the universe, build a
normalised target, diff the target against the broker, trade the difference. The
target is recomputed from scratch each day, which is exactly what makes the
design robust — nothing depends on remembering yesterday.

Wealth Core depends on remembering yesterday. Six pieces of state cannot be
recovered from any target:

| State | Why it cannot be re-derived |
|---|---|
| `market_sessions_held` | the one-time review fires at age 119 |
| `review_completed` | passing review once is permanent |
| `episode_peak_split_adjusted_close` | the trailing stop measures from it |
| slot cooldown | a vacated slot stays cash for 21 sessions |
| ticker cooldown | an exited name is unbuyable for 21 sessions |
| `reserved_for` | a queued entry has claimed a slot |

Run this strategy through the target-diff path and it would look plausible every
single day, and be a different strategy after the first restart. Hence a
separate execution model (`docs/architecture.md`, and
`services/scheduler/app/execution_model.py`).

## The four price domains

Named explicitly and enforced at the boundary
(`shared/stock_strategy_shared/wealth_core/prices.py`), because mixing any two
is a silent correctness failure rather than a crash.

| Domain | Used for | Sharadar column |
|---|---|---|
| split-adjusted, **dividend-unadjusted** close | signals, trailing stop | `SEP.close` |
| raw **as-traded** open | execution | derived: `open x closeunadj/close` |
| raw **as-traded** close | marking the book | `SEP.closeunadj` |
| explicit split / dividend events | share counts, cash | derived / not in SEP |

`SEP.closeadj` is a **total-return** series and is used by nothing. Feeding it to
the signal domain changes momentum on every dividend payer; feeding it to the
mark sizes every 4% admission off the wrong equity. Neither raises.

`DailyBar.from_mapping` refuses the field names `price`, `close`,
`adjusted_close`, `closeadj`, `px`, `last`, `value` and `prc` outright. A field
called `close` cannot express *which* domain it belongs to, and a contract that
relies on the caller remembering is a comment, not a contract.

### The split-adjustment basis is forward and fixed

The trailing stop compares today's close against a peak observed weeks ago, so
both must be on the same basis. Back-adjusting the window to today's price level
— what a charting package does — re-bases the series at every split, so a stored
peak from before a 2:1 sits at twice the level of the series it is compared
against and the position stops out on a corporate action that cost nobody
anything.

So `signal_close(t) = raw_close(t) x cumulative_split_factor(t)`, anchored at the
security's **first session**. A windowed load must state its prior split factor;
`build_signal_series` refuses to guess, because the wrong basis is internally
consistent and only the persisted peak is wrong.

## Fail-closed rules

Three places refuse rather than approximate. In each, every alternative produces
a *complete, plausible* run.

**Unmarkable holdings** (`marks.py`). Valuing at zero invents a total loss and,
because every admission is 4% of equity, permanently shrinks every position
opened afterwards. Carrying the last price presents a stale number as current.
Instead the holding is preserved, its last price is kept as explicitly stale, and
`resolved_equity` becomes `None` — admissions stop, because 4% of an unknown is
not a number. Exits still flow: a position whose value is unknown must always be
able to leave.

**Incomplete terminal terms** (`terminal.py`). A deal announced without economic
terms is not applied. The block comes from the missing *terms*, not from an
absent price — a contested bid trades right up to closing — so
`unresolved_terminals` outranks a live print. Zero is a *term*, not a missing
one: treating `0.0` as absent would block forever on a legitimate wipeout, and
treating `None` as `0.0` would invent one.

**Missing as-traded prices** (`wealth_core_replay.py`). Marking the book with
`SEP.close` produces a complete backtest denominated in split-adjusted currency,
where a 4:1 splitter marks at a quarter of its value and its weight is wrong by
the same factor for the rest of the run.

## Conversions

A conversion **continues** the episode — same slot, same age, same review flag —
because a takeover is not an exit, and restarting the clock would reset the
review age and the stop peak for a position the strategy never chose to leave.

Per-share accounting state divides by the exchange ratio, which preserves
**position value** exactly: at the peak the position was worth
`shares x peak_old`, and the same value over `shares x ratio` shares is
`peak_old / ratio` each. That is the quantity the stop measures. A consequence
worth knowing: a deal that genuinely delivers less value than the target's market
price *will* stop the position out, and that is correct.

Fractional entitlements **floor** and are settled in cash. `math.floor`, not
`round()` — rounding up delivers a share the acquirer never issued, and the
position is permanently one share heavier than the broker's.

## Final-session accounting

Three numbers, deliberately never one:

- **marked** — open positions at their final valid close. Not a trade.
- **liquidated** — positions the strategy actually closed during the run.
- **forced** — a *hypothetical* liquidation of what is still open.

Folding the third into the headline charges the strategy for a trade it never
made; omitting it entirely reports a book as if it were cash. It lives in its own
ledger, and finalisation writes nothing to the run ledger — a mark changes no
cash, and putting it there made the ledger depend on where the run stopped, which
broke resumption.

## Ordering conventions

The certified source fixes the **size** of the leadership set and the
**location** of the issuer check (at admission, never before the cutoff). It
fixes neither ordering, so both were decided here and are named:

| Rule | Tuple |
|---|---|
| `leadership_boundary_tie_break` | `(-momentum, security_id, ticker)` |
| `issuer_conflict_admission_tie_break` | `(-score, security_id, ticker)` |

Stable identifiers before tickers, always: a ticker is reassigned after a
delisting and changes on a rebrand, so a tie broken on ticker can order two
securities differently across two runs of the same data.

`ordering_profile` is in the config hash. If the recovered frozen prototype
orders differently, it goes in as a **named profile** beside the canonical one
and the fixture is re-pinned deliberately — a quietly edited comparator would
make every historical result silently unreproducible.

## Cross-engine parity

All three engines call the same `run_sessions`. They differ only in where
`VendorBar`s come from, so parity is tested by removing that difference: the
shared golden scenario is injected into each, and seven hashes must match.

The hashes are **ordered** so the first mismatch names the layer at fault:

    normalized_input -> candidate_audit -> decision -> order
                     -> daily_state -> daily_equity -> final_result

`normalized_input` differing means the engines read different *data*, and nothing
downstream is worth investigating. A single final hash cannot say that.

The wind tunnel's `BASELINE_REPLAY` raises rather than scoring on any mismatch: a
tunnel that has drifted from the backtester reports on a strategy nobody is
running. Its expected hashes are an *input* — a tunnel that derives its own
expectation proves only that it agrees with itself.

## Defects this design surfaced

Each was found by writing the fixture or the parity test, and each produced a
complete, plausible run beforehand.

1. **Slot reservation.** A queued entry set nothing on the slot until it filled,
   so an untradeable security collected one entry order *per session*, each
   against its own slot. Reproduced at 13 orders for one name — ~52% of the book
   in a strategy whose risk model is 4% per name.
2. **Fill-time affordability.** Sizing happens on session *t*'s close; the fill
   happens at *t+1*'s open, which gaps. The golden run finished on negative cash.
3. **Aggregated share counts.** Two conversions delivering the same acquirer put
   two episodes on one `security_id`, and `shares_by_security` was a dict
   comprehension keyed on it — one position vanished from equity, and every later
   admission was sized off the short number.

## Known reproduction differences and unsupported cases

| Item | Status |
|---|---|
| leadership boundary tie order | adopted convention, not transcribed |
| issuer conflict winner | adopted convention, not transcribed |
| dividends in the backtester | **not modelled** — SEP carries no dividend column |
| splits in the backtester | **derived** from the two price domains, not from SHARADAR/ACTIONS |
| terminal actions in the backtester | **not modelled** — no ACTIONS feed |
| `security_id` in the backtester | the **ticker**; a reused ticker reads as one continuous security |
| security-for-security where the delivered security is absent from the corpus | unsupported — the converted episode would have no closes |
| unmarkable-holding treatment | adopted 2026-08-03; the certified prototype's behaviour is unknown |

## Operating it

```bash
# replay the SEP stage so the as-traded price exists (hours)
scripts/backfill-sep-raw-close.sh

# deploy and verify, in the order verification depends on
scripts/deploy-wealth-core.sh

# the seven hashes, from inside any container that has the shared package
python -m stock_strategy_shared.wealth_core.parity_cli --engine backtester

# re-pin the golden fixture — deliberately a separate command
python -m tests.wealth_core.repin_golden
```

A change to the pinned hash is never a test failure to be papered over: it means
the strategy's output moved, and the commit has to say why.

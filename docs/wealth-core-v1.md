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

### The golden scenario does not discriminate between the volatility profiles

Measured at the 2026-08-06 re-pin, and recorded because it is easy to assume the
opposite. Running `golden_scenario()` under `simple_returns_v1` and under
`log_returns_certified_v1` produces **the same 30 entries, the same 24 final
positions, the same ledger event counts, the same blocked sessions and the same
final cash to the cent**. Only the hashes move, because the per-candidate
volatility is carried in the candidate audit.

The cause is the fixture's own construction: every security gets the same
reproducible ±2% jitter, so log compression is close to uniform across the
cross-section and cancels out of the ranking. It changes the denominator of
every durable score by nearly the same factor, and the leadership order survives
intact.

So the fixture pins the certified profile (it must — §3 of the rewrite taxonomy)
but it is **not evidence that the profiles differ**, and it would not catch a
regression that silently swapped one for the other. That evidence lives in
`tests/wealth_core/test_signals.py`, where the two are pinned separately against
hand-computed closed forms.

Giving the scenario genuine volatility dispersion would close the gap inside the
certified artefact, and it is deliberately **not** done: it changes the parity
artefact and would need a second re-pin, which would make every future re-pin
ambiguous between "the strategy changed" and "the discriminator changed". The
gap is closed **beside** it instead — see below.

### The profile-discrimination fixture

`tests/wealth_core/test_volatility_profile_discrimination.py` closes the gap
without touching the certified artefact. It holds one invariant:

> switching `log_returns_certified_v1` to `simple_returns_v1` must change at
> least one candidate ordering **and** one resulting portfolio decision.

Two securities whose formation segments have the **identical** cumulative return
(+50%), so `log1p(momentum)` cancels and volatility is the only thing that can
order them. Every gap in either path is the same size **in logs** (0.35):

| | gaps | simple vol | log vol |
|---|---|---|---|
| `SPIKE` | 3 **up** | 1.13035 | 0.94687 |
| `SLIDE` | 4 **down** | 0.95677 | 1.12326 |

A simple return is unbounded above and floored at -100%, so the same log move is
worth `e^0.35 - 1 = +41.9%` up and `1 - e^-0.35 = -29.5%` down. Simple returns
therefore see SPIKE's three gaps as larger than SLIDE's four and call SPIKE the
riskier name; log returns see all seven as identical in size, count them, and
call SLIDE riskier. **The two profiles disagree about which security is riskier
on identical price paths**, and since volatility is the denominator of the
durable score they buy different securities — SLIDE under simple, SPIKE under
certified, on ~18% margins.

Why this rung is not redundant, demonstrated rather than argued. Sabotaging
`score_universe` so it ignores `cfg.volatility_profile` entirely — a profile
accepted, hashed, and then silently dropped:

| Layer | Caught it? |
|---|---|
| hand-computed signal tests | **no** — 57 passed |
| golden fixture pin | **no** — passed |
| profile-discrimination fixture | **yes** — 4 failed |

The first two call the formula directly or run a scenario the profiles cannot
separate. Only a behaviour-level discriminator sees the plumbing.

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

## Source-lot provenance

Execution and marking use the **aggregated** security-level quantity — that is
what the broker holds and what equity must count. But aggregation destroys the
answer to "where did these shares come from?", and after a takeover that question
has no other source: it is what distinguishes one 8% holding from two 4% holdings
that collided, which changes what a human should do about it.

So `HoldingEpisode.source_lots` records every predecessor — the original
admission, then one entry per conversion, with the ratio, delivered count and
both cash legs. Both views are preserved and both are reported:

| Reader | Question it answers |
|---|---|
| `shares_by_security()` | how much do we own? |
| `lots_by_security()` | out of what? |
| `FinalReport.marked_positions` | one row per **holding** |
| `FinalReport.aggregate_by_security` | one row per **exposure** |

`tests/wealth_core/test_conversion_collision.py` is permanent. It asserts the
invariant at **five** reader surfaces — ownership, equity, risk exposure, final
reporting, provenance — because the original defect affected exactly one of them,
so a test checking equity alone would have passed while risk was still blind. It
also forbids, over the AST, `shares_by_security` being a dict comprehension keyed
on `security_id`: the fix is one line, looks obviously correct in isolation, and a
tidy-up that reverted it would be caught by nothing else — the run still
completes and only the total is wrong.

## The `wealth_core_v1` risk profile

Three inherited limits do not merely mis-tune; they mean something this strategy
does not do, and one fires where firing is worst.

| Inherited limit | What it does to Wealth Core |
|---|---|
| `MAX_POSITION_PCT` | reads a **converted** position as a breach demanding a trim — a trade this strategy does not have and must not learn |
| `MAX_DAILY_TURNOVER_PCT` | throttles trailing-stop exits during exactly the drawdown they exist for, turning a risk control into a risk |
| `MAX_POSITIONS` | counts held names and ignores slots **reserved** by queued entries, which are already committed capital |

`require_profile` **fails startup** when Wealth Core is selected without its own
profile. Inheriting ambiguous limits is worse than having none, because every
check would pass while enforcing the wrong ones and nothing would say so.

The profile refuses incoherent configuration rather than accepting it: an exit
notional cap cannot be set at all, and a concentration cap below the entry weight
is rejected because it would breach on the day of entry.

Encoded distinctions:

- The one-entry-per-session limit is a **strategy behaviour**, not a safety rail.
  It constrains entries only and never an exit, a kill-switch liquidation or a
  broker-side forced close.
- Exits are exempt from turnover **by construction**. Every sell is a stop, a
  review exit or a corporate action; there is no discretionary churn to damp.
- A **gap-reduced** entry below the 4% intent is valid. Rejecting it would make
  the strategy skip exactly the names that ran between the decision and the fill.
- A **converted** position above 4% is not a breach and not authorisation to trim.
- Exposure is computed from **aggregated** share counts, so two lots converted
  into one acquirer are one 8% exposure rather than two 4% ones.
- Pending entries count against **both** slot availability and risk reservation.

**Not yet done:** wiring this profile into `risk-service`'s `/check`. That
endpoint still applies the target-portfolio limits, which is why live activation
is blocked.

## Scheduler run trace

"Wealth Core does not require the target-portfolio stages" is a claim about
*runtime* that no source reading settles. `RunTrace` persists which chain ran, in
what order, what was bypassed, and what those bypassed services were doing at the
time — a trace taken while they all happened to be healthy proves considerably
less than one taken while two were down.

`validate()` returns problems as **data** rather than raising: a trace is
evidence, and a caller that cannot save a flawed one has no way to show what
happened on a bad day. It rejects a legacy stage being invoked, a wrong stage
order, an unrecorded bypass, and a "dry run" that submitted orders.

## Authoritative corporate actions (SHARADAR/ACTIONS)

The backtester used to derive everything it knew about corporate actions from
the price series itself. That was the right call while ACTIONS was un-ingested —
a derived ratio beats no split handling — but it cannot support a certified
claim, because it can only see events the vendor's own adjustment made visible.

### ACTIONS is the source; the derived ratio becomes a cross-check

`split_ratio_from_domains` is **not deleted**. It recovers the ratio from
`closeunadj / close`, which is the vendor's cumulative adjustment factor, and
that is an *independent* measurement of the same event. Two independent sources
that agree are worth more than one authoritative source alone, so the derived
ratio is retained and **reconciled** against ACTIONS on every bar.

On disagreement: **ACTIONS wins, and the disagreement is recorded.** Not silent
(the cross-check would be pointless), and not fatal (one inconsistent vendor
adjustment would block every backtest). The counts are returned on the run and
surfaced in the caveats, because a corpus where the two sources disagree often
is a fact about the corpus that a reader has to see.

Three reconciliation outcomes, all counted:

| | meaning |
|---|---|
| `agreed` | both sources see the same ratio |
| `actions_only` | ACTIONS has a split the price domains do not show |
| `disagreed` | both see a split, at different ratios — ACTIONS applied |

`derived_only` is deliberately **not** a separate outcome that overrides: a
ratio the price domains imply but ACTIONS does not carry is reported inside
`disagreed`, since acting on it would be exactly the un-authoritative behaviour
this work removes.

### Absent ACTIONS is a deployment state, not a data gap

The corpus has no ACTIONS rows until the stage is backfilled. Refusing outright
would break every existing backtest the moment the code lands, before anyone
could run the ingest. Falling back silently would let a run that looks certified
be scored on derived splits.

So the source is **explicit and recorded on every run** (`split_source:
actions | derived`), and `WEALTH_CORE_REQUIRE_ACTIONS` makes the fallback an
ERROR with a named remedy — the same shape as `RawPriceDomainUnavailable`. A
certified run sets it. An exploratory run does not, and gets a caveat saying
which source it actually used.

### A delisting is NOT a write-off

The single most important mapping rule, and the one where the obvious
implementation is wrong. ACTIONS carries `delisted` and `bankruptcy` rows that
frequently have no economic terms attached.

Mapping those to `WRITE_OFF` would **invent a total loss** — precisely what
`terminal.py` exists to prevent, and worse here than in the live book, because
every admission is 4% of equity so a fabricated zero permanently shrinks every
position opened afterwards. Zero is a *term*, not the absence of one.

So a terminal action without economic terms is emitted as an **incomplete**
`TerminalTerms`, which blocks: the holding stays unresolved, `resolved_equity`
goes `None`, and admissions stop until somebody supplies the terms. That is
worse to operate and the only version that cannot silently mis-state the book.
`WRITE_OFF` is reachable only from an action that actually states a zero
consideration.

| ACTIONS row | mapped to |
|---|---|
| `merger` / `acquisition` with a cash value, no contraticker | `CASH_MERGER` |
| with a contraticker and a ratio | `CONVERSION` |
| with both | `CASH_PLUS_STOCK` |
| stating a zero consideration | `WRITE_OFF` |
| `delisted` / `bankruptcy` with no terms | **incomplete — blocks** |

### What this does not yet cover

Permanent security identity is sequenced separately. The ingest stores **every**
action type including `ticker_change`, so it is a wiring change on the replay
side rather than another ingest.

## Dividends: earned on one session, received on another

The only cash event in Wealth Core with a gap between entitlement and payment.
Everything else — a buy, a sell, a cash merger — moves shares and cash in the
same instant. That gap is where the failure modes live, and all of them produce
a complete, plausible run.

### The receivable used to be decorative

`accrue_dividend`'s docstring said a receivable exists so an unsettled dividend
cannot "fund an admission on the same session it was declared". It could.
`apply_dividends` accrued into `receivables` and settled it out again **inside
one call**, at step 2 — and `decide()` runs at step 7 against `state.cash`. So
the dividend was spendable on its own ex-date. Two ledger events, zero delay.

Each receivable now carries `due_in`, a countdown of further sessions before it
becomes cash. The **list** shape matters: two dividends from the same security
can be outstanding at once with different due dates, and the old
`{security_id: amount}` dict would have merged them into one payment on one
date.

### The lag is an adopted convention, because the pay date is unobservable

SHARADAR/ACTIONS carries `date / action / ticker / name / value / contraticker /
contraname` and nothing else. The **payment** date is genuinely unavailable, not
merely unmapped, so `dividend_settlement_lag_sessions` is a named convention in
the config hash rather than a per-dividend fact.

The default is **1**, and the rationale is deliberately narrow: it is the
smallest lag that enforces what the receivable is *for*. Anything larger would
be modelling a payment calendar we cannot observe — a real US ex-to-pay gap is
nearer 10–20 sessions, and a deployment wanting that must ask by name. **0
reproduces the pre-lag behaviour exactly**, which is what makes the golden hash
movement attributable to this change rather than entangled with everything else.

### Entitlement is read before this session's fills

Dividends are step 2; pending orders fill at step 4. A position bought at this
session's open did not own the shares when the security went ex; a position sold
at this open did. Reading the share count after the fills gets both backwards,
and the resulting payment is internally consistent — so nothing catches it.

### The amount is fixed in dollars on the ex-date

Which is what makes a later split irrelevant to an outstanding receivable.
Recomputing at settlement from the then-current share count would **double** the
payment across a 2:1 — a bug that looks like a dividend and reconciles
perfectly.

### A receivable is paid whether or not the position survives

It is a claim on cash, not on the holding. A dividend earned before a delisting
or a cash merger is still owed, and cancelling it because the position has left
would lose real money with no event saying where it went.

### `ledger_hash` now covers receivables, not just events

It hashed the event log alone, which left money the book is owed outside every
hash. The consequence was concrete: a restart that dropped an unsettled
receivable produced an **identical** ledger hash at the boundary and diverged
only later, when the payment silently failed to appear. A hash that cannot see a
difference until its downstream consequence shows up is worth much less than one
that sees it at once — the same argument as the seven ordered parity hashes.

`RunResult` also reports `outstanding_receivables` as its own number. A run that
stops between ex and pay is owed money, and reporting cash alone understates it
silently: an accrual has no cash delta, so the ledger reconciles perfectly
either way.

### Not derived from the total-return series, ever

The book is marked on dividend-**unadjusted** prices, which is why an explicit
ledger event is needed at all. Deriving the distribution from the vendor's
total-return close would count it twice — once inside the price and once in the
ledger. `DailyBar.from_mapping` refuses the ambiguous field names outright, and
a test asserts the replay module never names that column even in a string, since
its SQL queries are string constants too.

## Permanent security identity

**A ticker is an observation label. The permanent security identity owns the
economic state.** Everything path-dependent hangs off `security_id`, so what
that field means decides whether a rename is a no-op or a liquidation.

The backtester used the TICKER as `security_id`, which gets it wrong in both
directions and silently:

| | what the ticker does | what it should do |
|---|---|---|
| rename (`FB` → `META`) | old id stops printing, new id appears — an exit and a fresh entry, with costs, a reset peak, a reset age and a reset review | nothing at all |
| reuse (a ticker reassigned years later) | two unrelated companies splice into one continuous security | two separate histories |

Neither raises. The first sells a winner on a press release; the second computes
momentum across a discontinuity between different businesses.

### What follows the permanent identity

Position quantity and basis, the episode peak and stop state, entry date and the
one-time review flag, the **security** cooldown, outstanding dividend
receivables, pending entries and exits, terminal history, and issuer
concentration. A `ticker_change` alters the tradeable symbol and nothing else.

The cooldown moved with it, and that is a behaviour change rather than a
refactor: `ticker_cooldowns` was keyed on the SYMBOL, so a security that exited
and then renamed became immediately re-buyable — the cooldown looked up a
ticker that no longer existed. It is now `security_cooldowns`, keyed on the
permanent id, because "this security is unbuyable for 21 sessions" is a
statement about the company, not about the string it trades under.

### Resolution is point-in-time, and refuses rather than guesses

`bt_universe` is keyed on `(snapshot_date, ticker)` and carries `permaticker`
plus the `first_price_date` / `last_price_date` window. Meta is therefore built
per **permaticker**, and a `(ticker, session)` pair resolves to whichever
permanent security actually held that symbol on that session.

Three refusals, all counted and reported rather than silently dropped:

- **no permaticker** — identity cannot be established, so the security is
  excluded. Same rule as strict issuer identity: a guess merges companies.
- **ambiguous** — two permanent securities claim one ticker on one session with
  overlapping windows. That is a data defect, and picking either one produces a
  complete run of a security that did not exist.
- **out of window** — a bar whose ticker resolves to no security on that
  session.

`security_id` is `P:<permaticker>`, prefixed so it can never be mistaken for a
ticker by a reader or by a test fixture.

### The certified artefact does not exercise identity either

The same shape as the volatility-profile gap, recorded for the same reason.
Across all 260 sessions the golden scenario produces **zero** relabellings and
has **125 distinct tickers for 125 securities** — no rename, no reuse. So it
pins identity *handling* only in the sense that the ids happen to be stable; it
would not catch a regression that reverted to ticker-as-identity.

That evidence lives in `tests/wealth_core/test_identity.py`, which is falsified
rather than assumed: reverting the cooldown key to the symbol and removing the
relabelling step fails **10** of its 21 tests. Giving the scenario a rename and a
reused ticker would close the gap inside the artefact and needs its own
deliberate re-pin — it belongs with the next scenario revision, alongside the
volatility dispersion.

## Known reproduction differences and unsupported cases

| Item | Status |
|---|---|
| leadership boundary tie order | adopted convention, not transcribed |
| issuer conflict winner | adopted convention, not transcribed |
| dividends in the backtester | **applied** from ACTIONS on the ex-date as a receivable, settling after `dividend_settlement_lag_sessions` |
| dividend PAYMENT dates | **unobservable** — ACTIONS carries no pay date, so the lag is an adopted convention in the config hash |
| splits in the backtester | **authoritative** from SHARADAR/ACTIONS, reconciled against the derived ratio; **derived** only when `bt_actions` is empty |
| terminal actions in the backtester | **modelled** from ACTIONS — cash merger, conversion and write-off, with terms-less events BLOCKING |
| mixed consideration in the backtester | **unsupported** — one `value` column per ACTIONS row, so a cash-plus-stock deal is modelled as the leg the vendor stated |
| a conversion's fractional stub in the backtester | **blocks** — ACTIONS carries no cash-in-lieu price |
| `security_id` in the backtester | the **ticker**; a reused ticker reads as one continuous security |
| security-for-security where the delivered security is absent from the corpus | unsupported — the converted episode would have no closes |
| unmarkable-holding treatment | adopted 2026-08-03; the certified prototype's behaviour is unknown |
| `risk-service` enforcement of `wealth_core_v1` | **not wired** — `/check` still applies the target-portfolio limits |
| deployed-image parity | **not yet run** — needs the NAS |
| SEP `close_unadjusted` | **not yet populated** — needs the replay |

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

## What "certified" would require

The two ordering rules are **adopted deterministic conventions**, not
transcriptions. Passing the test suite establishes internal consistency and
cross-engine agreement; it does not establish reproduction of the frozen
implementation. Exact certified reproduction may be claimed only once **all** of
these match the recovered control:

- normalized historical inputs
- ordering profile
- candidate audit
- entries and exits
- corporate-action treatment
- daily equity
- certified artifact hashes

If the frozen implementation establishes different ordering, add a **named
compatibility profile** and re-pin deliberately. The present production profile
(`canonical_2026_08`) is preserved rather than silently changed.

## Rollback

The strategy is inert until a config selects it, so rollback is a config change
rather than a code revert:

```bash
# 1. stop routing to Wealth Core — remove or change the top-level field
#    execution_model: stateful_ownership   ->   target_portfolio
#    The scheduler then runs the legacy chain unchanged.

# 2. if a full code rollback is wanted
git revert --no-commit 998a5d4 117d7ae 7966afc dc68f44 ce1c7fe 9f350a6 ca252c8
git commit -m "revert Wealth Core"

# 3. redeploy
scripts/deploy-all.sh
```

`bt_prices.close_unadjusted` needs no rollback: it is an added column that
nothing else reads, and the price corpus was rewritten in place by UPSERT with no
other column touched. **Never** pass `--volumes` to any `docker compose down` —
it deletes the trading database and the 35M-row corpus.

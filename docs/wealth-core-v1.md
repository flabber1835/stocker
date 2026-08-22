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
| security cooldown | an exited SECURITY is unbuyable for 21 sessions — keyed on the permanent id, never the symbol |
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

## Session-effective issuer-family changes

Issuer-family metadata is rebound at the start of the observed session, before
pending fills. The one-position-per-issuer admission invariant is then checked
again against the rebound state; the signal-session reservation is not authority
to violate the fill-session family.

- A pending entry that now conflicts with a held issuer is cancelled before
  fill and its slot reservation is released.
- If several pending entries converge on one issuer, the already-existing
  reservation wins: earlier `signal_session`, then lower `slot_id`, then
  permanent `security_id`. Every later reservation is cancelled. This is
  temporal commitment priority, not a new score or discretionary winner.
- A metadata change that maps two distinct already-held securities to one issuer
  is a fail-closed `IssuerFamilyCollision`. Wealth Core has no discretionary
  trim/unwind rule, so choosing a survivor would invent strategy behavior.
- Corporate-action conversions are the documented exception: when complete
  same-session conversion terms prove that every colliding source holding maps
  to the same delivered permanent security, the terminal waterfall runs and
  the resulting lots remain held and aggregate exactly as described above.
  Already-converted lots of that same delivered security are valid too. These
  are not new admissions. Missing, incomplete, mixed-target, or future terms do
  not waive the held-collision refusal.
- The exception is provisional until the terminal waterfall has actually
  applied the identity changes. Immediately after conversions, Wealth Core
  re-runs both sides of the invariant against the resulting state: distinct
  held securities may not share an issuer, and pending admissions may not
  conflict with any resulting holding or earlier reservation. Multiple source
  lots that deterministically became the same delivered permanent security are
  the evidenced consolidation above; any other new held collision raises the
  structured fail-closed refusal before fills or decisions.

The cancellation record includes the old/new issuer, conflicting slot/security,
reservation release, and the issuer-rebind transformation. The complete record
is part of the `order` hash. The held-collision exception carries a sorted,
structured evidence payload and aborts before fills or decisions.

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

### Wired into `/check` (2026-08-06)

`execution_model: stateful_ownership` dispatches to the profile AFTER the
universal gates and BEFORE every target-portfolio limit. The universal gates —
kill switch, live/paper, finite and positive qty — still apply: they are
validity and emergency controls, not strategy limits, and "exits are exempt"
must never become an exemption from the emergency brake.

**The profile is verified by HASH, not by name.** `profile_hash()` digests every
limit, so a deploy that loosened `maximum_positions` without renaming anything
still presents `wealth_core_v1` — a name check accepts it and the two sides then
enforce different limits with nothing saying so. Missing, unknown and mismatched
are all REFUSED; none falls back to the default risk behaviour. `/health`
publishes the name and hash so a deploy can verify what is live without
submitting a trade.

**The stateful context is SUPPLIED, never reconstructed.** Held positions, slot
reservations and the per-session admission count are path-dependent. A risk
service that re-derived them from a target would invent the state it is meant to
check and agree with itself perfectly. A buy-side check with no context is
refused — a default of zero-held, zero-reserved approves every entry.

Consequently the Wealth Core path reads **no database at all**, which is
asserted against an engine whose every connection raises rather than against
`engine=None` (the latter is the service's degraded mode, where the controls are
skipped — a pass there would be consistent with having tried and given up).

`security_id` is required: a decision keyed on the ticker can be attributed to
the wrong company after a rename or a reuse, and `risk_decisions` is the audit
trail answering "which rule approved this trade?".

The falsifier is a comparison rather than a mock: the identical order judged
under both models, with the same broken database, gets opposite answers — the
inherited path fails closed needing data it cannot reach, the profile approves
without any I/O. The two models disagree not about a threshold but about what
has to be known before an answer exists.

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

### Source-row grain and rebuild authority

The backtest corpus stores ACTIONS at the complete seven-field Sharadar source
grain: `date`, `action`, `ticker`, `name`, `value`, `contraticker`, and
`contraname`. Its durable key is a SHA-256 over the canonical complete row,
with semantic numeric spelling and a distinction between NULL and the empty
string. `(ticker,date,action)` is an economic grouping key only; it is not and
must never again become a storage uniqueness key.

An existing table created under the coarse key is unprovable because rows were
already discarded before storage. Schema migration therefore invalidates its
ACTIONS authority and requires a complete `1900-01-01..through` rebuild. The
replacement is one database transaction inside the corpus PUBLISHING
generation: delete the covered source window, insert every distinct complete
row, verify persisted cardinality, and mark ACTIONS READY together. A failure
rolls the replacement back and leaves the corpus generation unreadable.

Exact semantic redeliveries collapse by `source_row_id`; distinct siblings
coexist. Readers order by that identity. Dividends sum every distinct usable
source row deterministically. `split` and `adrratiosplit` do not coexist as two
candidate share multipliers: Sharadar documents the first as a stock split and
the second as an ADR ratio change. Wealth Core consumes only the `split`
new-float/old-float multiplier and retains the ADR row as provenance. Distinct
`split` values at one effective key remain unresolved ambiguity, never
first-row, last-row, reciprocal, or product semantics. Terminal rows continue
through the shared deterministic coalescer, using source identity as provenance
and refusing equally rich conflicting economics.

The price-domain cross-check is exact about source precision. The ordinary
one-percent relative agreement rule remains, but a stated value can also be
corroborated when it lies inside the ratio interval obtained by propagating a
half-mill rounding interval through all four SEP prices. One-session date
shifts and two-session adjustment bridges are accepted only in the narrowly
documented shapes: the immediately prior transition must corroborate the
action, or the prior-through-action net transition must corroborate while the
intermediate event is suppressed. Canonical replay and production use the same
state machine.

A corroborated five-decimal reverse ratio is represented as exact ``1/N`` only
when that simple rational lies inside the same strict agreement band. This
prevents 300 shares in a documented 1-for-30 from becoming 9.999 solely because
the source spelled the multiplier as ``0.03333``.

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
| target-side acquisition / merger / delisting | incomplete `CASH_MERGER` economics |
| public or private acquiring counterparty | provenance only; never delivered consideration |
| any `value`, including zero | aggregate deal-size provenance only |

No ACTIONS terminal row can produce exact cash, stock, mixed, or zero
consideration. The mapping intentionally chooses one incomplete terminal shape
so the settlement waterfall can carry and resolve the known termination without
inventing holder terms.

### The identity boundary an audit found (2026-08-06)

`load_meta` moved to permanent ids in item 7; the terminal-action call site did
not. The replay filtered ACTIONS with `known_tickers=set(meta)` — comparing
`"OLD"` against `{"P:123"}` — so **every terminal action was dropped before
reaching the engine.** No cash merger paid, no write-off applied, no terms-less
delisting blocking anything, and the run completed normally reporting an empty
`terminal_results`. A second defect sat behind it: `TerminalTerms` carried the
TICKER as `security_id`, which matches no episode, and fabricated
`delivered_issuer_id` as `"P:" + contraticker` — a ticker wearing the
permanent-id namespace's prefix, naming nothing.

The source ticker is now resolved point-in-time before filtering. An
unresolvable SOURCE is dropped and counted (applying a terminal event to a
security nobody can name is worse than missing one). `contraticker` is not
resolved as a delivered security: it identifies a buyer and supplies no holder
consideration. Buyer ticker/name remain in provenance while
`delivered_security_id` and exchange terms remain unset.

**Why the unit tests missed it.** They call `terminal_events_from_actions` with a
TICKER-keyed universe — a coherent contract in isolation and the wrong one at the
boundary. The tests added for this always cross it: a holding keyed `P:123`, an
ACTIONS row saying `OLD`, a resolver between them, and an assertion that the
position is actually terminated and the cash actually arrives.

### The hashes were interpreter-dependent

`json.dumps(..., default=...)` rounded floats in `default` — a hook the encoder
never calls for a float, because it handles floats natively. The rounding was
dead code, and ~42,000 candidate metrics were hashed through `repr`. Reported on
Python 3.13: state hash, ledger hash, final cash, positions, event counts and
blocked sessions ALL matched while `result_hash` differed — an
audit-serialisation difference, not a changed portfolio path.

`hashes.quantize()` now rounds recursively before serialisation, applied to all
four certification hashes (result, decision, state, ledger) rather than only the
one that was observed to differ.

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

That evidence lives in two files, both falsified rather than assumed.
`test_identity.py` pins each rule in isolation — reverting the cooldown key to
the symbol and removing the relabelling step fails **10** of its 21 tests.
`test_identity_discriminator.py` runs the rules in SEQUENCE, which is where the
interesting failure lives.

### One wrong key, two opposite wrong answers

The cooldown is written ONCE, when the exit fills. Keyed on the symbol it lands
on whatever the security was trading as at that moment, and that single wrong
key produces both failures — which is why one path can catch both:

| | what a symbol-keyed cooldown does |
|---|---|
| false **unblock** | SEC_A exits as `OLD`, renames to `NEW`, and a lookup under `NEW` finds nothing. Re-buyable inside its own protection window. |
| false **block** | SEC_B later picks up the vacated `OLD` and inherits a **stranger's** cooldown. A company never held is refused for 21 sessions, and the audit says only "cooldown". |

Only the first was fixed and pinned in item 7. The second was never pinned at
all, and nothing else in the suite notices it.

**Ordering in that fixture is load-bearing, and the first version got it wrong.**
It renamed SEC_A while the exit was still in flight, so the exit filled under
`NEW` and a symbol-keyed cooldown landed on a key SEC_B never touches — the
false-block test passed under a deliberately sabotaged engine, because the path
never reached the case it was written for. The exit must fill while the security
is still `OLD`. That constraint is incompatible with relabelling a queued order
mid-flight (which needs the rename BEFORE the fill), so the two live in separate
scenarios rather than being forced into one, and a guard test asserts the fill
really did precede the rename. Sabotaged, the corrected fixture fails 5 of 11. Giving the scenario a rename and a
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
| splits in the backtester | ACTIONS presence is required for certified provenance; only `split` is share authority, its direct multiplier is checked against finite-precision price evidence and narrow date bridges, and unresolved conflicts are not applied; **derived** only when `bt_actions` is empty |
| terminal actions in the backtester | **detected** from ACTIONS; holder consideration is unavailable, so source rows enter the incomplete-terms settlement waterfall |
| mixed consideration in the backtester | **unsupported and never inferred** — ACTIONS identifies buyers and aggregate deal value, not holder cash/share legs |
| a conversion's fractional stub in the backtester | **blocks** — ACTIONS carries no cash-in-lieu price |
| `security_id` in the backtester | the **ticker**; a reused ticker reads as one continuous security |
| security-for-security where the delivered security is absent from the corpus | unsupported — the converted episode would have no closes |
| unmarkable-holding treatment | adopted 2026-08-03; the certified prototype's behaviour is unknown |
| `risk-service` enforcement of `wealth_core_v1` | **wired** — `execution_model: stateful_ownership` dispatches to the profile, verified by hash |
| deployed-image parity | **not yet run** — needs the NAS |
| SEP `close_unadjusted` | **not yet populated** — needs the replay |

## Operating it

```bash
# replay the SEP stage so the as-traded price exists (hours)
scripts/backfill-sep-raw-close.sh

# build, push, then verify the current Sentinel/certification graph
# (exact registry and baseline arguments are in nas-deployment-remediation.md)
scripts/sentinel-certify.sh --start YYYY-MM-DD --end YYYY-MM-DD --build-only

# start the exact frozen rehearsal image, without rebuilding it
scripts/bt-engine-up.sh --no-build --start YYYY-MM-DD --end YYYY-MM-DD

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

## Running an experiment (bt-engine, `POST /wealth-core/jobs/run`)

Three modes on one endpoint, all against the Sharadar corpus in bt-postgres and
all read-only — nothing is submitted and no broker is contacted.

```bash
# 1. rehearse the LIVE chain, session by session, with every order risk-gated
curl -sX POST localhost:8031/wealth-core/jobs/run -H 'content-type: application/json' -d '{
  "mode": "chain_rehearsal",
  "start_date": "2015-01-01", "end_date": "2024-12-31",
  "starting_cash": 1000000
}'

# 2. reproduce one exact backtester artifact and its BT data generation
curl -sX POST localhost:8031/wealth-core/jobs/run -H 'content-type: application/json' -d '{
  "mode": "baseline_replay",
  "start_date": "2015-01-01", "end_date": "2024-12-31",
  "expected_hashes": {"normalized_input": "...", "...": "..."},
  "expected_data_version": "<artifact corpus.version>"
}'

# 3. score a variant against a recorded parent
curl -sX POST localhost:8031/wealth-core/jobs/run -H 'content-type: application/json' -d '{
  "mode": "experiment",
  "start_date": "2015-01-01", "end_date": "2024-12-31",
  "config": {"n_slots": 20}, "change": {"n_slots": 20, "note": "fewer, larger"},
  "baseline_hashes": {"normalized_input": "...", "...": "..."}
}'

curl -s localhost:8031/wealth-core/runs/latest
```

Runs are serialised against each other AND against a sweep — each loads the
whole corpus for its range, and two at once is the memory profile that gets the
container OOM-killed, which would be recorded as a strategy failure.
For `baseline_replay`, `expected_hashes` and `expected_data_version` must come
from the same retained producer artifact. After acquiring the shared corpus
lock in a read-only repeatable-read snapshot, bt-engine compares the current
READY generation to that exact version before it invokes any corpus loader; a
mismatch refuses instead of turning a vendor-data change into an apparent
engine divergence.

The baseline is intentionally not configurable. It accepts only the canonical
producer inputs: `starting_cash=1000000`, empty `config`, and empty
`eligibility`. Those empty diffs instantiate the canonical strategy,
eligibility, and certified volatility-profile defaults in both images. A
non-default cash base or any strategy/eligibility override is an `experiment`
and is refused as a baseline before the corpus is read.

The loader reaches back 400 calendar days only to locate the final 126 trading
sessions needed for feature warm-up plus their immediately preceding trading
session. That prior session is the exclusive ACTION cutoff: rows dated on or
before it are discarded before mapping splits or dividends. Rows dated after
it are preserved, including weekend or holiday ex-dates that correctly map to
the first retained trading session. If the prior session is unavailable the
run refuses; using the first retained date as the cutoff would incorrectly drop
those valid non-session events.

Terminal rows have a second boundary: inclusion in the measured window is based
on the row's mapped effective trading session, not its raw calendar date. The
mapping uses the complete retained warm-up plus measured calendar first. This
keeps a Sunday or exchange-holiday action that becomes effective on the first
measured session, and excludes actions whose effective sessions remain in
warm-up or fall outside the measured range. The expected-hash producer and
bt-engine baseline call the same canonical helper.

**Read the result in this order.** `provenance.split_source` first: `derived`
means `bt_actions` is empty and the run is NOT certified-reproducible (remedy:
`POST /jobs/backfill-actions` on bt-data; `WEALTH_CORE_REQUIRE_ACTIONS` turns it
into a refusal). Then `equivalence` on a rehearsal — a divergence is RAISED, so a
`success` row means the live path reproduced the bulk replay. Then
`rejected_intents`, which is what a rehearsal exists to surface: an order the
risk layer would refuse, seen before it happens live rather than after. Then
`divergence.first_divergence` on an experiment — `normalized_input` means the
DATA moved, not the strategy, and the comparison is confounded.

A rehearsal reports one row per trading day; over 400 sessions the per-session
detail is elided from the stored summary and the counts and verdict remain.

## Certification

Wealth Core is **NO-GO** for live activation. `execution_model` stays
`target_portfolio` in production until the authoritative-data evidence runs pass
on the NAS. The manifest — proven layers, pending layers, the required run
sequence, and the pre-existing failing suites that any evidence statement must
name rather than round up — is **docs/wealth-core-certification.md**.

# Wealth Core: the 31-test rewrite (open)

State at `2bfbe90`: **276 passed, 31 failed**, deliberately. All six audit items
are fixed in code. The red suite is doing its job — it is showing which
expectations still encode the superseded specification.

**The goal is not to make 31 tests green.** A test patched until it passes
records whatever the code now does, which is worth nothing the next time the
code is wrong. Each one is rewritten into one of three categories.

## 1. Profile-invariant

Must pass under **both** volatility profiles. Parametrise over
`VOLATILITY_PROFILES` rather than picking one:

- ordering and tie-breaks
- state transitions, slot and ticker cooldowns, reservations
- execution timing (decide at close t, fill at open t+1)
- accounting: cash, fills, affordability, ledger

If one of these depends on the profile, that is a finding, not a fixture to
adjust.

## 2. Profile-specific

Candidate scores, rankings and selected securities need **explicit expected
values per profile** — `simple_returns_v1` and `log_returns_certified_v1`
separately. Never a single expectation with a profile-shaped tolerance; that
hides the divergence the profiles exist to make visible.

## 3. Certified golden

The golden fixture and the Sharadar parity target use
`log_returns_certified_v1` **only**. `simple_returns_v1` is retained as
selectable and separately tested, and must never be the basis of a certified
artefact.

## Scenario drift — the trap

For every test whose expected security changed: **do not just replace the
ticker.** Establish why the new winner ranks first under the certified formula
— its momentum, its formation volatility, its durable score relative to the
name it displaced. Log returns compress large moves, so a volatile name gets a
smaller denominator and a higher score; a rewrite that does not show this is a
snapshot of accidental behaviour wearing a test's clothes.

## The two superseded tests

`test_it_matches_a_hand_computed_sample_stdev`
→ split into two hand-computed tests, one per profile. The arithmetic must be
worked by hand in the test, not read back from the implementation.

`test_review_fires_only_at_exactly_119`
→ three cases:
  - age 119, valid evidence → **evaluate**
  - age 119, no valid close → **defer** (`HOLD_REVIEW_DEFERRED`, flag NOT set)
  - next valid session → the still-pending one-time review **fires**

That third case is the one the old `==` rule made unreachable.

## Sequence after the rewrite

1. all Wealth Core tests green
2. **one** deliberate golden re-pin
3. cross-engine parity
4. authoritative ACTIONS, dividends, permanent security IDs
5. exact Sharadar control comparison

No-go stands until 5 completes.

## Not in scope, and not yet specified

The **shadow book → 30% position stop → 15.5% portfolio trigger → T-bill sleeve
→ shadow-controlled recovery** overlay is new architecture, absent from the
§1–§12 spec this engine was built to. It follows certification; it is not a
missing piece of it. `engine.py` explicitly excludes a portfolio-wide stop
today, and that exclusion is deliberate rather than an oversight.

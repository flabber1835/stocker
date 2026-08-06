# Wealth Core: the 31-test rewrite (DONE 2026-08-06)

**Outcome: 347 passed, 0 failed**, golden re-pinned once. Steps 1 and 2 of the
sequence below are complete; 3-5 remain and the no-go still stands.

Two of the 31 were not stale expectations at all. They were the red suite
pointing at live defects, and both are fixed in code:

* `RunResult.terminal_results` was never populated after corporate actions moved
  into `step_session`. The ledger still recorded every event, so nothing looked
  wrong — but the field is in `result_hash()`, so the parity hash had silently
  stopped covering corporate-action outcomes.
* the restart mutation controls compared a tail run's hashes against the whole
  run's. Those cover different session ranges, so `normalized_input` always
  differed and `first_divergence(...) is not None` was true for every
  corruption whether or not it did anything. The controls could not fail.

Correcting the second exposed a third thing: two of the six corruptions do not
move the terminal state, and asserting that they did was relying on other
defects. Dropping the slot reservations is absorbed by the fill-time
affordability rule; dropping the review flags is absorbed by a re-review that
passes and re-sets them, which only worked before because `review_due` was `==`.
Both diverge at `decision`, and each control now pins the layer.

Original state at `2bfbe90`: **276 passed, 31 failed**, deliberately. All six
audit items were fixed in code. The red suite was doing its job — it was showing
which expectations still encoded the superseded specification.

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

## Scenario drift — what it turned out to be

The security whose entry straddles the S170 restart boundary was `SEC_F094`, on
the reasoning that by S166 every *named* security is held. The
initial-construction fix invalidated that: the opening now fills all 25 slots at
S126/S127, so F094 is bought in the opening and the untradeable window landed on
a name nobody was buying.

The replacement is `SEC_BUST`, and the reason is mechanical rather than
incidental. Its base price of $25 against ~450k shares puts daily dollar volume
at ~$11M — **below the $20M ADV20 floor** — so at S126 it is ineligible and
absent from the leadership population entirely, which is why the opening never
considers it. By S166 its drift has carried the price past $45, ADV20 clears,
and it enters the leadership set through the room `SEC_STOPOUT` left when its
-40% crash collapsed its momentum. At S166 it scores 1.3810, behind only
`SEC_MERGED` (1.4238), `SEC_STRANDED` (1.4139) and `SEC_SPLITTER` (1.4053) —
all three already held — so it is the highest-ranked unheld candidate and the
slot is its.

BUST therefore carries two conditions, which is forced rather than untidy: a
dedicated security for the straddle would have to outrank it at S166, pushing
BUST to the next vacancy around S188 and leaving it unheld when its write-off is
due at S185 — retiring that condition silently.

## What the re-pin moved, and what it did not

| | old pin (`998a5d4`) | new pin |
|---|---|---|
| final cash | 33,848.44 | 34,824.20 |
| final positions | 24 | 24 |
| ledger event counts | identical | identical |
| blocked sessions | identical (19) | identical (19) |

Of the +975.76, **+973.78 is the four audit fixes** already committed in
`e9f6d26`/`2bfbe90` (the pin predates them), and **+1.98 is the scenario
change** — BUST's fill moving from S167 to S176 at a different open, taking 539
shares instead of 544.

The volatility profile contributes **nothing** to this scenario: see
docs/wealth-core-v1.md, "the golden scenario does not discriminate between the
volatility profiles". That is a known coverage gap in the fixture, not a
property of the strategy, and closing it needs a second re-pin.

## The four rungs of profile assurance

Each catches something the others cannot. The third was added on 2026-08-06
after the re-pin showed the certified artefact could not discriminate.

| Test | What it proves |
|---|---|
| hand-computed signal tests | each formula is mathematically correct |
| **profile-discrimination fixture** | **switching profiles changes behaviour where it should** |
| golden fixture | certified end-to-end behaviour stays frozen |
| cross-engine parity | all engines reproduce that certified behaviour |

Demonstrated, not assumed: sabotaging `score_universe` to ignore
`cfg.volatility_profile` is caught **only** by the discriminator (4 failed) —
the signal tests (57 passed) and the golden pin (passed) are both blind to it.

## Sequence after the rewrite

1. ~~all Wealth Core tests green~~ — **done**, 347 passed
2. ~~**one** deliberate golden re-pin~~ — **done**, `6fd382cf1d33…`
3. ~~cross-engine parity~~ — **done**, 45 passed, all seven hashes agree
4. ~~profile-discrimination fixture~~ — **done**, 29 tests, artefact untouched
5. ~~integrate authoritative ACTIONS~~ — **done**, ingest + replay wiring
6. ~~apply dividends~~ — **done**, with a settlement lag; golden pin left RED on purpose
7. permanent security / issuer identifiers in place of the ticker
8. revise and re-pin the certified artefact **once** for those data semantics
9. exact Sharadar control comparison
10. enforce `wealth_core_v1` in the live risk service
11. repeat cross-engine parity and restart falsification over the
    authoritative-data path
12. verify the SEP backfill directly on the NAS

No-go stands until 9 completes. Live activation additionally blocked on 10.

**The golden pin is deliberately RED at this commit.** Dividends moved the
strategy's output and permanent identifiers will move it again, so the two are
held for ONE controlled re-pin (item 8) rather than two — which is what keeps a
re-pin explainable. Everything else is green: 397 wealth_core, 45 parity, 140
backtester, 151 bt_data, 781 shared.

**ACTIONS is ingested but not yet BACKFILLED.** The code path is inert until
`POST /jobs/backfill-actions` has run on bt-data: `bt_actions` empty means the
replay falls back to derived splits and reports `split_source: derived` plus a
caveat saying the run is not certified-reproducible. Setting
`WEALTH_CORE_REQUIRE_ACTIONS` turns that fallback into an error, and a certified
run must set it.

## Not in scope, and not yet specified

The **shadow book → 30% position stop → 15.5% portfolio trigger → T-bill sleeve
→ shadow-controlled recovery** overlay is new architecture, absent from the
§1–§12 spec this engine was built to. It follows certification; it is not a
missing piece of it. `engine.py` explicitly excludes a portfolio-wide stop
today, and that exclusion is deliberate rather than an oversight.

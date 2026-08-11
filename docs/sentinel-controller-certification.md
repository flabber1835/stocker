# Certifying the Sentinel controller — what is proven, and what step 2 blocks on

> **Status after `23f268b`: the RECOVERY OVERLAY is certified exactly. The
> SEVERE PATH is implemented and NOT certified.** Step 2 was to close that gap
> by sourcing SPY and recomputing the fast path from raw inputs. Three findings
> below say the stated acceptance criterion targets the wrong artefact, and one
> of them is a hard environmental blocker.

---

## 1. What `23f268b` proves

```text
frozen rule        LOADED from FROZEN_SENTINEL_1P1_RULE.json, SHA256 verified
                   against the handoff's own SHA256SUMS.txt at import
recovery ramp      all 5,032 sessions of the frozen oracle, exactly, including
                   4413 / 386 / 150 / 83 and every transition date
fragility gate     all seven rows of 02_recovery_gate_flags.csv to 1e-12
healthy triple     matches the tape's own `healthy` column on every session
plateau claim      VERIFIED, not quoted: <= 0.0 and <= +0.01 both reproduce the
                   tape exactly, while 9 confirmations move 125 sessions, a
                   4-session horizon 125, and a 0.50 first step 150
```

The severe signal was supplied from the tape's `canonical_alloc`. That isolates
Sentinel 1.1's own contribution and certifies it exactly; it certifies nothing
about the trigger.

---

## 2. Finding A — the two artefacts use different TIME BASES

`sentinel_1p1_daily.csv` (the corrected reference implementation) and
`sentinel_1p1_exact_daily_with_breadth.csv` (the frozen oracle) disagree on 34
sessions of the parent allocation. Shifting one series by a single session drops
that to 20:

```text
same-day alignment    34 mismatches
one-session shift     20 mismatches
```

So `oracle.canonical_alloc[D] == reference.parent_allocation[D-1]`. The oracle
column is **effective-basis** (what was held on D); the reference column is
**decision-basis** (what was decided at D's close, effective at D+1's open).
Both are correct; they are answering different questions.

This is benign for §1's certification, which reads the oracle's own columns
consistently throughout. It is **not** benign for step 2: a fast path
recomputed from raw inputs produces a DECISION series, and comparing it directly
against `canonical_alloc` would show 34 spurious failures — every severe entry
and exit, twice per episode.

---

## 3. Finding B — the residual is one real episode, and it is a SHADOW difference

After the shift, the entire remaining disagreement is a single contiguous run:

```text
2025-04-08 .. 2025-05-06     20 sessions
corrected reference          0.0   (severe)
frozen oracle                1.0   (invested)
```

Twenty sessions, which is exactly `406 - 386`. The reference fires a severe
episode in April 2025 that the frozen oracle does not.

This is not a rule difference. The two artefacts are different RUNS on different
shadows:

```text
                      CAGR          max DD         ending multiple
frozen oracle         0.22251748    -0.21949046    55.6080
corrected reference   0.22094618    -0.21963098    54.1959
```

`PROVENANCE.md` says why. The reference is the **terminal + issuer corrected**
lineage, received 2026-08-09, carrying two fixes the frozen oracle predates: the
atomic terminal-action reconciliation, and the Sharadar `relatedtickers`
whitespace parse. Different holdings produce different `damaged`/`green`
breadth, and the fast path reads nothing but breadth and returns — so the
trigger fires on one shadow and not the other.

**And the correction runs in our favour.** `PROVENANCE.md` records that the
production engine already parses `relatedtickers` correctly and always has:

```text
services/bt-data/app/main.py:307              " ".join(rt)
services/backtester/.../wealth_core_replay.py:817   (...).split()
shared/.../wealth_core/eligibility.py:215     build_issuer_group_key
```

So Sentinel's Wealth Core, on a correct corpus, produces the CORRECTED shadow —
the 406-day path. **Requiring it to reproduce 386 would be requiring it to
reproduce a defect.** The 386 figure is sound as a description of the frozen
research run and is the wrong acceptance target for a production engine that
does not share its bug.

---

## 4. Finding C — SPY is not obtainable in this environment

The reference implementation sources it from Sharadar:

```python
spy['ret']    = spy.closeadj.astype(float).pct_change()
spy['r20']    = spy.closeadj.astype(float).pct_change(20)
spy['volacc'] = spy['ret'].rolling(5).std(ddof=1) / spy['ret'].rolling(20).std(ddof=1) - 1
```

No SPY price series exists in any repository artefact — not in the handoff, not
in the reference bundle, not in any fixture. Recomputing the fast path therefore
needs the Sharadar corpus, which needs the NAS. Like #15, this is blocked on
hardware rather than on design.

Two implementation details worth capturing now, because they are silent if
wrong: the volatility ratio uses **`ddof=1`**, and the horizon is a **rolling
standard deviation of daily returns**, not of prices.

### C1. SPY needs `closeadj`, which is enforced-unread

`tests/sentinel/test_feed_domains.py::test_closeadj_is_never_read` tokenizes
every file under `sentinel/` and fails on any executable reference to the
column. The rule is right and its reasoning is right:

> A total-return series in the signal domain changes momentum on every dividend
> payer; in the mark it sizes every 4% admission off the wrong equity.

But that reasoning is about **Wealth Core's four price domains** — what the book
is scored on and marked at. SPY here is not a holding; it is a market-regime
SENSOR, and the frozen rule specifies it as total return. The ban and the
requirement are both correct and they are about different things.

The resolution is a **narrowing, deliberately made and separately tested** — the
prohibition should attach to bar normalisation and holdings pricing, not to the
`sentinel/` tree as a whole — not a quiet exception, and not a `# noqa`. A
safety guard that acquires an undocumented carve-out is a guard that will
acquire a second one.

---

## 5. The settled split (decided 2026-08-11)

```text
1  the controller DECIDES at close; the effective series is the decision series
   shifted one session. Assert against the reference's decision-basis column,
   or shift explicitly — never compare the two bases directly

2  the fast path recomputed from raw inputs reproduces the CORRECTED reference
   lineage: 406 severe days including 2025-04-08 .. 2025-05-06, on the shadow
   our own engine produces

3  the frozen oracle remains authoritative for the RULE — every threshold, and
   the ramp certification already achieved — and is NOT the acceptance target
   for the severe path, because its shadow carries defects this engine does not

4  `closeadj` is unbanned for the SPY sensor by narrowing the guard, with its
   own test, in its own change
```

The alternative — reproducing 386 — is achievable only by reintroducing the
issuer-identity and terminal-order defects into the shadow, which would mean
certifying the production engine against a known-wrong book. **The
pre-correction shadow is deliberately not being recovered**; the corrected
lineage is the one intended for deployment.

**Step 2 moves to the NAS**, beside #15. Both need SPY and SPY needs the corpus.

### 5a. The `closeadj` contract, stated narrowly

The global Wealth Core guard is NOT weakened. A second, separate contract is
added beside it:

```text
Wealth Core security signals and marks      may NEVER read closeadj
the Sentinel market-regime sensor (SPY)     MAY read closeadj, because the
                                            frozen controller specification
                                            explicitly requires a total-return
                                            series
```

Two rules, two tests. The SPY exception must not become precedent for feeding
adjusted prices into Wealth Core, so the narrowing is by MODULE — a single named
regime-data path — rather than by column, and the existing tokenizer guard keeps
covering everything else under `sentinel/`. A future engineer reaching for
`closeadj` in a scoring or marking path still hits a wall.

---

## 6. Step 3, which does NOT wait on the NAS

Two halves, and the first is strictly stronger than re-running the experiments:

```text
FROZEN RESEARCH ARTEFACTS as acceptance oracles
    07_leave_one_crisis_out.csv        crisis holdouts
    04_delay_cost_sensitivity.csv      delayed signals, execution cost
    08_rolling_start_validation.csv    60 rolling starts
    09_fixed_5y_windows.csv            15 fixed windows
    10_time_blocks.csv                 5 regime blocks
    05/06_*_plateau.csv                parameter and gate plateaus
    11_controlled_recovery_adversarial_worlds.csv   3,000 synthetic worlds

NEW SYSTEM-LEVEL SIMULATION, which no artefact can answer
    controller + Wealth Core composition      catch-up after outages
    external cash                             stale / missing data
    restart equivalence                       recover twice = no further action
    single-name and multi-name failure        execution convergence
```

These are frozen evidence from the research process. Asserting against them is
stronger than reproducing the experiments, because a re-run can only ever agree
with the code that produced it.

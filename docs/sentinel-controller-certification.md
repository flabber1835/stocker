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

### 5b. The exemption, NAMED — decided before implementation (2026-08-12)

§5a settled that the narrowing happens. This settles exactly what it is, because
"a single named regime-data path" is not yet a name, and an unnamed exemption is
the kind that widens by accident.

**1. The one module permitted to name or read `closeadj`:**

```text
sentinel/regime/spy.py        the SPY market-regime sensor. Nothing else.
```

Not the package — the FILE. `sentinel/regime/` as a whole is not exempt, so a
second module added beside it inherits the prohibition rather than the
exemption. It declares the column as `SPY_PRICE_COLUMN` and that declaration is
the entire surface of the carve-out.

**2. Why total return is CORRECT here.** SPY in this rule is not a holding. It
is a market-regime sensor, and the frozen specification defines both of its
predicates on a total-return series (`standalone:176-178`). A dividend paid by
an S&P constituent is not a market decline, but it moves a price-return index
down; measuring regime on price return would read every quarterly dividend
season as mild market weakness. `spy_r20 <= -0.01` is a 1% threshold, which is
inside the range that error moves. The total-return domain is what makes the
threshold mean what the frozen rule says it means.

**3. Why `closeadj` remains WRONG everywhere else, stated per path:**

```text
Wealth Core signals    momentum on a total-return series changes on every
                       dividend payer, so the ranking silently reorders
Portfolio marking      sizes each 4% admission off the wrong equity
Execution              a total-return price is not a price anything trades at;
                       fills reconcile against closeunadj
Breadth                own_dd/r21/r63 are SIGNAL-domain by construction. The
                       recovered classifier reads SEP.close, and feeding it
                       closeadj would move every boundary in sentinel/breadth/
Any security-level path  same reason as signals: it is a synthetic series
```

The distinction is not "adjusted is riskier". It is that a total-return series
answers a different question, and every one of those paths is asking the other
one.

**4. No other module may name or read it.** The guard enforces this by FILE
path, and the allowlist is asserted to have exactly the expected entries — so
adding a second permitted module fails the suite rather than passing quietly.

**5. Widening requires a deliberate design change AND a test change**, in that
order, with an entry in this document. That is the point of pinning the
allowlist by equality rather than by membership: there is no way to add a path
without editing the assertion, and no way to edit the assertion without saying
why here.

**6. A defect in the existing guard, found while making this change and fixed
by it.** The tokenizer skips STRING tokens so that docstrings explaining the
prohibition do not violate it. But that also exempted string literals in
executable code:

```text
df.closeadj             CAUGHT today       NAME token
bar["closeadj"]         NOT CAUGHT today   STRING token
```

The second form is the natural one in this codebase, which passes corpus rows as
dicts. So the guard was materially weaker than it read, and a narrowing that
merely allowlisted a module would have left the hole open underneath it. The
replacement skips COMMENTs and DOCSTRINGS specifically — not all strings — so a
dict-key read is now caught everywhere except the one permitted file.
`sentinel/feed/domains.py` keeps a second, tightly-scoped entry for
`SEP_FORBIDDEN_COLUMNS = ("closeadj",)`: naming the prohibition is not
committing the violation, and that constant is what makes the ingest drop the
column. **This change makes the invariant stricter overall while carving out one
sensor.**

**7. What `sentinel/regime/` can and cannot claim.**

```text
SPY regime rule       SPECIFIED       by the frozen Sentinel rule
sentinel/regime/      IMPLEMENTED     faithful to frozen config, boundary-
                                      falsified, mutation-tested
direct tape parity    IMPOSSIBLE      SPY inputs are absent from every handoff
                                      artefact — there is nothing to compare to
forward-chain proof   REQUIRES NAS    raw corpus -> breadth -> SPY regime ->
                                      controller, on the corrected lineage
```

"IMPOSSIBLE" is a property of the preserved artefacts, not a gap in the logic.
The rule is fully specified and the implementation is faithful to it; what is
absent is a historical SPY series to replay it against. Do not describe this as
missing or unrecovered logic — the sense in which breadth was once missing does
not apply here and never did.

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


---

## 7. Step 2, revised: work FORWARD from raw data (decided 2026-08-11)

The earlier plan made the corrected 406-day reference the thing to reproduce.
That is the weaker construction, and the revision is right: an implementation
whose objective is to match a tape can be tuned until it matches a tape.

```text
raw Sharadar  ->  recovered breadth classifier  ->  SPY regime  ->  frozen rule
                                                                        |
                                                                        v
                                       the corrected reference is the FALSIFIER
```

Each stage is a deterministic algorithm recovered or frozen independently. If
the chain reproduces the corrected lineage without having been aimed at it, the
agreement is evidence. If it is aimed at it, the agreement is a tautology.

### 7a. The recovered breadth classifier IS in the repository

`09_GAPS` recorded the classifier as NOT FOUND. That was true of the handoff
bundle and only of it; the entry now carries a status note pointing here. The
classifier was recovered independently on 2026-08-09 and is present in
`docs/sentinel-reference-implementation/
sentinel_1p1_standalone.py`, labelled in the source as *"Exact recovered breadth
classifier, computed directly from current shadow holdings"*:

```text
own_dd  = signal_close / episode_peak_signal - 1
r21     = 21-session signal return
r63     = signal_close / signal_close[t-63] - 1
age     = sessions since entry

green   = own_dd > -0.075  AND  r21 > 0  AND  (age < 63 OR r63 > 0)
red     = own_dd <= -0.10  AND  r21 < 0

sstress = reds_in_sector / held_in_sector          # per GICS sector
amber   = own_dd <= -0.10  OR  r21 <= -0.03  OR  (sstress >= 0.50 AND NOT green)

green_b   = greens / len(held)
damaged_b = ambers / len(held)
```

Three properties that are not obvious and are silent if got wrong:

```text
RED FEEDS ONLY SECTOR STRESS. It never enters green_b or damaged_b directly;
    its entire role is the per-sector denominator behind `sstress`

AMBER IS NOT THE COMPLEMENT OF GREEN. The two are disjoint, but they do not
    partition the book — green_b + damaged_b need not sum to 1, and a
    classifier that forces them to has changed the strategy

THE DENOMINATOR IS len(held), the CURRENT shadow holdings, which matches the
    forensic finding that the frozen fractions divide by the position-panel row
    count rather than a `holdings` column
```

### 7b. CORRECTION — §8 of the architecture doc states GREEN incompletely

`sentinel-architecture.md` §8's forensic note says:

> GREEN `own_dd >= -7.5% AND r21 >= 0 AND r63 >= 0`

The recovered code says:

> `own_dd > -0.075 AND r21 > 0 AND (age < 63 OR r63 > 0)`

Two differences, both material:

```text
STRICTNESS   `>` and `>=` differ exactly at the threshold, and a book marked
             precisely at its peak (own_dd == 0) is common, not exotic

THE AGE ESCAPE  a holding younger than 63 sessions is GREEN with NO r63 test
             at all. That clause is absent from the prose entirely, and it
             governs every newly admitted position — 4% of equity each, one
             per session, so a fresh book is mostly positions in that band
```

An implementation built from §8's summary would misclassify young holdings and
shift `green_b` on exactly the sessions after a recovery, when the book is being
rebuilt. This is the hazard §7 names — *re-inferring Sentinel from prose* —
found in the document's own summary of the code. **The standalone source is
authoritative; §8's prose is orientation.**

### 7c. What the NAS run must therefore do

```text
1  implement the recovered classifier from the STANDALONE SOURCE, not from any
   prose summary, and reproduce the frozen breadth tape before anything
   downstream is accepted — the frozen rule's own precondition
   [IMPLEMENTED offline as sentinel/breadth/. The TAPE half is still owed —
    see 7d below for exactly which half is done]
2  compute the SPY regime series: closeadj, rolling std of DAILY RETURNS,
   ddof=1, vol5/vol20 - 1
3  narrow the closeadj guard to a named regime-data module, with its own test
4  run the whole chain forward and compare on DECISION basis against the
   corrected reference: 406 severe days including 2025-04-08 .. 2025-05-06
5  any mismatch is a certification failure, not a tolerance to widen
```

The `decide` seam stays empty until step 4 passes. Wiring a driver before the
upstream signal chain is certified would mean choosing an implementation to fill
it on the strength of the part that is not yet proven.

### 7e. The 7,061-session target is UNREACHABLE by the corrected engine, and that is by design (measured 2026-08-12)

Before regenerating a holding panel from raw Sharadar, the two preserved tapes
were compared directly. Both are in the repository; the comparison needs no
corpus and takes seconds. `scripts/sentinel-breadth-lineage-diff.py` reproduces
it.

```text
frozen oracle    04_BREADTH_ORACLES/fundamental_portfolio_health_daily.csv
                 7,062 rows, 1998-07-06 .. 2026-07-31   PRE-correction lineage
corrected tape   sentinel-reference-implementation/sentinel_1p1_daily.csv
                 5,032 rows, 2006-07-31 .. 2026-07-31   terminal + issuer corrected
```

Result on the 5,032-session overlap:

```text
identical          4,183
divergent            849   16.9%
FIRST DIVERGENCE  2016-02-05, after 2,396 CONSECUTIVE IDENTICAL SESSIONS
                  frozen     16 damaged /  2 green of 19 held
                  corrected  17 damaged /  2 green of 20 held
```

**Two conclusions, and the second is the certification-relevant one.**

*The classifier rule is the same in both lineages.* 2,396 consecutive identical
sessions cannot happen under two different classification rules. A strictness
error or a missing clause diverges immediately and everywhere, not after nine
and a half years.

*The BOOKS differ, starting at a single dated event.* The first divergence is a
held-count change, 19 to 20 — a population difference, not a classification one.
That is exactly the signature of the terminal-order correction, which found the
old replay buying a delisted security and spending admission slots on already
terminated ones. It matches the date the architecture document already recorded
for this divergence, derived independently there.

Of the 849 divergent sessions, 399 (47%) have a different held COUNT and are
definitively population differences. The other 450 have the same count; that is
NOT evidence of a rule difference, because once the held set diverges a
same-size book of different names produces different counts under an identical
classifier. The fractions alone cannot separate those two causes, and the script
deliberately does not claim otherwise.

**Therefore the 7,061/7,061 result cannot be reproduced by this engine, and
reproducing it would be a defect rather than an achievement.** That measurement
was taken against the frozen oracle using the PRE-correction panel. Matching it
now would require reintroducing the terminal-order and issuer-identity defects
into the shadow — which §5 already ruled out for the 386-day figure, for the
same reason. The pre-correction shadow is deliberately not recovered.

This is a **CATEGORY B** result, and the blocker is NOT Sharadar restatement:

```text
classifier parity        ESTABLISHED    2,396 identical sessions across two
                                        independently produced lineages, plus
                                        the randomised differential in
                                        tests/sentinel/test_breadth_classifier.py
input-population parity   IMPOSSIBLE    the target panel belongs to a superseded
                                        book carrying a defect this engine does
                                        not have, and is not being recovered
tape parity vs FROZEN     IMPOSSIBLE    follows from the above
tape parity vs CORRECTED  UNVERIFIED    reachable, and the right target. See
                                        below
```

**The right target is the corrected tape, and it is still unverified.**
`docs/sentinel-reference-implementation/PROVENANCE.md` states it plainly: *"Not
verified: that running `sentinel_1p1_standalone.py` against raw Sharadar
reproduces `sentinel_1p1_daily.csv`. That needs the corpus. The tape is stored;
the producer is unverified."* That run — 5,032 sessions, corrected lineage —
is what F(a) and F(b) should be aimed at. Aiming them at 7,061 was aiming at the
wrong artefact.

`UNCERTIFIED_BREADTH` therefore STANDS, and the reason is now specific: not "the
engine is unproven" but "the engine has never been run against the corpus and
compared to the tape of its own lineage".

### 7d. Step 1's offline half is DONE: `sentinel/breadth/`

The classifier is transcribed from `sentinel_1p1_standalone.py:526-546` into a
pure stdlib-only module in the appliance. Be precise about what that buys,
because the two halves of step 1 are easy to collapse into one claim:

```text
DONE, and falsified offline
  the predicates, transcribed from the source and not from prose
  every strict-vs-inclusive boundary, tested AT the threshold and one step
    across it: own_dd 0 and -0.075, r21 0 and -0.03, red's -0.10, r63 0,
    age 62 vs 63, sector stress exactly 0.50, escalation with green true/false
  the age-63 exemption as a WAIVER — r63 absent must still be green at 62
  the len(held) denominator, and the empty book as 0.0/0.0 rather than NaN
  the float32 lag-close contract, with a fixture that FLIPS a classification
    under float64 (identical current and lag price: r21 == 0 -> not green,
    r21 == +1.5e-8 -> green)
  a randomised 300-book differential against the stored pandas artefact, with
    values clustered ON the thresholds rather than uniformly sampled

NOT DONE, and not claimable until the NAS run
  reproducing the 7,061-session breadth tape from the raw Sharadar corpus
  the corrected-lineage comparison that step 4 makes on a DECISION basis
```

Every item in the first block was mutation-checked: the semantics were broken
one at a time — age exemption removed, each comparison flipped strict/inclusive,
the escalation dropped, `AND NOT green` dropped, float32 replaced by float64,
the denominator changed, each threshold constant moved — and the suite failed in
every case. A guard nobody has watched fail is a guard nobody has tested.

What the module deliberately does NOT do: read a tape, read the corpus, read
anything under `docs/`, or fall back to a frozen output. A fallback is how a
reconstruction quietly becomes a replay, and there is a test asserting the
absence rather than a comment promising it.

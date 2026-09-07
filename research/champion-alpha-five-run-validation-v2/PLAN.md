# Corrected Champion alpha validation plan

Status: PRE-RUN DESIGN FROZEN

## Authoritative baseline certification

The only baseline allowed for this study is the completed one-session dividend recertification:

- workflow run: `34071569702`
- artifact: `10001317230`
- artifact digest: `sha256:803b1b8288d77fc9c275cec5ebac91f8bac23ba030dad3dfb5d523fceed2415f`
- branch/source head: `1d3ab06a0b6c1ef5db4939bbecfe24953ae2195d`
- formal source: `27bb992087182c42c3c051e62bf837895f5d2ab7`
- classifier source: `ba74e79490beb8950611b1d17f5d124833b3d91e`
- runtime source: `887f479b15ad861313da666ad698034d3847121c`
- canonical PIT dataset hash: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- canonical PIT package: `ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c`
- measurement window: 2006-07-31 through 2026-07-31, 5,032 sessions
- dividend settlement: exact next-session `gday + 1`
- 20-year strategy CAGR: 18.800888800126314%
- 20-year ending multiple: 31.363500124285768
- 20-year maximum drawdown: -24.91366167248561%
- 20-year daily Sharpe: 1.0363365863293037
- final factual security-type corpus: PASS, 696 effective securities, zero unresolved, zero issues

The obsolete 15-session certificate is excluded from all control comparisons.

## Corrected black-box observations to reconfirm before experimental outcomes

These observations were recomputed from the corrected certified daily portfolio path, before any experimental result is available.

1. **Vacated-slot timing fingerprint.** Thirteen clean 25-to-24 single-removal windows at full stock allocation have no intervening membership change and every next addition occurs exactly 22 session steps later. This is consistent with a 21-session slot cooldown followed by next-open execution.

2. **Admission throttling.** The generated certified source permits only one new admission per session after initialization, even when multiple slots are ready. This is an observable mechanism that can prolong under-filled books after clustered exits.

3. **Holding-age boundary.** The corrected selected-position path has 68 exits at age 120 session steps, compared with 2 at age 119 and 6 total across ages 121-129. The executable review boundary is `REVIEW_AGE = 119`, with qualifying exits occurring at the following open.

4. **Recovery participation.** The corrected path has six zero-stock episodes. Several protect materially against additional losses, especially 2008-09 and 2020. Others give up substantial benchmark recovery while stock exposure remains zero; examples include 2011 (+7.65% SPY endpoint return), 2015 (+8.02%), 2018-19 (+11.15%), and 2022 (+11.26%). This is a timing hypothesis, not evidence that full immediate reentry is superior.

5. **Book underfill.** At full stock-book allocation the corrected path averages 23.227 holdings, and 73.62% of full-allocation sessions contain fewer than 25 names. Membership count does not by itself establish cash percentage, but it confirms persistent capacity vacancies.

These observations are diagnostics only. No price/return outcome from the experimental arms may alter the definitions below.

## Five authorized historical replays

The corrected certification replay above is the control and does not consume the five experimental run allowance. Exactly five variant replays are authorized. Each is a fresh chronological PIT replay from initial state. No prior holdings, trades, pending orders, allocations, controller state or NAV path may drive a variant.

### Run 1 — FRESH_REPLACEMENT

Hypothesis: the slot-level 21-session vacancy delay suppresses productive capital redeployment.

Change only slot reuse timing after a position leaves:

- vacated slot `ready_day` becomes the current execution session (`gday`), allowing a fresh replacement decision at that session's close and execution at the next session's open;
- security-specific `book.sec_ready[sold_security] = gday + 21` remains unchanged;
- terminal-event security cooldown remains 21;
- one-new-admission-per-day limit remains unchanged;
- all ranking, eligibility, sizing, costs, stops, review logic, controller logic and execution timing remain unchanged.

This separates fresh-name replacement from same-security reentry.

### Run 2 — MULTI_REFILL

Hypothesis: the one-new-admission-per-day throttle prolongs exposure to an under-filled stock book after several slots become available.

Change only initialized-book admission budget:

- when multiple slots are already ready, admission budget is `len(ready)` for that close;
- slot cooldown remains 21 sessions;
- security cooldown remains 21 sessions;
- candidate ordering, ranking, issuer uniqueness, sizing, costs and next-open execution remain unchanged.

### Run 3 — EARLY_WEAK_REVIEW

Hypothesis: some persistently weak positions consume capital for roughly six months before the existing review boundary.

Add one causal early assessment at holding age 59 sessions while preserving the existing age-119 review:

- add `early_reviewed` state per slot;
- at age >= 59, once only, apply the existing review predicate using information available at that close: `underwater and not qualifies`;
- failure queues the same review sale for the next available open;
- passing the early check marks only `early_reviewed=True`; the original age-119 review remains active;
- stop logic remains prior in precedence and unchanged;
- all entry, ranking, sizing, cooldown, controller and execution rules remain unchanged.

### Run 4 — STAGED_RECOVERY

Hypothesis: zero-stock protection can remain active after a causal recovery becomes sufficiently persistent.

Preserve the baseline Wealth Core stock book and all baseline native/controller calculations. Add a separate causal overlay only to the strategy allocation target while baseline Candidate-A desired allocation remains zero:

- on the first close whose baseline Candidate-A desired allocation becomes zero, store that session's SPY adjusted close as the episode reference and set zero-session count to 1;
- while the baseline desired allocation remains zero, increment zero-session count and maintain a consecutive qualifying-close streak;
- a qualifying close requires all of: current SPY adjusted close > stored reference; SPY 20-session return > 0; Wealth Core trailing 5-session return > 0; current fast shock signal is false;
- before 10 zero-target sessions, experimental desired allocation stays zero;
- after at least 10 zero-target sessions and 5 consecutive qualifying closes, experimental desired allocation becomes 0.25;
- after 10 consecutive qualifying closes, experimental desired allocation becomes 0.55;
- any failed qualifying close while baseline remains zero resets the qualifying streak and experimental desired allocation to zero;
- when baseline Candidate-A desired allocation becomes positive, the probe resets and the experimental target equals the baseline desired target;
- target changes execute with the existing next-session-open allocation timing and existing transaction-cost convention.

No future recovery date, crisis schedule or prior baseline decision tape is used.

### Run 5 — COMBINED

Apply exactly Runs 1-4 simultaneously. No component is selected or removed based on Runs 1-4 results.

## PIT, classification and causality gates

Every arm must:

- consume the same pre-existing canonical PIT package and verify its immutable digest before replay;
- use the same formal strategy source, classifier source, runtime source and final factual security-type corpus as the corrected certification;
- preserve exact one-session dividend settlement and prove it structurally before replay and in the executed engine summary afterward;
- execute session-by-session from fresh initial state;
- use only session-available prices, rankings, metadata, corporate actions and controller inputs;
- retain next-session execution timing for close decisions;
- fail closed if classification coverage, identity, terminal terms, NAV resolution, package identity or source pins differ from the corrected certification;
- report any new unknown security classification with security ID, ticker and interval. No classification may be changed using performance information.

The variants alter no universe classification rule, so no classification expansion is expected unless a changed path reaches a security/interval that the certified control did not require. Such a case stops that arm before an authoritative result is reported.

## Reporting contract

For each arm retain full daily evidence plus manifest and report:

- 20/15/10/5-year CAGR, ending multiple, max drawdown and Sharpe;
- SPY comparison;
- first divergence from corrected baseline observable state where applicable;
- holdings/admissions/exits and under-filled-book statistics;
- allocation exposure and zero-stock/recovery statistics;
- transaction-cost totals and transition counts available from engine output;
- classification coverage and unresolved count;
- exact experiment source SHA and generated executable SHA;
- exact PIT package/dataset identities.

Interpretation must separate increased return from increased exposure and increased drawdown. The 2008-09 and 2020 protection paths are mandatory checks for the recovery arm and combined arm.

This 20-year history is already an inspected research sample. Positive results validate an in-sample historical mechanism only; they do not establish prospective alpha.
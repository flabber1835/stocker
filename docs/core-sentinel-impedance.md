# Wealth Core / Sentinel interface investigation

## Scope and experiment registration — 2026-09-21

Base: `da7b64a9429c9c73fb7efac90c8d4a5decb39e13`. This is a research
investigation, not a production strategy change or economic certification.
The selected authority remains `production-compact-champion.md`. Older defense
plans describe superseded controllers; in particular ordinary stress is a
sensor, not an independent 15.5% liquidation backstop in the selected champion.

The owner requests calibration/interface matching without fitting historical
returns. The preceding historical diagnostic motivated the questions below.
Consequently these hypotheses are NOT blind discoveries or an untouched
holdout. Synthetic results can establish mechanics and counterexamples, not
expected investment performance, crisis probabilities or superior CAGR.

### Boundary and deliverable

Use the existing production Native, recovery, peer-breadth and canonical Wealth
Core components. Do not modify their parameters, registration, state schemas,
broker-facing paths, immutable shadow or golden artifacts. A standalone research
runner and tests will record counterexamples and alternative **entry eligibility**
only; alternatives are not complete strategies and have no deployable actuator.
There is no historical-data input, return optimizer or candidate ranking by P&L.
No NAS, broker, credentials or historical replay continuation is required.

### Hypotheses registered before synthetic results

1. **Bounded damage acceleration:** damage is in [0,1]; the five-session
   increase cannot exceed 1 minus prior damage. All-at-once shock detection can
   become unreachable during sustained high damage. Test book sizes 5, 10, 20
   and every feasible prior damaged count, with current damage at 100% and all
   other fast conditions satisfied.
2. **Signal timing:** test abrupt damage, previously damaged books, displaced
   market confirmation, gradual decline, and short versus sustained corrections
   followed by recovery. Derive Core returns/drawdown from each synthetic NAV
   path. These are controller-input experiments, not complete market/book
   simulations; supplied breadth and market observations are explicit probes.
3. **Capital versus headcount:** feed production peer breadth identical price
   histories and labels while changing owned quantities. Count damage should
   stay fixed; damaged capital and actual remaining equity exposure may differ
   substantially. Weighted damage is a diagnostic, not a substituted signal.
4. **Ownership turnover:** execute canonical Core trailing-stop sales at the
   next open with unchanged survivor prices. Compare pre/post-sale breadth,
   NAV, cash and stock value. Distinguish reduced future risk from price recovery
   and realized loss. Do not keep sold names as fictitious current holdings.
5. **Recovery population:** test the frozen Candidate A persistence route with
   positive leadership returns but weak owned Core; also positive Core with weak
   leadership. Neither broker P&L nor historical reference exposure is an input.
6. **Cash/actuator units:** demonstrate exposure multiplier times Core invested
   fraction. Do not renormalize weights to make nominal 100% Core equal 100%
   stocks. Observe the separate Core cash and defensive-sleeve amounts.

### Alternative mechanisms to diagnose, not select

- **Drop acceleration:** fast eligibility without the damage-increase clause.
  This is an ablation control, expected to lose discrimination between a new
  shock and old damage; it is not the proposed production fix.
- **Remember recent confirmation:** current damage/drawdown/return conditions
  remain necessary, but damage and market-volatility confirmations may have
  occurred in the current or four preceding sessions. This uses the existing
  five-session measurement horizon as an explicit illustrative memory budget.
  It must expire evidence and cannot repair a book that was already saturated
  before the entire memory window.
- **Separate persistent impairment:** retain current fast eligibility and add
  five consecutive sessions meeting existing drawdown, damage, green and
  market-or-severe-Core-return confirmation levels, without the two acceleration
  gates or short-return gate. This distinguishes a level from its derivative.
  Five sessions is an illustrative existing horizon, NOT a calibrated dwell.
  Report its delayed response and extra exits during transient corrections.

No candidate is promoted for passing its motivating example. Every report must
also show the scenarios it does not solve and benign/transient cases it would
add. New entry/recovery combinations, data-availability behavior, evidence
ownership and state restoration require a separate design before deployment.

### Verification and reporting contract

Use independent arithmetic oracles for bounds, value and costs. Check JSON
restart equivalence for Native and recovery. Use an explicit falsifier that
breaks each experiment's claimed distinction; do not count tests that merely
reproduce snapshots. Record exact source hashes, synthetic inputs, commands and
results. No full unrelated suite and no Wealth Core suite: production Wealth
Core is unchanged. Report the tests as component/interface diagnostics only.

Interpretation will distinguish a documented policy consequence from a proven
implementation defect. An invariant such as split/identity/accounting neutrality
can establish correctness; an acceptable false-exit rate, drawdown tolerance or
response deadline must be specified as a risk objective, not inferred from a
profitable historical setting.

## Findings

The experiments completed. The claims below are bounded observations, not new
production requirements. No implementation defect was demonstrated in these
selected paths: the consequences follow the selected policy and input meanings.
This does not establish that the complete economic path is defect-free.

### 1. The shock detector is sensitive to ordering and saturation

The 38 cases covering every prior damaged count in books of 5, 10 and 20 agree
with the independent rational bound `delta_damage <= 1 - prior_damage`.
Once prior damage exceeds 70%, the frozen 30-percentage-point increase cannot
occur. Both book and market conditions must pass together in
[`champion_frozen.py:46`](../sentinel/controller/champion_frozen.py#L46).

The path experiments use time derived from synthetic NAV for Core drawdown and
returns, with explicitly supplied breadth and market probes. They are NOT
claims that every vector is reachable from a full universe and canonical book.
There are 960 controller transitions, with a JSON restart after every transition.
The table uses zero-based closes after 60 warmup observations; execution would
be at the NEXT open, never at the detected close. `None` means no entry during
the tested path, not proof about all possible futures.

| Prespecified path | Frozen Native first defense | Drop damage acceleration | Recent confirmations | Persistent-level addition |
|---|---:|---:|---:|---:|
| Abrupt shock | 0 | 0 | 0 | 4 |
| Already damaged before both windows | None | 0 | None | 4 |
| Market confirmation six sessions late | None | 6 | 6 | 4 |
| Confirmation expired, renewed price loss | None | 10 | None | 4 |
| Gradual 40-session decline, then flat | 59 | None | None | 24 |
| 20% loss, then flat for 60 sessions | None | None | None | 4 |
| Four-session correction, then full rebound | None | 0 | None | None |
| Eight-session correction, then full rebound | None | 0 | None | 4 |
| Healthy | None | None | None | None |

The last three columns report additional/alternative entry ELIGIBILITY, not
traded allocations. Recovery, latch/re-arm, costs, missing data and state schemas
are not supplied for these conceptual alternatives. In particular the persistent
addition preserves the existing fast path; its later eligibility at close 4
does not replace the original close-0 shock response.

The slow route also has a deliberate additional-loss requirement: NAV must fall
at least 2% BELOW its stress-start anchor, not just remain far below its all-time
peak (`champion_frozen.py:85`). In the 20%-down plateau, the anchor and current
NAV are both 80. The ordinary stress clock reaches 30 but never causes a sale.
In the gradual decline, the anchor is reached late, and slow defense only starts
at close 59. These are vulnerabilities only if the intended mandate requires
protection in such conditions; a detector intended solely for accelerating loss
would deliberately behave differently.

### 2. Core capital and Sentinel headcount measure different things

Core retains winners without trimming or rebalancing
(`shared/stock_strategy_shared/wealth_core/engine.py:9`). Production peer breadth
uses one vote per currently held episode and up to three residual-correlated
neighbors (`sentinel/controller/median5_breadth.py:50`), regardless of dollars.

The same 18 damaged names out of 20 yield 90% damage with either 0.65% or 99.98%
of stock capital in those names when quantities are changed. This is an extreme
seeded ownership counterexample, not a predicted portfolio or proof it arises
from one common initial-capital history. It establishes that count breadth does
not uniquely identify capital at risk. The production NAV gates still respond
to dollars; this result alone does NOT prove that final allocations ignore them.

Do not replace count breadth with weighted breadth while retaining its old
thresholds. They answer different questions: extent of participation versus
capital affected. Observe both, together with invested fraction, largest weight
and effective number of positions. A future policy can then distinguish broad
damage in small residual holdings from concentrated damage in major winners.

### 3. Core stops change the sensor population

The canonical adapter, with unchanged prices across both sessions, sells ten
stopped positions only at the next open. Breadth changes from 50% damaged / 50%
green to 0% damaged / 100% green. NAV falls from 1,700 to 1,699.40 from 0.60 fees;
cash becomes 599.40. No price has recovered. This is not false accounting:
remaining risk really has fallen. It is a different explanation of the improved
breadth than a recovering stock cohort.

Core cash also changes actuator units. The remaining stock fraction is 64.73%.
A 55% Core multiplier therefore means approximately 35.60% of account NAV in
stocks, before account-level rounding and execution differences. A second
capital probe with 75% Core cash gives 13.75% stocks at that same multiplier.
This multiplication is intended. Renormalizing Core weights to reach 55% stocks
would change the strategy and undermine its cooldown/cash decisions.

The matching remedy is to attribute breadth changes to continuing names, exits,
entries and action transformations, and show cash separately. An exited cohort
may be retained as diagnostic memory, never as fictitious current ownership.
Pre-sale losses must not be erased from impairment/recovery evidence merely
because the denominator changed. This is a proposed evidence contract, not a
newly imposed production rule.

### 4. Recovery samples another population

The persistence branch accepts eight consecutive positive recent-leadership
20-session returns and leadership r40 above -4%. Unlike its separate concordance
branch, it does not require positive Core r20
(`sentinel/controller/champion_frozen.py:168`, `:191`). Conditional on Native
having returned to full, the probe releases on the eighth session even with
Core r20 at -10%. Positive Core with weak leadership stays held out.

This probe isolates Candidate A; it does not claim that Native can clear every
possible weak-Core path. Core and leadership are intentionally independent
surfaces. Core owns persistent positions, cash, dividends and trading costs;
the recent-leadership witness uses prior membership in a frequently refreshed,
equal-weight signal cohort (`sentinel/controller/median5.py:171`). Their raw
return magnitudes therefore do not represent the same economic instrument.

The design question is whether recovery should mean 'new opportunities exist',
'the owned book is recovering', or both. Do not silently use those descriptions
interchangeably. A separate owned-Core readiness condition may match protection
to what will actually be held, but can delay recovery and miss rebounds. A test
with no historic returns cannot determine the acceptable tradeoff.

## Recommended direction, without selecting profitable thresholds

1. **Define the risk mandate first.** Specify response deadlines for a sudden
   loss, a sustained impairment and a concentrated-position loss; define how much
   extra turnover/delayed re-entry is acceptable in temporary corrections. Those
   are owner risk choices. The current detector provides no universal drawdown
   ceiling, and next-open execution cannot promise one across overnight gaps.
2. **Measure matching quantities.** Keep existing count breadth; add diagnostic
   capital damage, Core cash, concentration, cohort continuity, and separate
   leadership/Core return definitions. This is the lowest-risk next engineering
   step because it need not change decisions. Classification/accounting repairs
   remain correctness work and must never be reversed to recover reference CAGR.
3. **Separate shock from persistent impairment.** Preserve the shock channel;
   specify a distinct level/duration channel if the mandate requires it. Give
   each bounded evidence memory, explicit healthy re-arm and a recovery rule
   tied to its own cause. The five-session illustration is not a selected dwell.
   Reusing an existing constant does not make it statistically validated.
4. **Evaluate readiness of the asset actually re-entered.** Compare leadership
   evidence with Core's current holdings, stops/cooldowns and cash. Avoid requiring
   a return to an old peak as the only recovery criterion: that can lock out a
   changed book indefinitely. Do not feed live fills or realized exposure back
   into this decision.

Recent-confirmation memory is a narrower possible change, but the experiments
show it does not fix persistent saturation. Simply deleting acceleration adds
exits in the four-session transient example. Headroom-normalizing acceleration
by `1 - prior_damage` is not an automatic repair either: the denominator becomes
zero at complete damage and amplifies tiny changes near saturation. Volatility-
normalizing every threshold introduces a different risk model and additional
estimation choices. None should be adopted because it repairs one old crisis.

Before any strategy change, freeze a small complete challenger specification and
its acceptance criteria. Exercise coherent synthetic market paths THROUGH the
canonical book/kernel, including peer correlations, cash, action neutrality,
missing observations and restarts. The current isolated tests are prerequisites,
not a substitute for that integration. Evaluate a frozen challenger on untouched
forward data and predeclared historical diagnostics; retain all trials and
measure missed protection, unnecessary exits, turnover and re-entry delay.
No optimization objective or acceptance criterion should be 'recover 56.27x'.

This separation of faithful implementation from fitness for intended use is
consistent with [NIST's verification/validation distinction](https://nvlpubs.nist.gov/nistpubs/ir/2020/NIST.IR.8298.pdf).
Our specific portfolio conclusions are inferences from repository code and the
synthetic evidence, not findings of that paper. Repeatedly selecting strategies
for in-sample performance can produce misleading results, as discussed by
[Bailey et al.](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
This investigation does not estimate a probability of overfitting or establish
an out-of-sample return expectation.

## Verification and retained artifacts

See [commands and results](../audit/impedance/README.md). Twelve new diagnostic
tests and nineteen existing champion tests pass; both deliberate mutants are
detected. No production algorithm or configuration changed. The synthetic
research tests are explicitly run locally; they are not a new protected CI owner.
Ordinary CI remains necessary for PR integration and is not strategy validation.

Fixture corrections during investigation are retained in this description:
pre-existing damage now predates both five-session windows, and the expired-
confirmation example includes renewed price loss so a separate short-return
gate cannot hide a broken expiry rule. These improve isolation; neither was
selected using historical returns. The plateau/grind observation horizon was
extended so the thirty-session slow gate was actually reachable.

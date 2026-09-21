# Current Sentinel: predefined parameter sensitivity probes

Owner-authorized synthetic comparison, 2026-09-21. Verified main base:
`ee23c894c97a2c4023654ce3a56a62728f5b061e`. This specification precedes
implementation and results. Related investigations: #431 and #432.

## Question and fixed alternatives

Can changing existing compact champion parameters improve its response without
adding the owned-impairment state machine? Compare the unchanged current profile
and four research variants. Select these simple halving probes before running;
do not search a grid, rank an optimized winner, or adjust after seeing returns.

| Label | Only parameter changes from current |
| --- | --- |
| current | None |
| fast_sensitive | FAST damage increase over five sessions: 0.30 to 0.15 |
| slow_earlier | SLOW qualifying base-stress duration: 30 to 15 sessions |
| recovery_faster | Candidate A recovery persistence: 8 to 4 sessions |
| combined | All three changes above |

All other predicates, thresholds, state transitions and rearming rules remain
unchanged. The fast path has simultaneous confirmation gates, not a configurable
multi-close entry streak. Lower acceleration still excludes zero acceleration;
shortening slow confirmation does not remove its base-stress and incremental-loss
requirements. Faster recovery may recapture rebounds or admit exposure too early.

## Research boundary and method

Load the exact production `champion_frozen.py` source into independent in-memory
research namespaces and override only the named numeric constants. Do not patch
production imports, change source files, bypass configuration checks or issue a
production identity for these alternatives. Hash the source and parameter map
into a research identity. Snapshots bind to that identity and refuse cross-variant
restoration. Existing bounded state counters suffice for these lower settings.

Drive the current production warmup, Wealth Core, breadth, leadership and kernel
once per unchanged PR #431 synthetic case. The membrane permits all variants to
consume that same independent Core stream. Replay formation into each controller
before measuring; never initialize variant memory from current-profile memory.
At every formation/scenario close, require the unmodified research controller's
native target, full native snapshot, recovery target and reason to equal the
actual production result. A mismatch stops the comparison.

Use the same seven cases, 252 feature-warmup sessions, 80 formation sessions,
120 measured sessions, $100,000 accounts, 10 bps costs, zero-yield synthetic bill,
whole shares and previous-close exposure at next-open prices as #432. Establish
accounts at the origin close to include the initial overnight shock. Reuse the
same account helper and stimuli; retain hashes/provenance. Full broker journals,
provider finality and NAS performance are outside this experiment.

Record every daily observation, leadership input, native/overlay decision,
snapshot, account trade, fee and NAV; report terminal differences, drawdown,
turnover, defense/recovery dates and false exits on healthy/correction controls.
Verify split-control decisions, controller restarts and account restoration.
Compare the unchanged current-profile economics to the retained #432 results;
do not alter those golden artifacts. Unit tests independently exercise each
parameter and the persistent zero-acceleration blind spot, research isolation,
identity rejection, baseline parity and account arithmetic/timing. Falsify the
new identity and parity guards. No full unrelated suite is required.

## Interpretation

This is a bounded mechanism/sensitivity test on already-known synthetic shapes,
not independent out-of-sample research or proof of improved historical returns.
Report every adverse case. No historical fit, parameter promotion, deployment,
certification or production-default change is authorized by this comparison.

## Results

Completed against the verified base above. Dollar differences below are terminal
wealth changes from the current controller on identical $100,000 accounts:

| Synthetic case | Current NAV | Fast sensitive | Slow earlier | Recovery faster | Combined |
| --- | ---: | ---: | ---: | ---: | ---: |
| Healthy | $111,311.54 | $0 | $0 | $0 | $0 |
| Synchronized shock | $86,153.21 | $0 | $0 | $0 | $0 |
| Staggered damage | $84,209.31 | -$1,213.01 | $0 | $0 | -$1,213.01 |
| Gradual decline | $89,560.79 | $0 | $0 | $0 | $0 |
| Temporary correction | $94,351.03 | $0 | $0 | -$67.74 | -$67.74 |
| Leadership rotation | $77,174.44 | $0 | +$1,072.44 | $0 | +$1,072.44 |
| Healthy split control | $111,311.54 | $0 | $0 | $0 | $0 |

All 920 distinct formation/scenario closes match the production control's
native/overlay targets, reason and full native snapshot. Baseline terminal NAV,
drawdown, fees and turnover exactly match the retained #432 reference in every
case despite the intervening spin-off implementation on main. No economic
reference or stimulus was repinned. All 280 controller and 280 account restart
comparisons match. Healthy/split observations and decisions match for every
variant; no variant exits on these two healthy controls.

### Economic explanations

- **Fast sensitivity:** staggered damage has already reached 80% before the
  second shock. The remaining jump is about 20 percentage points, below the
  original 30-point requirement but above the 15-point probe. The probe exits
  at close 15 and returns at close 66. Worst drawdown falls from 21.575% to
  20.451%, but missed recovery and costs reduce terminal wealth by $1,213.01;
  fees rise from $229.46 to $410.65. The initial gap still hits both accounts.
- **Earlier slow defense:** rotation's base stress starts at close 22. The
  15-session probe acts at close 36 while damaged holdings still exist. By
  close 51, when the original 30-session timer matures, Core has exited those
  holdings and damaged breadth is zero, so the original slow gate never fires.
  The probe returns at close 68, improves worst drawdown from 25.891% to
  24.650%, and adds $1,072.44 after higher fees. This is a concrete mismatch
  between the detection window and Core's ownership lifetime; earlier reaction
  captures only a small part of the losses in this scenario.
- **Faster recovery:** the temporary correction returns to full at close 11
  rather than close 15. That earlier re-entry loses $67.74 and slightly worsens
  worst drawdown (15.254% to 15.315%). In the synchronized shock, another native
  recovery gate still binds, so REC4 makes no economic difference.
- **Combined:** it inherits all three differences; there is no added benefit
  from combining them on these paths. Gradual decline remains unprotected by
  every variant, and the independent plateau probe remains fully exposed under
  all five settings.

### Decision

Parameter changes can partly align timing, but these tests do not support a
general sensitivity increase or replacing the structural correction with a
parameter tweak. Of these predefined probes, earlier slow defense is the only
one with a measured benefit and no adverse change in the seven cases. That is
a candidate for further independent validation, not an optimized setting or
approval to change production: these known shapes are a small sample and do
not exercise every false-exit/recovery market. Keep current defaults unchanged.

Evidence and exact commands: [audit/parameter-probes/README.md](../audit/parameter-probes/README.md).

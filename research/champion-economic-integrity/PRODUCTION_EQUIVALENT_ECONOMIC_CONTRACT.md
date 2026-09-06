# Production-equivalent Research Champion economic contract

Date: 2026-09-06

Status: **FROZEN FOR IMPLEMENTATION — NO PERFORMANCE REPLAY YET**

## Target question

This contract answers one question:

> If the frozen Research Champion had been switched on in 2006, and the live Production security classifier had correctly identified every security's factual type on every decision day, how would the system have behaved through 2026?

This is not a strict archival-source-availability certificate and it is not a claim that a $100,000,000 account could have been deployed without market impact. The $100,000,000 value is the frozen shadow-book initial condition used to generate the normalized strategy curve.

## Frozen identities

- Security-truth integration base: `023dda5f63ea64fea0e846c619604b49206204db`
- Frozen Champion profile: `strategy9-e3-research-champion-v1`
- Profile SHA-256: `1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26`
- Pinned Production/runtime: `887f479b15ad861313da666ad698034d3847121c`
- Canonical corpus SHA-256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- Warmup start: `2006-01-03`
- Measurement start: `2006-07-31`
- End session: `2026-07-31`
- Initial shadow cash: `$100,000,000`

The factual security-type scrub is closed with zero unresolved P0/P1/P2/P3 type cases. The consolidated review and interval-boundary adjudications in `security-truth/manual-review/FINAL_SECURITY_TRUTH_INTEGRATION.md` are authoritative for the final classifier.

## Resolved economic rules

### 1. Executable-order capacity

**Rule: no synthetic participation cap.**

The certificate-only 10% of prior-20 mean share-volume whole-order guard is not part of pinned Production and must not appear in the final replay. There is no capacity-sized partial-fill model and no whole-order capacity deferral.

At a positive-volume executable raw open:

- sells execute at the raw open with the frozen 10 bps side cost;
- buys are clipped only by available cash and whole-share affordability;
- any cash-unaffordable residual is not retained as a pending residual.

The final result is therefore a strategy-economics shadow replay, not a live market-impact/capacity claim.

### 2. Historical security type

**Rule: use the closed factual truth ledger as a decision-day oracle.**

A security is `common` or `non_common` according to the factually correct historical legal type for that session. Later authoritative evidence may establish the earlier fact. Future returns, prices, ranks, portfolio outcomes, survival, profitability and later index membership remain prohibited.

No unresolved type may default in either direction.

### 3. Dividend entitlement and settlement

**Entitlement rule:** prior-close ownership, after any same-session split-domain share transformation, owns the ex-date dividend. Open buyers do not receive it; open sellers retain it.

**Open-boundary rule:** the current ex-date receivable must be accrued **before** the resolved/open-equity witness is computed and before same-open pending fills. This makes the overnight allocation leg include the economic claim that belonged to the prior-close book.

**Settlement rule:** Production's configured lag is **1 trading session**. A receivable accrued on session index `gday` becomes spendable cash at `gday + 1`.

The 15-session certificate convention is not used in the production-equivalent replay.

Required event order for the relevant open boundary:

1. settle receivables already due;
2. apply effective splits;
3. capture prior-close quantities in the post-split share domain;
4. accrue current ex-date receivables with due index `gday + 1`;
5. apply terminal transformations/consideration belonging to the prior-close holding;
6. compute resolved/open equity including the newly accrued receivable;
7. execute pending exits and entries at the open.

### 4. Terminal settlement for held positions

**Rule: use the pinned Production settlement waterfall, not a research-only approximation.**

For authenticated terminal events:

- complete exact terms control;
- incomplete documented terms enter the Production C1 carried-claim lifecycle when a trustworthy mark exists;
- C1 grace is 10 sessions;
- after grace, an actual executable print outranks a proxy;
- otherwise a last trustworthy mark may settle only inside Production's mark-recency bound;
- if neither exact terms nor an admissible mark/print can resolve the holding, the book remains unresolved and new admissions are blocked;
- undocumented disappearances follow the pinned Production C2/orphan policy, including its predeclared timeout and zero-orphan semantics.

No universal last-price recovery, universal zero recovery, or return-conditioned recovery is permitted.

### 5. Terminal eligibility and retirement

**Rule: no cumulative permanent research-only retired-security set.**

A terminal event must not remove a name from the day's pre-veto cross-sectional ranking geometry. On the event session, Production's terminal rule is an admission veto after ranking. Existing pending admission intent for the terminating security is cancelled on the event session.

For later sessions, canonical episode/listing identity determines whether the old security remains available. The replay must not maintain an independent lifetime `_retired_tids` set that permanently reshapes eligibility.

### 6. Recent-leadership witness around terminal events

The prior close's selected leadership basket earns the current session's economic return.

For a prior-selected security on a terminal session:

1. use authenticated exact terminal consideration when complete;
2. otherwise use the ordinary observed signal close when available;
3. if neither produces a valid return, use Production's frozen **zero-contribution** missing-leadership convention and record the occurrence.

For the next leadership witness, compute the ranking on the ordinary unmodified eligible cross-section, then exclude securities terminal on the current session from the selected witness carried forward. This prevents a dead security from becoming a next-session constituent without letting the terminal event promote another name by changing the cross-sectional denominator/rank geometry.

No cumulative permanent retirement filter is applied.

### 7. Missing held marks and NAV

**Rule: match the Production unresolved-equity behavior.**

A held position missing a current raw mark may use its last trustworthy raw mark for estimated book valuation. The session is flagged unresolved. While unresolved, new Wealth Core admissions are blocked.

The final replay must not abort merely because an otherwise-valued held mark is stale. Conversely, a genuinely unvalued holding must not silently become zero or disappear. Production terminal-carry states remain governed by the terminal settlement waterfall above.

### 8. Existing frozen mechanics retained

The following remain unchanged: 25 slots; 4% new-entry sizing from current shadow equity; one post-initialization admission per session; 21-session slot/security cooldown; one review at age 119 or later; 30% close-based peak drawdown stop; next-positive-volume raw-open execution; 10 bps Wealth Core side cost; existing ranking, momentum, breadth and Candidate A controller parameters; structural Wealth Core cash at zero yield; existing canonical defensive-cash factor series; warmup state carried into measurement; Candidate A promoted as the authoritative research curve.

## Required implementation proof before replay

The final runner must fail closed unless source probes prove all of the following in the **exact generated program**:

- no executable-order capacity guard remains;
- every security-type decision comes from the consolidated factual truth layer or already-authoritative canonical type;
- ex-date receivable accrual precedes `open_eq` / open-equity computation;
- dividend due index is exactly `gday + 1`;
- no cumulative `_retired_tids` eligibility filter or pending-entry cancellation survives;
- current-session terminal IDs are filtered only from the next leadership witness after ranking;
- exact-terminal / observed-close / zero-contribution leadership precedence is present;
- missing held marks carry the last trustworthy mark and block admissions rather than hard-abort;
- frozen Champion/profile/corpus/runtime identities match;
- no strategy parameter or return-conditioned branch changed.

Synthetic tests must include the known dividend allocation-transition fixtures and terminal/witness fixtures. Exact generated-source hashing must be retained.

## Replay gate

**Do not run the 20-year performance replay until the implementation and source-probe suite are green.**

After that gate passes, run exactly one clean full-horizon replay. That run becomes the sole candidate for the label `PRODUCTION_EQUIVALENT_CERTIFIED`; prior 9.20%, 17.92%, 18.15%, 18.72% and 20.09% runs remain diagnostics or superseded paths and are not correctness targets.

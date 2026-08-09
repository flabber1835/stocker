# Provenance, and what the terminal-order correction changed

`README.md` and `CORRECTION_REPORT.md` are the **upstream** package documents,
verbatim, covered by `SHA256SUMS.txt` (12/12 verify clean). This file is the
repository's own record.

Source archive: `docs/Sentinel_1_1_Terminal_Order_Corrected.zip`
(sha256 `514737cc17924243cba9abb488a6728bebf2cf4ad2844f502a108d48b9dedc59`,
received 2026-08-09).

**This is the only Sentinel reference lineage to use going forward.** The
previous package (`Sentinel_1_1_Python_Only_Corrected.zip` and its
`raw_sharadar_20y_daily.csv`, `PARITY_REPORT.json`,
`transition_accounting_delta.csv`, `validate_against_frozen.py`) is DELETED. It
produced a book containing positions that could not legally have been bought.

## What was wrong, and why it is not a rounding difference

Terminal corporate actions were applied AFTER pending fills and were invisible to
close-time admissions. Two consequences, both with named instances:

```text
2023-11-29  VRTV   a pending entry FILLED into a security that was
                   acquisitionby|delisted that session — $240,788,734 of notional
                   into something that had already ceased to exist
5 sessions         a security that terminated at TODAY's close was still
                   scheduled for tomorrow's open, consuming the one-admission-
                   per-session slot and delaying a valid replacement:
                     2008-10-09 SCRX  rank 98
                     2016-02-04 SWI1  rank  7
                     2016-02-22 KING  rank  2
                     2018-10-09 SYNT  rank 10
                     2020-04-06 FTSV  rank  1
```

The fix is causal and adds no look-ahead: load the session's effective actions,
mark terminals, cancel pending entries into them, settle held terminals, then
fill, and at the close exclude anything that terminated that session.

## THE CONSEQUENCE THAT MATTERS MOST HERE

**The corrected path no longer reproduces the frozen oracle, and it should not
be expected to.** The shadow book changed, so everything downstream of it moved:

```text
first shadow/breadth/NAV divergence   2016-02-05
first allocation divergence           2025-04-08
allocation-difference sessions        20 (through 2025-05-06)
```

The corrected Sentinel goes 0% Wealth Core 2025-04-08 → 2025-05-06 where the old
path stayed at 100%.

**The breadth CLASSIFIER is unchanged.** `green`/`red`/`amber`/`sector_stress`
are the same predicates that reproduced the frozen tape 7,061/7,061. They now
produce different VALUES because their input — the holdings panel — is a
different book. Do not read the divergence as the classifier being wrong; it is
the classifier applied to a corrected portfolio.

Consequently the earlier in-repo verification (5,032/5,032 allocation and breadth
parity against `03_exact_candidate_daily.csv`) describes the SUPERSEDED lineage.
It was a true measurement of a book we now know was wrong. Item F of
`docs/sentinel-deployment.md` cannot be "reproduce the frozen tape" for this
lineage — see that document for the restated acceptance criterion.

Per upstream: **do not overwrite the frozen oracle.** `docs/sentinel-handoff/`
stays exactly as it is. It is the audit artifact showing what the old code
produced, and it remains the certification target for anyone reproducing the old
lineage deliberately.

## Performance impact

```text
                              previous raw      terminal-corrected     change
Sentinel CAGR                 22.259384%        22.094535%             -0.1648 pp
Sentinel max drawdown        -21.949046%       -21.963098%             -0.0141 pp
Sentinel ending multiple      55.677526x        54.195113x             -2.66%
Wealth Core full-history      165.814088x       173.765727x            +4.80%
```

Sentinel got slightly worse and Wealth Core got materially better. That is the
expected shape of removing phantom holdings from a book: the alpha engine stops
carrying dead weight, while the controller's severe episodes are re-timed by a
shadow whose drawdown path changed. **A correction that improved every number
would be the suspicious one.**

The endpoint book holds 20 stocks at 62.86% weight with 37.14% cash. VRTV is
gone, so the large cash balance is NOT the zombie position — it remains a
consequence of the 25-slot / 4%-entry / cooldown / no-rebalance mechanics.

## Verified in this repository, 2026-08-09

```text
sha256sum -c SHA256SUMS.txt           12/12 OK
the four controller unit tests        PASS against the corrected source
                                      (import retargeted; the only edit to any
                                      shipped file)
```

Not verified, and it is the whole claim: that running
`sentinel_1p1_standalone.py` against raw Sharadar reproduces
`sentinel_1p1_daily.csv`. That needs the corpus, which this machine does not
have. The tape is stored; the producer is unverified.

## OPEN ISSUE FOR OUR OWN WEALTH CORE

Stocker's engine has the FIRST half of this fix and appears to lack the SECOND.

```text
HAVE   shared/.../wealth_core/adapter.py orders terminal actions (step 3) BEFORE
       pending fills (step 4), and cancels a pending entry into a terminated
       security with reason TERMINATED_BEFORE_FILL. Its docstring records the
       same defect the standalone just found — "a pending ENTRY plus a same-day
       merger BOUGHT a security that had already terminated"
LACK   `terminated` is passed to the fill loop and to the orphan/grace sweeps,
       but NOT to `decide()`. So an admission decided at today's close can still
       name a security that terminated today
```

The failure mode differs from the standalone's. A delisted security has no
executable bar at the next open, so the order does not fill — it takes the
`b is None or not b.can_execute` branch, increments `sessions_waiting`, and stays
pending. The slot is occupied by an order that can never fill, which is the same
harm ("consumed the one-admission-per-session mechanism and delayed valid
replacements") reached by a different route.

This is NOT fixed here. It is a Wealth Core semantics change: it would move the
golden hash, require a decomposed re-pin, and invalidate any rehearsal in flight.
It needs a deliberate decision, and the falsifier is already written for us —
`terminal_close_admission_blocks.csv` names five dated instances to reproduce.

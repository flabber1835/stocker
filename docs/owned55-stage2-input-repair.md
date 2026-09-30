# Owned55 Stage 2 historical input repair

Status: input repair in progress; **no Stage 2 financial certification or long-run
authorization**. This decision applies to the retained 252-session warmup,
126-session formation, $50,000 funded measurement scenario. It does not change
production feed publication or Wealth Core accounting.

## Event chronology decision

The retained research adapter used `effective_session` to replace a raw
terminal row only *on that same session*. Changing a supplement's date by
itself therefore leaves the incomplete raw action on the earlier session.
For the 12 dated cash mergers in `research/stage2_actions/chronology.json`, the
repair binds a supplement to one exact raw security, action kind, original
session and missing-cash disposition; removes that one raw row; and inserts one
completed row on the documented legal-completion session. Duplicate, absent,
changed, or colliding source rows refuse. The original archive and the previous
run stay immutable. The new binding includes the source hashes and repair file.

The canonical kernel consumes terminal actions at session resolution. A
date-only completion is recognized at that session's close. The modeled cash
can therefore fund no *earlier* open. This is a conservative research timing
convention, not evidence of broker credit. A pre-open filing still establishes
the legal date; it does not establish when a particular broker made proceeds
spendable. Prior final-trading sessions retain the source market price. A
completion-session mark can be absent only when the terminal event resolves the
held position on that session; valuation must otherwise refuse. IKN's retained
October 31 quote is missing, so the corrected October 31 terminal must be
exercised against the canonical transition before accepting a long run.

The 12 event dates and terms are sourced to issuer filings in the repair file.
They are DRS1, IKN, BUD1, CEPH, GR, SWI1, SAIL1, SWCH, FOCS, ATSG, PYCR and
SWI. The first 11 were in the September 28 timing review; SWI was found in the
subsequent cash audit. The corrected event is not a claim that consideration
was known at the session open. In particular, the GR July 26 open cannot be
funded with a July 25 merger payout after this repair.

The formed 20-year runner that produced the prior result is retained only in a
frozen research snapshot; it is not part of current `main`. Its old adapter
would still reintroduce the obsolete raw event if given only the new supplement
file. A future current-main runner must consume the corrected
`terminal-schedule.json` (or the same checked reconciliation function) and bind
its hash. The two output files are a pair; neither is a standalone run input.

PLYA is not folded into the cash-merger correction. Hyatt paid shares validly
tendered in its offer, while non-tendered shares followed a June 17 back-end
transaction. The retained book has no tender instruction or broker tender
receipt. Its June 13 generic cash conversion cannot establish which route the
held shares took. The passive-holder chronology, terminal valuation over the
nontrading interval, and cash-credit date require independent adjudication.
See [Hyatt's June 17 filing](https://www.sec.gov/Archives/edgar/data/1468174/000110465925060325/tm2518204d1_8k.htm).

## 2005 split source decision

The prefix remains `FAIL`. FSNMQ's issuer announced a 2-for-1 split effective
February 9, but the retained raw/signal price relationship changes on March
10, when a separate 2-for-1 event is already applied. Applying both would
double shares. [Issuer release](https://www.sec.gov/Archives/edgar/data/897861/000119312505010637/dex991.htm).
FCEC's vendor reports 1.1 on April 28; the retained price relationship changes
April 29, and the April 28 row is untradeable. The issuer's historical filing
shows a 2005 stock dividend, but the exact ex-date and the adjustment of the
retained observation/volume domain still need source reconciliation.
[Issuer filing](https://www.sec.gov/Archives/edgar/data/744126/000074412608000010/form10k_2007.htm).
The prior current-code reachability proof makes both identities irrelevant to
that frozen strategy only; it does not turn a failed source manifest into PASS.

## Other cash and security claims still open

The existing research supplements use price proxies for held BRL, SGP1, FDO,
HPY, CWEI and ITC fractional cash; prior-day FX for FALB; first-open child
prices for LVNTA; and an A-equivalent proxy for VMED's separate Class C shares.
LVGO omits an identified special dividend. Those need exact paying-agent/market
inputs or an explicit
bounded-error acceptance study before financial certification. The pre-BIL
Treasury sleeve uses lagged GS3M, which is a stated model assumption rather
than an observed broker cash return. Actual cash credit and settlement timing
have not been proven for the merger proceeds.

## Validation gate before the long run

1. Validate the 12 source rows and produce a new, hash-bound supplement file.
2. Exercise the canonical session transition on each affected date: original
   day retains shares and cash, completion day pays once, slot cooldown begins
   at corrected exit, and an age-20 replacement cannot enter. Test IKN's
   missing quote and GR's July 26 affordability explicitly.
3. Resolve PLYA, both 2005 split conflicts, and cash/stock proxies, or retain
   a clearly scoped research-only exception with a falsified reachability and
   error-bound proof. Neither path by itself grants provider or broker authority.
4. Bind a current-main runtime and all admitted inputs, then decide together
   whether to launch one new 20-year replay. Old checkpoints and returns cannot
   be spliced into that replay.

## Reproduction of the bounded repair

From the repository root, use the retained licensed input files and a new output
directory:

```text
python -m research.stage2_actions.repair --archive .codex-tmp/pit-source-5bdc6b39.zip --supplements .codex-tmp/owned55-formed-20y-run/qualification-001/supplements.json --output .codex-tmp/<new-repair-directory>
python -m research.stage2_actions.validate_retained --schedule .codex-tmp/<new-repair-directory>/terminal-schedule.json --cases .codex-tmp/owned55-formed-20y-run/qualification-001/timing-review-20260928/cases.json --output .codex-tmp/<new-repair-directory>/held-validation.json
```

The export verifies the 1.5 GB archive and retained supplement hashes, writes
both transformed files without overwriting an existing directory, and records
their hashes and remaining blockers. The held check exercises 11 genuine held
episodes through the canonical terminal primitive. These checks do not advance
the complete strategy/controller session.

Local bounded export on September 29, 2026 verified archive SHA-256
`7d86c6f728f0392516dec5e2a709c16d45b2f46bc139fe7f3d29af25ae4dfce8`
and source-supplement SHA-256
`aac7fd0e9110503f6b32c26ba93e8bbb044b2ada494ba2b8ca88e968dde09aa5`.
It suppressed 12 raw events and produced 12 later completions. The corrected
terminal schedule SHA-256 is
`c9e70843f53283aacd1dae53307b39fb9868734ef95430db83df1a4959bf1def`;
the corrected supplement SHA-256 is
`dbb5534beff8227456ccdf8fe325c20b907a1eba384dbd8d5676cabecf94a970`.
The 11 retained held-episode primitive checks passed. The derived local files
remain outside Git because they contain licensed source data.

# Bounded production economic replay

Owner authorization, 2026-09-20: reuse the corrected historical inputs, add
source-backed RSAS terms, run a ten-minute pilot, and continue the same book
through twenty years only if the measured projection fits two hours. Stop at
the next unresolved economic input instead of researching indefinitely.

Verified main base: `48f88fd4f3957c0dfc264e2eef2e35ecd753c9c1`.
Production revision: PR #425, `624395dd04c48af7de3a8930cfd586ca2cc81245`,
still unmerged when this experiment started. Delivery is a separate PR to main,
dependent on #425. No production algorithm is changed for this experiment.

## Input and timing decisions (before implementation)

Reuse the previous provisional runner's fresh USD 100,000 account at the
2006-07-31 close, 252 feature-only warmup sessions, continuous ownership and
controller state, benchmark partition bridge, and production scalar accountant.
Measurement ends 2026-07-31. Unknown security classifications stay ineligible;
all retained spin-offs reach the production entitlement guard. The prior run's
artifacts and all golden references remain unchanged.

Use schema-2 dataset
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
and the independently retained exact 2005 prefix. Verify archive and all member
hashes. This includes existing ARXX, CYTC and TRB corrections. Bind source
hashes to #425; do not claim parity with the historical champion's different
starting book or classification overlay.

RSAS retains its original incomplete 2006-09-15 event. Add exact cash terms at
the next session, 2006-09-18, when the completion announcement is dated. The
June 29 agreement specifies $28 per common share; EMC's September 18 8-K
confirms completion on September 15 and the same consideration. Do not apply
the later completion evidence to a September 15 opening decision. This is a
session-granular retrospective settlement input, not proof of a provider's
intraday publication or broker cash availability. The canonical terminal
accounting convention settles the modeled entitlement when terms are supplied.

Sources:
- https://www.sec.gov/Archives/edgar/data/932064/000095013506004177/b614778ke8vk.htm
- https://www.sec.gov/Archives/edgar/data/790070/000119312506192225/d8k.htm
- https://www.sec.gov/Archives/edgar/data/790070/000119312506192225/dex992.htm

The adapter must bind the supplemental row to the retained RSAS security ID,
original event date and missing-cash disposition. Reject mismatches and duplicate
replacement terms. Record both original event and supplement in provenance.
Do not use the old research rule that proxy-settled missing terms at a carried
price after ten missing sessions. Unresolved valuations still stop this replay.

## Budget and interpretation

The pilot clock includes input verification and warmup. After ten minutes,
project the remaining sessions using observed measured-session time plus a 20%
margin. Continue only within a total two-hour execution budget; otherwise retain
a diagnostic prefix and timing estimate. Check the deadline between sessions;
one in-progress production transition may finish after the soft deadline.
Checkpoint every 300 sessions without resetting the book. No parallel books,
broker services, PostgreSQL, NAS access or parameter optimization are involved.

Only a complete, resolved 5,032-session path can supply twenty-year CAGR,
multiple, final value and maximum drawdown. A stopped pilot reports no headline
return. A completed result remains provisional economic-engine evidence, not
full-service or deployment certification. Core fills and costs are those of
the pinned production engine; defensive cash factors retain dataset provenance,
including the Treasury-rate proxy before BIL existed.

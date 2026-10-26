# Zero-share entry admission

Owner direction, 2026-10-26: fix the deterministic zero-share cancellation and
requeue loop directly. Pooling and new Sentinel exposure rules are not part of
this correction.

## Failure and selected correction

V5 binds an intended dollar budget of NAV / 20 at a close. Its opening quantity
is the minimum of whole shares affordable by that budget and by settled total
cash, including transaction costs. The close previously tested only total cash.
For example, NAV $100,000 and cash $100,000 admitted a $6,000 stock into a $5,000
intent. At an unchanged open, the intent sized to zero, released its reservation,
and could be admitted again at the next close.

Admission must require the existing opening sizing function to return at least
one share at the current raw closing price and the same intended budget, settled
cash and transaction-cost inputs. Total-cash feasibility also uses the canonical
exact whole-share affordability helper. Keep distinct total-cash and
intended-budget rejection reasons under REJECT_INSUFFICIENT_CASH.

This is a post-ranking admission check, before any reservation or admission count
is consumed. An unaffordable candidate remains in the ranking/leadership
population; another qualified candidate can use an available slot. Eligibility
is re-evaluated each close, so a genuinely affordable candidate may enter later.
Do not add retry caches, synthetic cooldowns, new book state, or broker feedback.

The NAV / 20 dollar intent, settled-total-cash opening cap, positive cash-clipped
fills, cash-scarcity cushion and both 21-session cooldowns remain unchanged.
In particular, do not subtract the close admission cushion from opening cash or
require the full intended position to be funded.

## Timing, identity and limits

Future opens are unknown. Price gaps or intervening cash changes can still yield
zero at an open after an affordable close. Preserve that safe cancellation and
reservation release, and reassess using the next close's facts. The correction
prevents knowingly infeasible close intents; it does not claim to guarantee a
future fill or prohibit ordinary daily eligibility checks.

The V5 sizing profile continues to identify the unchanged sizing equation. The
source-derived strategy identity changes with this admission correction; old
results and checkpoints retain their original source identity. Do not repin
frozen research references, relabel checkpoints, reset the installed book, or
automatically deploy this PR. Existing source-handover and PAPER release gates
remain applicable. No new performance claim is made.

## Required regression evidence

- An unchanged high-priced candidate with ample cash and an insufficient NAV/20
  budget produces no pending entry, opening attempt, zero-share cancellation,
  reservation leak or cooldown across repeated sessions and state restoration.
- A candidate becomes admissible when its actual budget/price becomes feasible.
- The known positive AGN1 cash-clipped entry remains admissible and fills.
- Exact one-share budget/cash boundaries, transaction costs and float neighbors
  agree with the opening quantity helper.
- Removing the intended-budget guard makes the repeated-session regression fail.
- Ordinary gap-caused zero cancellation/release remains safe, and a rejected
  candidate does not consume a slot or exclude another qualified candidate.

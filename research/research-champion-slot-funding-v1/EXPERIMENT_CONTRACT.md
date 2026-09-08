# Corrected Research Champion slot-funding experiment v1

Status: **RESEARCH ONLY — NO PRODUCTION PROMOTION**

## Question

What does the frozen 25-slot / 4% Research Champion + E3/LD-RC architecture do when the Wealth Core admission defect is corrected so that a physical slot can only be claimed by a fully funded decision-time whole-share target?

This is a one-factor economic counterfactual. It is not a search for a better CAGR and it must not tune any threshold after observing results.

## Immutable parent identities

- Corrected current-kernel research head at experiment creation: `bd5ba4572fb170ac5a5ac24c408c27ac2fe1b823`.
- Current kernel funding identity: `entry_funding_profile = full_whole_share_target_v1`.
- Certified historical Research Champion source: `27bb992087182c42c3c051e62bf837895f5d2ab7`.
- Historical pinned runtime authority: `887f479b15ad861313da666ad698034d3847121c`.
- Historical Champion profile: `strategy9-e3-research-champion-v1`.
- Warm-up start: `2006-01-03`.
- Measurement start: `2006-07-31`.
- End session: `2026-07-31`.
- Dividend settlement lag: 15 sessions.

## Frozen Champion / E3 economics

- 25 physical slots.
- 4% nominal entry target.
- 10 bps traded-side cost.
- age-119 review.
- 21-session cooldown.
- 30% trailing stop retention.
- Strategy 9 selector and E3 recovery-concordance architecture unchanged.
- LD-RC: `REC=8`, `R20=-0.085`, `V=0.11`, `DD=-0.10`.
- divergence SPY floor = 0.0.
- full-recovery r40 floor = 0.0.
- FAST damaged breadth = 0.88.
- healthy damaged ceiling = 0.63.
- terminal grace, resolved-NAV, identity, PIT, corporate-action and execution-timing semantics unchanged.

## The only intended economic change

Legacy retained-research admission did this:

```text
target = min(equity * entry_weight, cash)
shares = floor(target / decision_per_share_cost)
```

and later allowed the pending order to use whatever account cash happened to exist at the executable open.

The corrected experiment does this:

1. Compute the complete decision-time whole-share target from `equity * entry_weight`.
2. Compute its exact required cash including transaction cost.
3. Define uncommitted cash as account cash minus the cash budgets of all still-pending entry reservations.
4. Reject the admission if uncommitted cash cannot fund the complete target. A rejected candidate claims no slot.
5. On admission, reserve the slot **and** the exact decision-time cash budget persistently.
6. A non-tradeable next session keeps that reservation.
7. At an executable open, the order may be share-clipped by an upward gap only inside its already-reserved dollar budget. Later sales, dividends or other unrelated cash cannot enlarge or rescue it.
8. If the reserved budget cannot buy even one share, cancel the entry and release the slot/budget.
9. Split/terminal cancellation also releases the cash reservation.

No minimum-fill percentage is introduced. No winner trimming, leverage, top-up or fractional slot accounting is introduced.

## Isolation method

The current repository no longer carries the retired root `backtester/` tree. The experiment therefore must **not** merge the historical Research Champion branch into current code.

The workflow will:

1. check out this current research branch;
2. verify the current corrected kernel identity;
3. check out exact certified historical Champion source `27bb992...` read-only under `legacy/`;
4. check out its pinned runtime authority read-only under `legacy/main-src/`;
5. pull and verify the same immutable canonical PIT-v2 package;
6. import the certified Champion transform chain and wrap its final generated source with a pre-registered exact-seam slot-funding patch;
7. refuse if any expected source seam occurs other than exactly once;
8. compile/self-test the corrected generated source before the full replay;
9. run the full chronological PIT replay;
10. emit structural diagnostics first, then performance diagnostics as a separate phase.

Historical source files are not edited in git. Results are uploaded as workflow artifacts and are not committed automatically.

## Required structural evidence

The replay must report at least:

- funding-rejected admission count and affected sessions;
- decision-time reserved cash and uncommitted cash;
- held, pending and ready slot counts;
- sessions with vacancies;
- entry fill count;
- next-open gap-clipped fill count;
- next-open reserved-budget cancellation count;
- minimum actual/planned share fraction among filled entries;
- cash / Wealth Core equity distribution;
- end-book held/pending/ready counts;
- proof that aggregate reserved entry cash never exceeds actual account cash and uncommitted cash never becomes materially negative.

## Interpretation discipline

Structural validity is evaluated before performance. Performance cannot be used to change this funding rule.

The result may invalidate or preserve later architectural choices, but it does not automatically promote any of them. If the corrected 25x4 Research Champion baseline is coherent, portfolio-size research is restarted from that baseline. Caesar-20 and Median-5 must earn their way back in independently.

This experiment is not itself a production certificate and must never emit or be described as a production GO.
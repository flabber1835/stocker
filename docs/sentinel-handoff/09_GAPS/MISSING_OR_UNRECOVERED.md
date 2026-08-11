# Missing / unrecovered artifacts

## 1. Security-level damaged/green breadth classifier — RECOVERED 2026-08-09

> **STATUS CHANGED. The section below described the HANDOFF BUNDLE, and was
> accurate for it. The classifier has since arrived by a different route and is
> in this repository.**
>
> ```text
> docs/sentinel-reference-implementation/sentinel_1p1_standalone.py
> ```
>
> labelled in the source as *"Exact recovered breadth classifier, computed
> directly from current shadow holdings"*. Its exact rules — and three
> properties that are silent if got wrong — are recorded in
> `docs/sentinel-controller-certification.md` §7a.
>
> **Read the standalone source, not a prose summary.** §7b of that document
> records a case in point: `sentinel-architecture.md` §8 states GREEN as
> `own_dd >= -7.5% AND r21 >= 0 AND r63 >= 0`, and the recovered code says
> `own_dd > -0.075 AND r21 > 0 AND (age < 63 OR r63 > 0)` — strict comparisons,
> plus an age escape absent from the prose that makes every holding younger than
> 63 sessions GREEN with no r63 test at all.
>
> The requirement below still stands and is unchanged: **it must reproduce the
> frozen breadth tape before it is accepted.** Recovered is not certified.

Status at handoff: **NOT FOUND in the retained artifacts searched for this
handoff.**

What is retained:
- Complete daily aggregate `damaged` / `green` breadth tape.
- Sentinel 1.1 exact daily oracle containing `damaged` and `green`.
- Position-level research scripts that reconstruct holding-day state (`own_dd`, momentum horizons, etc.) and later consume `green` / `red` classifications.

What is not retained/located:
- The original function/script that assigned each security-level holding to damaged/green (or green/red/amber) before aggregation.

Required behavior:
- Do **not** reverse engineer and silently call it certified.
- Search any older notebooks/temp files/source archives if they become available.
- If a candidate classifier is reconstructed, it must reproduce the frozen breadth tape before it can be accepted.

## 2. Full monolithic original interactive Python session
The ChatGPT research work persisted many result bundles and source fragments, but not every ephemeral notebook cell/script appears as a standalone library file. The package therefore distinguishes original retained source from derived oracle outputs.

## 3. Production share-level execution equivalence
The research Sentinel overlay is scalar. A real broker implementation must project shadow target holdings into actual integer-share orders, handle no-print legs and pending orders, and persist target vs realized exposure. That production execution layer is new work and should be certified separately from the controller oracle.
